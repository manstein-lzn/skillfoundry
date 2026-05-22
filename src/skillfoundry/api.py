"""WP9 minimal internal API/UI over the offline SkillFoundry factory."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4
import zipfile

from .contracts import BUILD_NODE_CONTRACT_REF, GOAL_CONTRACT_REF, VERIFICATION_GATE_REF
from .frontdesk_loop import FrontDeskLoopResult, run_frontdesk_round
from .frontdesk_schema import ConversationTurn, FrontDeskConfig, FrontDeskState, PlanReviewRecord
from .frontdesk_v2 import (
    FRONTDESK_V2_GOAL_CONTRACT_REF,
    FRONTDESK_V2_GOVERNANCE_REPORT_REF,
    FRONTDESK_V2_MANIFEST_REF,
)
from .frontdesk_workspace import (
    FRONTDESK_BUDGET_REF,
    FRONTDESK_CONVERSATION_REF,
    FrontDeskWorkspace,
    append_conversation_turn,
    initialize_frontdesk_workspace,
    read_conversation_turns,
    write_frontdesk_artifact,
)
from .goal_runtime import GOAL_RUNTIME_LEDGER_REF, GOAL_RUNTIME_RESULT_REF, GOAL_RUNTIME_STATE_REF
from .live_llm import DEFAULT_FRONTDESK_MODEL, OpenAIChatCompletionsClient
from .offline import OfflineWorkerMode, build_offline, read_final_report
from .registry import APPROVAL_APPROVED, LocalSkillRegistry, QUARANTINE_NONE
from .schema import JsonValue, RegistryEntry, ensure_json_compatible, sha256_file
from .security import PathSecurityError, assert_under_root, resolve_under_root, validate_relative_path
from .verification_bridge import CONTEXTFORGE_VERIFICATION_RESULT_REF
from .workspace import JOB_ID_RE, JobWorkspace, initialize_job_workspace


API_VERSION = "skillfoundry.api.wp9.v1"
FRONTDESK_API_VERSION = "skillfoundry.api.frontdesk.v1"
DEFAULT_SERVE_HOST = "127.0.0.1"
DEFAULT_SERVE_PORT = 8765
FRONTDESK_STATE_REF = "frontdesk/state.json"
FRONTDESK_CORE_NEED_BRIEF_REF = "frontdesk/core_need_brief.json"
FRONTDESK_SOLUTION_PLAN_REF = "frontdesk/solution_plan.json"
FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF = "frontdesk/solution_plan.md"
PLAN_REVIEW_REF_TEMPLATE = "frontdesk/plan_review_{sequence:03d}.json"
FrontDeskClientFactory = Callable[[str, str, int], Any]


class APIError(ValueError):
    """Expected request failure for the minimal WP9 API."""

    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict[str, JsonValue]:
        return {"error": {"code": self.code, "message": self.message}}


@dataclass(frozen=True)
class APIHTTPResult:
    """Small response object shared by tests and the stdlib HTTP wrapper."""

    status: int
    content_type: str
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()

    def json(self) -> dict[str, JsonValue]:
        payload = json.loads(self.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("response body is not a JSON object")
        return ensure_json_compatible(payload)  # type: ignore[return-value]


@dataclass(frozen=True)
class OptionalJsonRefRead:
    """Result of reading an optional JSON workspace artifact."""

    exists: bool
    valid: bool
    payload: dict[str, JsonValue] | None = None
    error_code: str | None = None


class SkillFoundryAPI:
    """Minimal synchronous service for WP9 internal use.

    This class deliberately does not introduce a queue, auth platform, frontend
    framework, provider dependency, or live Codex dependency. It is a small
    request boundary around the existing deterministic offline factory.
    """

    def __init__(
        self,
        runs_root: str | Path,
        *,
        registry_path: str | Path | None = None,
        frontdesk_client_factory: FrontDeskClientFactory | None = None,
        frontdesk_model: str | None = None,
    ) -> None:
        self.runs_root = Path(runs_root).expanduser()
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self._runs_root_resolved = self.runs_root.resolve(strict=True)
        self.registry_path = self._resolve_registry_path(registry_path)
        self.frontdesk_client_factory = frontdesk_client_factory
        self.frontdesk_model = frontdesk_model or os.environ.get("SKILLFOUNDRY_FRONTDESK_MODEL", DEFAULT_FRONTDESK_MODEL)

    def create_job(self, payload: Mapping[str, Any]) -> dict[str, JsonValue]:
        """Create one synchronous offline job from a JSON-like payload."""

        if not isinstance(payload, Mapping):
            raise APIError(400, "invalid_json", "request body must be a JSON object")

        job_id = payload.get("job_id")
        if job_id is None or job_id == "":
            job_id = self._generate_job_id()
        if not isinstance(job_id, str):
            raise APIError(400, "invalid_job_id", "job_id must be a string")
        safe_job_id = self._validate_job_id(job_id)

        requirement = payload.get("requirement")
        if not isinstance(requirement, str) or not requirement.strip():
            raise APIError(400, "invalid_requirement", "requirement must be a non-empty string")

        worker_mode = payload.get("worker_mode")
        if worker_mode is not None:
            if not isinstance(worker_mode, str):
                raise APIError(400, "invalid_worker_mode", "worker_mode must be a string")
            try:
                worker_mode = OfflineWorkerMode(worker_mode).value
            except ValueError as exc:
                raise APIError(400, "invalid_worker_mode", f"unknown worker_mode: {worker_mode}") from exc

        attempt_limit = self._coerce_attempt_limit(payload.get("attempt_limit", 2))
        job_root = self._job_root(safe_job_id)
        if job_root.exists() and any(job_root.iterdir()):
            raise APIError(409, "job_exists", f"job already exists: {safe_job_id}")

        requirement_path = self._write_requirement(safe_job_id, requirement)
        try:
            result = build_offline(
                requirement_path=requirement_path,
                output=job_root,
                registry_path=self.registry_path,
                worker_mode=worker_mode,
                attempt_limit=attempt_limit,
            )
        except FileExistsError as exc:
            raise APIError(409, "job_exists", str(exc)) from exc
        except ValueError as exc:
            raise APIError(400, "job_create_failed", str(exc)) from exc

        return self._job_payload(safe_job_id, report=result.final_report)

    def create_frontdesk_job(self, payload: Mapping[str, Any]) -> dict[str, JsonValue]:
        """Create a real Front Desk clarification job and run one round."""

        if not isinstance(payload, Mapping):
            raise APIError(400, "invalid_json", "request body must be a JSON object")
        job_id = payload.get("job_id")
        if job_id is None or job_id == "":
            job_id = self._generate_job_id()
        if not isinstance(job_id, str):
            raise APIError(400, "invalid_job_id", "job_id must be a string")
        safe_job_id = self._validate_job_id(job_id)
        message = payload.get("message", payload.get("requirement"))
        if not isinstance(message, str) or not message.strip():
            raise APIError(400, "invalid_message", "message must be a non-empty string")
        job_root = self._job_root(safe_job_id)
        if job_root.exists() and any(job_root.iterdir()):
            raise APIError(409, "job_exists", f"frontdesk job already exists: {safe_job_id}")
        if self.frontdesk_client_factory is None and not os.environ.get("OPENAI_API_KEY"):
            raise APIError(503, "openai_api_key_missing", "OPENAI_API_KEY is required for live Front Desk trial")

        workspace = initialize_job_workspace(self._runs_root_resolved, safe_job_id)
        frontdesk = initialize_frontdesk_workspace(workspace)
        append_conversation_turn(
            frontdesk,
            ConversationTurn(
                turn_id="turn-001",
                role="user",
                content=message.strip(),
                metadata={"source": "api"},
            ),
        )
        result = self._run_frontdesk_round(frontdesk)
        return self._frontdesk_payload(safe_job_id, result=result)

    def append_frontdesk_message(self, job_id: str, payload: Mapping[str, Any]) -> dict[str, JsonValue]:
        """Append one user message and run the next Front Desk round."""

        if not isinstance(payload, Mapping):
            raise APIError(400, "invalid_json", "request body must be a JSON object")
        safe_job_id = self._validate_job_id(job_id)
        message = payload.get("message", payload.get("answer"))
        if not isinstance(message, str) or not message.strip():
            raise APIError(400, "invalid_message", "message must be a non-empty string")
        if self.frontdesk_client_factory is None and not os.environ.get("OPENAI_API_KEY"):
            raise APIError(503, "openai_api_key_missing", "OPENAI_API_KEY is required for live Front Desk trial")

        job_root = self._require_job_root(safe_job_id)
        workspace = JobWorkspace(root=job_root, job_id=safe_job_id)
        frontdesk = FrontDeskWorkspace(workspace)
        turns = read_conversation_turns(frontdesk)
        append_conversation_turn(
            frontdesk,
            ConversationTurn(
                turn_id=f"turn-{len(turns) + 1:03d}",
                role="user",
                content=message.strip(),
                metadata={"source": "api"},
            ),
        )
        state = self._read_frontdesk_state(frontdesk)
        result = self._run_frontdesk_round(frontdesk, state=state)
        return self._frontdesk_payload(safe_job_id, result=result)

    def review_frontdesk_plan(self, job_id: str, payload: Mapping[str, Any]) -> dict[str, JsonValue]:
        """Record a user plan review decision and advance the Front Desk state."""

        if not isinstance(payload, Mapping):
            raise APIError(400, "invalid_json", "request body must be a JSON object")
        safe_job_id = self._validate_job_id(job_id)
        decision = payload.get("decision")
        if decision not in {"approve", "request_revision", "reject", "human_review"}:
            raise APIError(
                400,
                "invalid_plan_review_decision",
                "decision must be approve, request_revision, reject, or human_review",
            )

        job_root = self._require_job_root(safe_job_id)
        workspace = JobWorkspace(root=job_root, job_id=safe_job_id)
        frontdesk = FrontDeskWorkspace(workspace)
        state = self._read_frontdesk_state(frontdesk)
        if state is None or state.solution_plan_ref is None:
            raise APIError(409, "solution_plan_missing", "frontdesk solution plan is not ready for review")
        if state.readiness not in {"awaiting_plan_review", "plan_revision_requested"}:
            raise APIError(409, "plan_review_not_available", "frontdesk job is not awaiting plan review")

        round_index = _frontdesk_report_index(state.latest_elicitation_report_ref) or max(1, state.clarification_round)
        plan_ref = state.solution_plan_ref
        plan_path = workspace.resolve_path(plan_ref, must_exist=True)
        reason = str(payload.get("reason") or payload.get("message") or "User reviewed the solution plan.").strip()
        requested_changes = _coerce_string_list(payload.get("requested_changes"))
        if decision == "request_revision" and not requested_changes and reason:
            requested_changes = [reason]
        review = PlanReviewRecord(
            review_id=f"plan-review-{round_index:03d}",
            solution_plan_ref=plan_ref,
            decision=decision,
            reviewer_id=str(payload.get("reviewer_id") or "api-user"),
            reviewer_role=str(payload.get("reviewer_role") or "requesting_user"),
            reason=reason,
            requested_changes=requested_changes,
            source_hash=sha256_file(plan_path),
        )
        review_ref = PLAN_REVIEW_REF_TEMPLATE.format(sequence=round_index)
        write_frontdesk_artifact(frontdesk, review_ref, review)

        if decision == "approve":
            approved_state = _copy_frontdesk_state(
                state,
                stage="freeze_approved_plan",
                frontdesk_phase="freeze",
                readiness="plan_approved",
                next_action="freeze_approved_plan",
                latest_plan_review_ref=review_ref,
                human_review_required=False,
            )
            write_frontdesk_artifact(frontdesk, "state.json", approved_state.to_dict())
            result = self._run_frontdesk_round(frontdesk, state=approved_state)
            return self._frontdesk_payload(safe_job_id, result=result)

        if decision == "reject":
            rejected_state = _copy_frontdesk_state(
                state,
                stage="complete",
                frontdesk_phase="failed",
                readiness="rejected",
                next_action="reject",
                latest_plan_review_ref=review_ref,
                human_review_required=False,
            )
            write_frontdesk_artifact(frontdesk, "state.json", rejected_state.to_dict())
            return self._frontdesk_payload(safe_job_id, state=rejected_state)

        if decision == "human_review":
            human_state = _copy_frontdesk_state(
                state,
                stage="human_review",
                frontdesk_phase="failed",
                readiness="human_review_required",
                next_action="human_review",
                latest_plan_review_ref=review_ref,
                human_review_required=True,
            )
            write_frontdesk_artifact(frontdesk, "state.json", human_state.to_dict())
            return self._frontdesk_payload(safe_job_id, state=human_state)

        revision_count = state.plan_revision_count + 1
        config = FrontDeskConfig.read_json_file(workspace.resolve_path(FRONTDESK_BUDGET_REF, must_exist=True))
        if revision_count > config.max_plan_revision_rounds:
            review_state = _copy_frontdesk_state(
                state,
                stage="human_review",
                frontdesk_phase="failed",
                readiness="human_review_required",
                next_action="human_review",
                latest_plan_review_ref=review_ref,
                plan_revision_count=revision_count,
                human_review_required=True,
            )
            write_frontdesk_artifact(frontdesk, "state.json", review_state.to_dict())
        else:
            turns = read_conversation_turns(frontdesk)
            revision_text = _plan_revision_message(reason=reason, requested_changes=requested_changes)
            append_conversation_turn(
                frontdesk,
                ConversationTurn(
                    turn_id=f"turn-{len(turns) + 1:03d}",
                    role="user",
                    content=revision_text,
                    metadata={
                        "source": "api_plan_review",
                        "plan_review_ref": review_ref,
                        "decision": "request_revision",
                    },
                ),
            )
            review_state = _copy_frontdesk_state(
                state,
                stage="revise_plan",
                frontdesk_phase="user_review",
                readiness="plan_revision_requested",
                next_action="plan_solution",
                latest_plan_review_ref=review_ref,
                plan_revision_count=revision_count,
                human_review_required=False,
            )
            write_frontdesk_artifact(frontdesk, "state.json", review_state.to_dict())
            result = self._run_frontdesk_round(frontdesk, state=review_state)
            return self._frontdesk_payload(safe_job_id, result=result)
        return self._frontdesk_payload(safe_job_id, state=review_state)

    def retry_frontdesk_job(self, job_id: str) -> dict[str, JsonValue]:
        """Retry the current Front Desk model round without appending a user turn."""

        safe_job_id = self._validate_job_id(job_id)
        if self.frontdesk_client_factory is None and not os.environ.get("OPENAI_API_KEY"):
            raise APIError(503, "openai_api_key_missing", "OPENAI_API_KEY is required for live Front Desk trial")

        job_root = self._require_job_root(safe_job_id)
        workspace = JobWorkspace(root=job_root, job_id=safe_job_id)
        frontdesk = FrontDeskWorkspace(workspace)
        state = self._read_frontdesk_state(frontdesk)
        if state is None:
            raise APIError(409, "frontdesk_state_missing", "frontdesk state is missing")
        if state.readiness == "failed":
            report_index = _frontdesk_report_index(state.latest_elicitation_report_ref)
            if report_index is None:
                raise APIError(409, "frontdesk_retry_not_available", "frontdesk job is not retryable")
            state = FrontDeskState(
                job_id=state.job_id,
                stage="elicit",
                frontdesk_phase=state.frontdesk_phase,
                clarification_round=report_index,
                core_need_round=state.core_need_round,
                plan_revision_count=state.plan_revision_count,
                readiness="needs_clarification",
                latest_core_need_report_ref=state.latest_core_need_report_ref,
                core_need_brief_ref=state.core_need_brief_ref,
                decision_ledger_ref=state.decision_ledger_ref,
                solution_plan_ref=state.solution_plan_ref,
                solution_plan_markdown_ref=state.solution_plan_markdown_ref,
                latest_plan_review_ref=state.latest_plan_review_ref,
                latest_elicitation_report_ref=state.latest_elicitation_report_ref,
                latest_audit_report_ref=state.latest_audit_report_ref,
                skill_spec_ref=state.skill_spec_ref,
                acceptance_criteria_ref=state.acceptance_criteria_ref,
                verification_spec_ref=state.verification_spec_ref,
                next_action="elicit",
                human_review_required=False,
                frontdesk_budget_ref=state.frontdesk_budget_ref,
                risk_report_ref=state.risk_report_ref,
                freeze_gate_result_ref=state.freeze_gate_result_ref,
                freeze_manifest_ref=state.freeze_manifest_ref,
                acceptance_coverage_plan_ref=state.acceptance_coverage_plan_ref,
            )
        if state.readiness in {"frozen", "human_review_required", "rejected"}:
            raise APIError(409, "frontdesk_retry_not_available", "frontdesk job is not retryable")
        self._ensure_frontdesk_retry_budget(frontdesk)
        result = self._run_frontdesk_round(frontdesk, state=state)
        return self._frontdesk_payload(safe_job_id, result=result)

    def get_frontdesk_job(self, job_id: str) -> dict[str, JsonValue]:
        """Return Front Desk state, questions, and artifact refs for one job."""

        safe_job_id = self._validate_job_id(job_id)
        job_root = self._require_job_root(safe_job_id)
        workspace = JobWorkspace(root=job_root, job_id=safe_job_id)
        frontdesk = FrontDeskWorkspace(workspace)
        state = self._read_frontdesk_state(frontdesk)
        return self._frontdesk_payload(safe_job_id, state=state)

    def list_jobs(self) -> dict[str, JsonValue]:
        """List known job directories below ``runs_root``."""

        jobs = [self._job_summary(path.name) for path in self._job_dirs()]
        return ensure_json_compatible(
            {
                "schema_version": API_VERSION,
                "jobs": jobs,
                "count": len(jobs),
            }
        )  # type: ignore[return-value]

    def get_job(self, job_id: str) -> dict[str, JsonValue]:
        """Return a job payload, including final report when present."""

        safe_job_id = self._validate_job_id(job_id)
        job_root = self._require_job_root(safe_job_id)
        report_path = job_root / "final_report.json"
        if report_path.exists():
            return self._job_payload(safe_job_id, report=self._read_report(safe_job_id))
        return self._job_payload(safe_job_id, report=None)

    def get_final_report(self, job_id: str) -> dict[str, JsonValue]:
        """Return ``final_report.json`` for one job."""

        safe_job_id = self._validate_job_id(job_id)
        self._require_job_root(safe_job_id)
        return self._read_report(safe_job_id)

    def get_contextforge_status(self, job_id: str) -> dict[str, JsonValue]:
        """Return refs, hashes, and IDs for v2 ContextForge artifacts."""

        safe_job_id = self._validate_job_id(job_id)
        job_root = self._require_job_root(safe_job_id)
        workspace = JobWorkspace(root=job_root, job_id=safe_job_id)
        runtime_result = self._read_optional_json_ref(workspace, GOAL_RUNTIME_RESULT_REF)
        graph_state = self._read_optional_json_ref(workspace, GOAL_RUNTIME_STATE_REF)
        contextforge_verification_read = self._read_optional_json_ref_status(
            workspace,
            CONTEXTFORGE_VERIFICATION_RESULT_REF,
        )
        contextforge_verification = (
            contextforge_verification_read.payload if contextforge_verification_read.valid else None
        )
        if contextforge_verification is not None:
            verification_status = _json_str(contextforge_verification.get("status")) or "invalid"
            verification_result_id = _json_str(contextforge_verification.get("verification_result_id"))
            verification_passed = contextforge_verification.get("passed") is True and verification_status == "passed"
        elif contextforge_verification_read.exists:
            verification_status = "invalid"
            verification_result_id = None
            verification_passed = False
        else:
            verification_status = _nested_json_str(runtime_result, ("status", "verification"))
            verification_result_id = _nested_json_str(runtime_result, ("ids", "verification_result_id"))
            verification_passed = verification_status == "passed"
        contextforge_verification_ref_status = self._artifact_ref_status(
            workspace,
            CONTEXTFORGE_VERIFICATION_RESULT_REF,
        )
        if contextforge_verification_read.exists:
            contextforge_verification_ref_status["valid_json"] = contextforge_verification_read.valid
            if contextforge_verification_read.error_code:
                contextforge_verification_ref_status["error_code"] = contextforge_verification_read.error_code
        final_report = self._try_read_report(safe_job_id)
        registry_entry = self._approved_registry_entry_for_report(safe_job_id, final_report) if final_report else None

        payload = {
            "schema_version": "skillfoundry.api.contextforge_status.v1",
            "job_id": safe_job_id,
            "refs": {
                "goal_contract": self._artifact_ref_status(workspace, GOAL_CONTRACT_REF),
                "build_node_contract": self._artifact_ref_status(workspace, BUILD_NODE_CONTRACT_REF),
                "verification_gate": self._artifact_ref_status(workspace, VERIFICATION_GATE_REF),
                "goal_runtime_result": self._artifact_ref_status(workspace, GOAL_RUNTIME_RESULT_REF),
                "goal_runtime_state": self._artifact_ref_status(workspace, GOAL_RUNTIME_STATE_REF),
                "goal_runtime_ledger": self._artifact_ref_status(workspace, GOAL_RUNTIME_LEDGER_REF),
                "contextforge_verification_result": contextforge_verification_ref_status,
                "frontdesk_v2_goal_contract": self._artifact_ref_status(workspace, FRONTDESK_V2_GOAL_CONTRACT_REF),
                "frontdesk_v2_governance_report": self._artifact_ref_status(
                    workspace,
                    FRONTDESK_V2_GOVERNANCE_REPORT_REF,
                ),
                "frontdesk_v2_manifest": self._artifact_ref_status(workspace, FRONTDESK_V2_MANIFEST_REF),
            },
            "ids": _json_mapping(runtime_result.get("ids")) if runtime_result else {},
            "status": {
                "runtime": _json_mapping(runtime_result.get("status")) if runtime_result else {},
                "graph": _json_mapping(graph_state.get("contextforge")) if graph_state else {},
                "verification": {
                    "status": verification_status,
                    "passed": verification_passed,
                    "verification_result_id": verification_result_id,
                },
                "registry": {
                    "approved": registry_entry is not None,
                    "skill_id": registry_entry.skill_id if registry_entry is not None else None,
                    "version": registry_entry.version if registry_entry is not None else None,
                },
            },
            "cache": {
                "cache_plan_id": _nested_json_str(runtime_result, ("ids", "cache_plan_id")),
                "cache_telemetry_status": "unavailable",
                "raw_prompt_included": False,
            },
            "frontdesk_v2": {
                "governance": self._frontdesk_v2_governance_summary(workspace),
            },
            "raw_context_included": False,
        }
        return ensure_json_compatible(payload)  # type: ignore[return-value]

    def query_registry(
        self,
        *,
        status: str | None = APPROVAL_APPROVED,
        include_quarantined: bool = False,
    ) -> dict[str, JsonValue]:
        """Return registry entries, defaulting to approved and non-quarantined."""

        entries = LocalSkillRegistry(self.registry_path).list(
            status=status,
            include_quarantined=include_quarantined,
        )
        return ensure_json_compatible(
            {
                "schema_version": API_VERSION,
                "registry_path": self._relative_to_runs_root(self.registry_path),
                "status": status if status is not None else "all",
                "include_quarantined": include_quarantined,
                "entries": [entry.to_dict() for entry in entries],
                "count": len(entries),
            }
        )  # type: ignore[return-value]

    def download_approved_package(self, job_id: str) -> tuple[bytes, str]:
        """Return a zip archive for a registered, approved, non-quarantined job."""

        safe_job_id = self._validate_job_id(job_id)
        report = self._read_report(safe_job_id)
        entry = self._approved_registry_entry_for_report(safe_job_id, report)
        if entry is None:
            raise APIError(403, "package_not_approved", "job does not have an approved registered package")

        job_root = self._require_job_root(safe_job_id)
        package_dir = self._package_dir(job_root)
        if not (package_dir / "SKILL.md").is_file():
            raise APIError(404, "package_missing", "approved package is missing package/SKILL.md")

        archive = BytesIO()
        file_count = 0
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
            for path in sorted(package_dir.rglob("*")):
                if path.is_symlink():
                    raise APIError(403, "unsafe_package_path", "package contains a symlink")
                if not path.is_file():
                    continue
                assert_under_root(package_dir, path)
                relative = path.relative_to(job_root.resolve(strict=True)).as_posix()
                validate_relative_path(relative)
                if not relative.startswith("package/"):
                    raise APIError(403, "unsafe_package_path", f"package archive path escaped package/: {relative}")
                handle.write(path, relative)
                file_count += 1
        if file_count == 0:
            raise APIError(404, "package_missing", "approved package contains no files")
        return archive.getvalue(), f"{safe_job_id}-package.zip"

    def render_index_html(self) -> str:
        """Render a quiet internal HTML page for jobs and registry entries."""

        jobs = [self._job_summary(path.name) for path in self._job_dirs()]
        frontdesk_jobs = [self._frontdesk_job_summary(path.name) for path in self._frontdesk_job_dirs()]
        registry_entries = self.query_registry()["entries"]
        return "\n".join(
            [
                "<!doctype html>",
                '<html lang="en">',
                "<head>",
                '  <meta charset="utf-8">',
                '  <meta name="viewport" content="width=device-width, initial-scale=1">',
                "  <title>SkillFoundry</title>",
                "  <style>",
                "    :root { color-scheme: light; font-family: system-ui, sans-serif; color: #172026; background: #f6f7f8; }",
                "    body { margin: 0; }",
                "    header { background: #172026; color: white; padding: 16px 24px; }",
                "    main { max-width: 1120px; margin: 0 auto; padding: 24px; }",
                "    section { margin-block: 24px; }",
                "    h1 { font-size: 22px; margin: 0; font-weight: 650; letter-spacing: 0; }",
                "    h2 { font-size: 18px; margin: 0 0 12px; font-weight: 650; letter-spacing: 0; }",
                "    h3 { font-size: 15px; margin: 0 0 8px; font-weight: 650; letter-spacing: 0; }",
                "    form { display: grid; gap: 10px; max-width: 760px; }",
                "    label { display: grid; gap: 4px; font-size: 13px; color: #43515a; }",
                "    input, textarea, select { font: inherit; border: 1px solid #c7ced3; border-radius: 6px; padding: 8px 10px; background: white; color: #172026; }",
                "    textarea { min-height: 150px; resize: vertical; }",
                "    button { width: fit-content; border: 1px solid #172026; border-radius: 6px; padding: 8px 12px; background: #172026; color: white; font: inherit; cursor: pointer; }",
                "    button[disabled] { opacity: .65; cursor: wait; }",
                "    table { width: 100%; border-collapse: collapse; background: white; }",
                "    th, td { border-bottom: 1px solid #dbe0e3; padding: 9px 10px; text-align: left; vertical-align: top; font-size: 14px; }",
                "    th { color: #43515a; font-weight: 650; background: #eef1f3; }",
                "    a { color: #075985; text-decoration: none; }",
                "    a:hover { text-decoration: underline; }",
                "    .muted { color: #667780; }",
                "    .links { display: flex; gap: 12px; flex-wrap: wrap; }",
                "    .panel { background: white; border: 1px solid #dbe0e3; border-radius: 8px; padding: 16px; }",
                "    .grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.8fr); gap: 18px; align-items: start; }",
                "    .status { display: inline-flex; width: fit-content; border-radius: 999px; padding: 4px 9px; background: #e8f1f8; color: #075985; font-size: 13px; font-weight: 650; }",
                "    .soft { background: #eef1f3; color: #43515a; }",
                "    .danger { background: #fdecec; color: #991b1b; }",
                "    .success { background: #e9f7ef; color: #166534; }",
                "    .stack { display: grid; gap: 12px; }",
                "    .small { font-size: 13px; }",
                "    @media (max-width: 760px) { main { padding: 14px; } .grid { grid-template-columns: 1fr; } }",
                "  </style>",
                "</head>",
                "<body>",
                "  <header><h1>SkillFoundry Codex Skill 工厂</h1></header>",
                "  <main>",
                '    <section class="grid">',
                '      <div class="panel stack">',
                "        <h2>描述你想要的 Skill</h2>",
                '        <form method="post" action="/frontdesk/jobs">',
                '          <label>需求 <textarea name="message" required placeholder="例如：我想要一个 Codex Skill，帮助研发团队根据 pytest 失败日志定位问题，并给出修复建议。"></textarea></label>',
                '          <button type="submit">开始对话</button>',
                '          <div class="small muted" data-submit-status></div>',
                "        </form>",
                "      </div>",
                '      <div class="panel stack">',
                "        <h2>当前会话</h2>",
                self._frontdesk_table_html(frontdesk_jobs),
                "      </div>",
                "    </section>",
                '    <section class="panel">',
                "      <h2>已交付资产</h2>",
                self._registry_table_html(registry_entries),
                "    </section>",
                '    <section class="panel">',
                "      <details>",
                "      <summary>内部调试</summary>",
                "      <h2>离线工厂</h2>",
                '      <form method="post" action="/jobs">',
                '        <label>Job ID <input name="job_id" autocomplete="off"></label>',
                '        <label>Worker Mode <select name="worker_mode">'
                + "".join(
                    f'<option value="{escape(mode.value)}">{escape(mode.value)}</option>'
                    for mode in OfflineWorkerMode
                )
                + "</select></label>",
                '        <label>Attempt Limit <input name="attempt_limit" inputmode="numeric" value="2"></label>',
                '        <label>Requirement <textarea name="requirement" required></textarea></label>',
                "        <button type=\"submit\">运行离线闭环</button>",
                '          <div class="small muted" data-submit-status></div>',
                "        </form>",
                "      <h2>离线 Job</h2>",
                self._jobs_table_html(jobs),
                "      </details>",
                "    </section>",
                "  </main>",
                self._submit_feedback_script(),
                "</body>",
                "</html>",
            ]
        )

    def render_frontdesk_job_html(self, job_id: str) -> str:
        """Render one user-facing Front Desk conversation page."""

        payload = self.get_frontdesk_job(job_id)
        state = payload.get("state")
        state_map = state if isinstance(state, Mapping) else {}
        job_root = self._require_job_root(job_id)
        workspace = JobWorkspace(root=job_root, job_id=job_id)
        frontdesk = FrontDeskWorkspace(workspace)
        turns = read_conversation_turns(frontdesk)
        elicitation = payload.get("latest_elicitation_report")
        elicitation_map = elicitation if isinstance(elicitation, Mapping) else {}
        questions = payload.get("next_questions")
        question_list = questions if isinstance(questions, list) else []
        solution_plan = payload.get("solution_plan")
        solution_plan_map = solution_plan if isinstance(solution_plan, Mapping) else {}
        readiness = str(state_map.get("readiness") or "new_conversation")
        next_action = str(state_map.get("next_action") or payload.get("status") or "elicit")
        return "\n".join(
            [
                "<!doctype html>",
                '<html lang="zh-CN">',
                "<head>",
                '  <meta charset="utf-8">',
                '  <meta name="viewport" content="width=device-width, initial-scale=1">',
                "  <title>SkillFoundry 需求澄清</title>",
                "  <style>",
                "    :root { color-scheme: light; font-family: system-ui, sans-serif; color: #172026; background: #f6f7f8; }",
                "    body { margin: 0; }",
                "    header { background: #172026; color: white; padding: 16px 24px; }",
                "    main { max-width: 1160px; margin: 0 auto; padding: 24px; display: grid; gap: 18px; }",
                "    h1 { font-size: 22px; margin: 0; font-weight: 650; letter-spacing: 0; }",
                "    h2 { font-size: 17px; margin: 0 0 10px; font-weight: 650; letter-spacing: 0; }",
                "    h3 { font-size: 14px; margin: 0 0 8px; font-weight: 650; letter-spacing: 0; }",
                "    a { color: #075985; text-decoration: none; } a:hover { text-decoration: underline; }",
                "    .grid { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(260px, 0.55fr); gap: 18px; align-items: start; }",
                "    .panel { background: white; border: 1px solid #dbe0e3; border-radius: 8px; padding: 16px; }",
                "    .stack { display: grid; gap: 12px; }",
                "    .conversation { display: grid; gap: 10px; }",
                "    .bubble { max-width: 84%; border: 1px solid #dbe0e3; border-radius: 8px; padding: 10px 12px; background: #fbfcfd; line-height: 1.55; overflow-wrap: anywhere; }",
                "    .bubble.user { justify-self: end; background: #e8f1f8; border-color: #cfe0ed; }",
                "    .bubble.assistant, .bubble.system, .bubble.tool { justify-self: start; }",
                "    .question { justify-self: start; max-width: 92%; border: 1px solid #d5e3ed; border-left: 3px solid #075985; border-radius: 8px; padding: 12px 14px; background: #f4f8fb; display: grid; gap: 10px; }",
                "    .question-title { font-size: 16px; line-height: 1.55; font-weight: 650; overflow-wrap: anywhere; }",
                "    .question-reason { line-height: 1.5; }",
                "    .option-list { display: grid; gap: 8px; margin-top: 2px; }",
                "    .option-item { width: 100%; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px; align-items: start; text-align: left; padding: 8px 10px; border: 1px solid #d5e3ed; border-radius: 6px; background: #fff; color: #172026; line-height: 1.5; overflow-wrap: anywhere; cursor: pointer; }",
                "    .option-item:hover { border-color: #075985; background: #f8fbfd; text-decoration: none; }",
                "    .option-key { font-weight: 650; color: #075985; }",
                "    .muted { color: #667780; }",
                "    .small { font-size: 13px; }",
                "    .status { display: inline-flex; width: fit-content; border-radius: 999px; padding: 4px 9px; background: #e8f1f8; color: #075985; font-size: 13px; font-weight: 650; }",
                "    .success { background: #e9f7ef; color: #166534; }",
                "    .danger { background: #fdecec; color: #991b1b; }",
                "    label { display: grid; gap: 6px; font-size: 13px; color: #43515a; }",
                "    textarea { box-sizing: border-box; width: 100%; min-height: 78px; max-height: 220px; resize: vertical; font: inherit; border: 1px solid #c7ced3; border-radius: 8px; padding: 10px 12px; line-height: 1.5; }",
                "    textarea:focus { outline: 2px solid #b9d7ea; border-color: #075985; }",
                "    form { display: grid; gap: 10px; }",
                "    .answer-form { border-top: 1px solid #eef1f3; padding-top: 12px; }",
                "    button { width: fit-content; border: 1px solid #172026; border-radius: 6px; padding: 8px 12px; background: #172026; color: white; font: inherit; cursor: pointer; }",
                "    button[disabled] { opacity: .65; cursor: wait; }",
                "    dl { display: grid; grid-template-columns: 120px minmax(0, 1fr); gap: 8px 12px; margin: 0; }",
                "    dt { color: #667780; } dd { margin: 0; overflow-wrap: anywhere; }",
                "    ul { margin: 0; padding-left: 20px; }",
                "    summary { cursor: pointer; color: #43515a; font-weight: 650; }",
                "    @media (max-width: 760px) { main { padding: 14px; } .grid { grid-template-columns: 1fr; } dl { grid-template-columns: 1fr; } }",
                "  </style>",
                "</head>",
                "<body>",
                "  <header><h1>SkillFoundry 需求澄清</h1></header>",
                "  <main>",
                '    <div><a href="/">返回首页</a></div>',
                '    <section class="grid">',
                '      <div class="panel stack">',
                "        <h2>对话</h2>",
                self._conversation_html(turns, workspace=workspace, state=state_map),
                self._questions_html(question_list, readiness=readiness, next_action=next_action),
                self._solution_plan_review_html(job_id, solution_plan_map, readiness=readiness),
                self._frontdesk_answer_form_html(job_id, readiness=readiness, next_action=next_action),
                "      </div>",
                '      <aside class="panel stack">',
                "        <h2>交付状态</h2>",
                self._frontdesk_status_html(readiness, next_action),
                self._frontdesk_understanding_html(elicitation_map),
                self._frontdesk_artifact_refs_html(state_map),
                "      </aside>",
                "    </section>",
                "  </main>",
                self._submit_feedback_script(),
                "</body>",
                "</html>",
            ]
        )

    def render_error_html(self, *, title: str, message: str, status: int) -> str:
        return "\n".join(
            [
                "<!doctype html>",
                '<html lang="zh-CN">',
                "<head>",
                '  <meta charset="utf-8">',
                '  <meta name="viewport" content="width=device-width, initial-scale=1">',
                f"  <title>{escape(title)}</title>",
                "  <style>body{font-family:system-ui,sans-serif;background:#f6f7f8;color:#172026;margin:0}main{max-width:760px;margin:0 auto;padding:24px}.panel{background:white;border:1px solid #dbe0e3;border-radius:8px;padding:16px}a{color:#075985}</style>",
                "</head>",
                "<body><main>",
                f'<section class="panel"><h1>{escape(title)}</h1><p>{escape(message)}</p><p><a href="/">返回首页</a></p><p>HTTP {status}</p></section>',
                "</main></body></html>",
            ]
        )

    def handle(
        self,
        method: str,
        path: str,
        *,
        body: bytes | str | Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> APIHTTPResult:
        """Handle a minimal HTTP-shaped request without requiring a live server."""

        try:
            parsed = urlparse(path)
            route = [unquote(part) for part in parsed.path.split("/") if part]
            query = parse_qs(parsed.query, keep_blank_values=False)
            method = method.upper()

            if method == "GET" and route == []:
                html = self.render_index_html().encode("utf-8")
                return APIHTTPResult(200, "text/html; charset=utf-8", html)

            if method == "POST" and route == ["jobs"]:
                content_type = _header(headers, "content-type")
                payload = self._parse_body(body, content_type=content_type)
                created = self.create_job(payload)
                if content_type.startswith("application/x-www-form-urlencoded"):
                    return APIHTTPResult(
                        303,
                        "text/plain; charset=utf-8",
                        b"",
                        headers=(("Location", f"/jobs/{created['job_id']}"),),
                    )
                return self._json_response(created, status=201)

            if method == "GET" and route == ["jobs"]:
                return self._json_response(self.list_jobs())

            if method == "GET" and len(route) == 2 and route[0] == "jobs":
                return self._json_response(self.get_job(route[1]))

            if method == "GET" and len(route) == 3 and route[0] == "jobs" and route[2] == "report":
                return self._json_response(self.get_final_report(route[1]))

            if method == "GET" and len(route) == 3 and route[0] == "jobs" and route[2] == "contextforge":
                return self._json_response(self.get_contextforge_status(route[1]))

            if method == "GET" and len(route) == 3 and route[0] == "jobs" and route[2] == "package.zip":
                data, filename = self.download_approved_package(route[1])
                return APIHTTPResult(
                    200,
                    "application/zip",
                    data,
                    headers=(("Content-Disposition", f'attachment; filename="{filename}"'),),
                )

            if method == "GET" and route == ["registry"]:
                status = query.get("status", [APPROVAL_APPROVED])[0]
                if status == "all":
                    status = "all"
                include_quarantined = _query_bool(query.get("include_quarantined", ["false"])[0])
                return self._json_response(
                    self.query_registry(status=status, include_quarantined=include_quarantined)
                )

            if method == "POST" and route == ["frontdesk", "jobs"]:
                content_type = _header(headers, "content-type")
                payload = self._parse_body(body, content_type=content_type)
                created = self.create_frontdesk_job(payload)
                if content_type.startswith("application/x-www-form-urlencoded"):
                    return APIHTTPResult(
                        303,
                        "text/plain; charset=utf-8",
                        b"",
                        headers=(("Location", f"/frontdesk/jobs/{created['job_id']}"),),
                    )
                return self._json_response(created, status=201)

            if method == "GET" and len(route) == 3 and route[:2] == ["frontdesk", "jobs"]:
                if _wants_html(headers):
                    html = self.render_frontdesk_job_html(route[2]).encode("utf-8")
                    return APIHTTPResult(200, "text/html; charset=utf-8", html)
                return self._json_response(self.get_frontdesk_job(route[2]))

            if method == "GET" and len(route) == 4 and route[:2] == ["frontdesk", "jobs"] and route[3] == "core-need":
                safe_job_id = self._validate_job_id(route[2])
                job_root = self._require_job_root(safe_job_id)
                workspace = JobWorkspace(root=job_root, job_id=safe_job_id)
                core_need = self._read_optional_json_ref(workspace, FRONTDESK_CORE_NEED_BRIEF_REF)
                if core_need is None:
                    raise APIError(404, "core_need_not_found", "core need brief is not available")
                return self._json_response(core_need)

            if method == "GET" and len(route) == 4 and route[:2] == ["frontdesk", "jobs"] and route[3] == "solution-plan":
                safe_job_id = self._validate_job_id(route[2])
                job_root = self._require_job_root(safe_job_id)
                workspace = JobWorkspace(root=job_root, job_id=safe_job_id)
                solution_plan = self._read_optional_json_ref(workspace, FRONTDESK_SOLUTION_PLAN_REF)
                if solution_plan is None:
                    raise APIError(404, "solution_plan_not_found", "solution plan is not available")
                return self._json_response(solution_plan)

            if method == "POST" and len(route) == 4 and route[:2] == ["frontdesk", "jobs"] and route[3] == "plan-review":
                content_type = _header(headers, "content-type")
                payload = self._parse_body(body, content_type=content_type)
                result = self.review_frontdesk_plan(route[2], payload)
                if content_type.startswith("application/x-www-form-urlencoded"):
                    return APIHTTPResult(
                        303,
                        "text/plain; charset=utf-8",
                        b"",
                        headers=(("Location", f"/frontdesk/jobs/{result['job_id']}"),),
                    )
                return self._json_response(result)

            if method == "POST" and len(route) == 4 and route[:2] == ["frontdesk", "jobs"] and route[3] == "messages":
                content_type = _header(headers, "content-type")
                payload = self._parse_body(body, content_type=content_type)
                result = self.append_frontdesk_message(route[2], payload)
                if content_type.startswith("application/x-www-form-urlencoded"):
                    return APIHTTPResult(
                        303,
                        "text/plain; charset=utf-8",
                        b"",
                        headers=(("Location", f"/frontdesk/jobs/{result['job_id']}"),),
                    )
                return self._json_response(result)

            if method == "POST" and len(route) == 4 and route[:2] == ["frontdesk", "jobs"] and route[3] == "retry":
                content_type = _header(headers, "content-type")
                result = self.retry_frontdesk_job(route[2])
                if content_type.startswith("application/x-www-form-urlencoded"):
                    return APIHTTPResult(
                        303,
                        "text/plain; charset=utf-8",
                        b"",
                        headers=(("Location", f"/frontdesk/jobs/{result['job_id']}"),),
                    )
                return self._json_response(result)

            if any(part in ("..", ".") or "/" in part or "\\" in part for part in route):
                raise APIError(400, "unsafe_path", "request path contains an unsafe segment")
            raise APIError(404, "not_found", "route not found")
        except APIError as exc:
            if _wants_html(headers):
                html = self.render_error_html(title=exc.code, message=exc.message, status=exc.status).encode("utf-8")
                return APIHTTPResult(exc.status, "text/html; charset=utf-8", html)
            return self._json_response(exc.to_dict(), status=exc.status)

    def _resolve_registry_path(self, registry_path: str | Path | None) -> Path:
        path = self.runs_root / "registry.json" if registry_path is None else Path(registry_path).expanduser()
        if not path.is_absolute():
            path = self.runs_root / path
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(self._runs_root_resolved)
        except ValueError as exc:
            raise APIError(400, "unsafe_registry_path", "registry_path must be under runs_root") from exc
        return resolved

    def _validate_job_id(self, job_id: str) -> str:
        if not JOB_ID_RE.fullmatch(job_id):
            raise APIError(400, "invalid_job_id", "job_id must be a non-empty safe path segment")
        try:
            safe = validate_relative_path(job_id)
        except PathSecurityError as exc:
            raise APIError(400, "invalid_job_id", str(exc)) from exc
        if len(safe.parts) != 1:
            raise APIError(400, "invalid_job_id", "job_id must be one path segment")
        return safe.as_posix()

    def _job_root(self, job_id: str) -> Path:
        try:
            return resolve_under_root(self._runs_root_resolved, job_id, must_exist=False)
        except PathSecurityError as exc:
            raise APIError(400, "invalid_job_id", str(exc)) from exc

    def _require_job_root(self, job_id: str) -> Path:
        try:
            root = resolve_under_root(self._runs_root_resolved, job_id, must_exist=True)
        except PathSecurityError as exc:
            raise APIError(404, "job_not_found", f"job not found: {job_id}") from exc
        if not root.is_dir():
            raise APIError(404, "job_not_found", f"job not found: {job_id}")
        return root

    def _package_dir(self, job_root: Path) -> Path:
        try:
            package_dir = resolve_under_root(job_root, "package", must_exist=True)
        except PathSecurityError as exc:
            raise APIError(404, "package_missing", str(exc)) from exc
        if not package_dir.is_dir():
            raise APIError(404, "package_missing", "package path is not a directory")
        return package_dir

    def _write_requirement(self, job_id: str, requirement: str) -> Path:
        requirement_dir = self._runs_root_resolved / ".api_requirements"
        requirement_dir.mkdir(parents=True, exist_ok=True)
        assert_under_root(self._runs_root_resolved, requirement_dir)
        path = requirement_dir / f"{job_id}.md"
        assert_under_root(self._runs_root_resolved, path)
        path.write_text(requirement.strip() + "\n", encoding="utf-8")
        return path

    def _read_report(self, job_id: str) -> dict[str, JsonValue]:
        job_root = self._require_job_root(job_id)
        report_path = job_root / "final_report.json"
        if not report_path.exists():
            raise APIError(404, "report_not_found", f"final report not found for job: {job_id}")
        try:
            return read_final_report(job_root)
        except Exception as exc:
            raise APIError(500, "invalid_report", f"final report is invalid: {exc}") from exc

    def _try_read_report(self, job_id: str) -> dict[str, JsonValue] | None:
        try:
            return self._read_report(job_id)
        except APIError:
            return None

    def _run_frontdesk_round(
        self,
        frontdesk: FrontDeskWorkspace,
        *,
        state: FrontDeskState | None = None,
    ) -> FrontDeskLoopResult:
        if state is not None and (state.readiness == "plan_approved" or state.next_action == "freeze_approved_plan"):
            round_index = _frontdesk_report_index(state.latest_elicitation_report_ref) or max(1, state.clarification_round)
            elicitor_client = None
        else:
            round_index = (state.clarification_round if state is not None else 0) + 1
            elicitor_client = self._frontdesk_client("requirements_elicitor", frontdesk.job_id, round_index)
        auditor_client = self._frontdesk_client("spec_auditor", frontdesk.job_id, round_index)
        result = run_frontdesk_round(
            frontdesk,
            state=state,
            elicitor_client=elicitor_client,
            auditor_client=auditor_client,
            elicitor_model_params=self._frontdesk_model_params(),
            auditor_model_params=self._frontdesk_model_params(),
            elicitor_provider="openai" if self.frontdesk_client_factory is None else "fake",
            auditor_provider="openai" if self.frontdesk_client_factory is None else "fake",
            elicitor_model=self.frontdesk_model,
            auditor_model=self.frontdesk_model,
        )
        write_frontdesk_artifact(frontdesk, "state.json", result.state.to_dict())
        return result

    def _frontdesk_client(self, role: str, job_id: str, round_index: int) -> Any:
        if self.frontdesk_client_factory is not None:
            return self.frontdesk_client_factory(role, job_id, round_index)
        try:
            return OpenAIChatCompletionsClient.from_env()
        except Exception as exc:
            raise APIError(503, "frontdesk_provider_unavailable", str(exc)) from exc

    def _frontdesk_model_params(self) -> dict[str, JsonValue]:
        params: dict[str, JsonValue] = {
            "model": self.frontdesk_model,
            "temperature": float(os.environ.get("SKILLFOUNDRY_FRONTDESK_TEMPERATURE", "0")),
            "max_tokens": int(os.environ.get("SKILLFOUNDRY_FRONTDESK_MAX_TOKENS", "4096")),
        }
        return params

    def _ensure_frontdesk_retry_budget(self, frontdesk: FrontDeskWorkspace) -> None:
        budget_path = frontdesk.workspace.resolve_path(FRONTDESK_BUDGET_REF, must_exist=True)
        config = FrontDeskConfig.read_json_file(budget_path)
        default_calls = FrontDeskConfig().max_frontdesk_model_calls
        if config.max_frontdesk_model_calls >= default_calls:
            return
        config.max_frontdesk_model_calls = default_calls
        write_frontdesk_artifact(frontdesk, "budget.json", config.to_dict())

    def _read_frontdesk_state(self, frontdesk: FrontDeskWorkspace) -> FrontDeskState | None:
        state_path = frontdesk.workspace.resolve_path(FRONTDESK_STATE_REF)
        if not state_path.exists():
            return None
        try:
            return FrontDeskState.from_json(state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise APIError(500, "invalid_frontdesk_state", f"frontdesk state is invalid: {exc}") from exc

    def _frontdesk_payload(
        self,
        job_id: str,
        *,
        result: FrontDeskLoopResult | None = None,
        state: FrontDeskState | None = None,
    ) -> dict[str, JsonValue]:
        job_root = self._require_job_root(job_id)
        workspace = JobWorkspace(root=job_root, job_id=job_id)
        frontdesk = FrontDeskWorkspace(workspace)
        if state is None:
            state = result.state if result is not None else self._read_frontdesk_state(frontdesk)
        turns = read_conversation_turns(frontdesk)
        latest_elicitation = self._read_optional_json_ref(workspace, state.latest_elicitation_report_ref if state else None)
        latest_audit = self._read_optional_json_ref(workspace, state.latest_audit_report_ref if state else None)
        latest_failure = self._read_optional_json_ref(workspace, result.failure_ref if result is not None else None)
        core_need_brief = self._read_optional_json_ref(workspace, state.core_need_brief_ref if state else None)
        solution_plan = self._read_optional_json_ref(workspace, state.solution_plan_ref if state else None)
        latest_plan_review = self._read_optional_json_ref(workspace, state.latest_plan_review_ref if state else None)
        questions = _active_frontdesk_questions(state, latest_elicitation, turn_count=len(turns))
        review_actions = _frontdesk_review_actions(state)
        payload: dict[str, Any] = {
            "schema_version": FRONTDESK_API_VERSION,
            "job_id": job_id,
            "status": result.status if result is not None else (state.next_action if state else "new_conversation"),
            "phase": state.frontdesk_phase if state is not None else "core_need_discovery",
            "state": state.to_dict() if state is not None else None,
            "conversation_ref": FRONTDESK_CONVERSATION_REF,
            "turn_count": len(turns),
            "next_questions": questions,
            "core_need_brief": core_need_brief,
            "solution_plan": solution_plan,
            "solution_plan_markdown_ref": state.solution_plan_markdown_ref if state is not None else None,
            "latest_plan_review": latest_plan_review,
            "review_actions": review_actions,
            "latest_elicitation_report": latest_elicitation,
            "latest_audit_report": latest_audit,
            "latest_failure": latest_failure,
            "result": result.to_dict() if result is not None else None,
            "links": {
                "self": f"/frontdesk/jobs/{job_id}",
                "messages": f"/frontdesk/jobs/{job_id}/messages",
                "core_need": f"/frontdesk/jobs/{job_id}/core-need",
                "solution_plan": f"/frontdesk/jobs/{job_id}/solution-plan",
                "plan_review": f"/frontdesk/jobs/{job_id}/plan-review",
            },
        }
        return ensure_json_compatible(payload)  # type: ignore[return-value]

    def _read_optional_json_ref(self, workspace: Any, ref: str | None) -> dict[str, JsonValue] | None:
        result = self._read_optional_json_ref_status(workspace, ref)
        return result.payload if result.valid else None

    def _read_optional_json_ref_status(self, workspace: Any, ref: str | None) -> OptionalJsonRefRead:
        if not ref:
            return OptionalJsonRefRead(exists=False, valid=False)
        try:
            path = self._resolve_optional_ref_path(workspace, ref)
        except Exception:
            return OptionalJsonRefRead(exists=False, valid=False, error_code="invalid_ref")
        if not path.exists():
            return OptionalJsonRefRead(exists=False, valid=False)
        if not path.is_file():
            return OptionalJsonRefRead(exists=True, valid=False, error_code="not_file")
        if path.suffix.lower() not in {".json", ".jsonl"}:
            return OptionalJsonRefRead(exists=True, valid=False, error_code="unsupported_json_ref")
        if path.suffix.lower() == ".jsonl":
            return OptionalJsonRefRead(exists=True, valid=False, error_code="jsonl_not_loaded")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return OptionalJsonRefRead(exists=True, valid=False, error_code="invalid_json")
        except UnicodeDecodeError:
            return OptionalJsonRefRead(exists=True, valid=False, error_code="invalid_encoding")
        except OSError:
            return OptionalJsonRefRead(exists=True, valid=False, error_code="unreadable")
        if not isinstance(payload, dict):
            return OptionalJsonRefRead(exists=True, valid=False, error_code="not_json_object")
        try:
            compatible = ensure_json_compatible(payload)
        except Exception:
            return OptionalJsonRefRead(exists=True, valid=False, error_code="invalid_json_schema")
        return OptionalJsonRefRead(exists=True, valid=True, payload=compatible)  # type: ignore[arg-type]

    def _resolve_optional_ref_path(self, workspace: Any, ref: str) -> Path:
        if isinstance(workspace, JobWorkspace):
            root = Path(workspace.root).resolve(strict=True)
            safe_relative = validate_relative_path(ref)
            target = root.joinpath(*safe_relative.parts)
            current = root
            for part in safe_relative.parts:
                current = current / part
                if current.is_symlink():
                    raise PathSecurityError(f"symlink components are not allowed: {current}")
                if current.exists():
                    assert_under_root(root, current)
                else:
                    break
            return assert_under_root(root, target)
        return workspace.resolve_path(ref)

    def _artifact_ref_status(self, workspace: JobWorkspace, ref: str) -> dict[str, JsonValue]:
        try:
            path = self._resolve_optional_ref_path(workspace, ref)
        except Exception:
            return {"ref": ref, "exists": False, "error_code": "invalid_ref"}
        if not path.exists():
            return {"ref": ref, "exists": False}
        kind = "file" if path.is_file() else "directory" if path.is_dir() else "other"
        payload: dict[str, JsonValue] = {
            "ref": ref,
            "exists": True,
            "sha256": None,
            "kind": kind,
            "size_bytes": None,
        }
        if not path.is_file():
            payload["error_code"] = "not_file"
            return ensure_json_compatible(payload)  # type: ignore[return-value]
        try:
            payload["sha256"] = sha256_file(path)
            payload["size_bytes"] = path.stat().st_size
        except OSError:
            payload["error_code"] = "unreadable"
        return ensure_json_compatible(payload)  # type: ignore[return-value]

    def _frontdesk_v2_governance_summary(self, workspace: JobWorkspace) -> dict[str, JsonValue] | None:
        payload = self._read_optional_json_ref(workspace, FRONTDESK_V2_GOVERNANCE_REPORT_REF)
        if payload is None:
            return None
        return {
            "status": payload.get("status"),
            "blocking_reason_codes": [
                item.get("code")
                for item in payload.get("blocking_reasons", [])
                if isinstance(item, Mapping) and isinstance(item.get("code"), str)
            ],
            "provider_usage": payload.get("provider_usage") if isinstance(payload.get("provider_usage"), Mapping) else {},
        }

    def _frontdesk_job_dirs(self) -> list[Path]:
        candidates: list[Path] = []
        for path in sorted(self._runs_root_resolved.iterdir(), key=lambda item: item.name):
            if not path.is_dir() or path.is_symlink():
                continue
            if not JOB_ID_RE.fullmatch(path.name):
                continue
            if (path / FRONTDESK_CONVERSATION_REF).is_file():
                candidates.append(path)
        return candidates

    def _frontdesk_job_summary(self, job_id: str) -> dict[str, JsonValue]:
        try:
            job_root = self._require_job_root(job_id)
            workspace = JobWorkspace(root=job_root, job_id=job_id)
            frontdesk = FrontDeskWorkspace(workspace)
            state = self._read_frontdesk_state(frontdesk)
            turns = read_conversation_turns(frontdesk)
        except APIError:
            state = None
            turns = []
        latest = self._read_optional_json_ref(
            JobWorkspace(root=self._job_root(job_id), job_id=job_id),
            state.latest_elicitation_report_ref if state is not None else None,
        )
        current_understanding = latest.get("current_understanding") if isinstance(latest, Mapping) else None
        return ensure_json_compatible(
            {
                "job_id": job_id,
                "readiness": state.readiness if state is not None else "unknown",
                "next_action": state.next_action if state is not None else "unknown",
                "clarification_round": state.clarification_round if state is not None else 0,
                "turn_count": len(turns),
                "current_understanding": current_understanding if isinstance(current_understanding, str) else "",
                "links": {"self": f"/frontdesk/jobs/{job_id}"},
            }
        )  # type: ignore[return-value]

    def _job_payload(
        self,
        job_id: str,
        *,
        report: Mapping[str, Any] | None,
    ) -> dict[str, JsonValue]:
        approved_entry = self._approved_registry_entry_for_report(job_id, report) if report is not None else None
        final_status = str(report.get("final_status")) if report is not None and report.get("final_status") else None
        payload: dict[str, Any] = {
            "schema_version": API_VERSION,
            "job_id": job_id,
            "status": final_status or "workspace",
            "final_status": final_status,
            "route": report.get("route") if report is not None else None,
            "created_at": report.get("created_at") if report is not None else None,
            "verifier_passed": self._verifier_passed(report),
            "package_downloadable": approved_entry is not None,
            "links": self._links(job_id, package_downloadable=approved_entry is not None),
            "report": report,
        }
        if approved_entry is not None:
            payload["registry_entry"] = approved_entry.to_dict()
        return ensure_json_compatible(payload)  # type: ignore[return-value]

    def _job_summary(self, job_id: str) -> dict[str, JsonValue]:
        report: dict[str, JsonValue] | None = None
        final_status: str | None = None
        verifier_passed = False
        created_at: JsonValue = None
        try:
            report = self._read_report(job_id)
        except APIError:
            pass
        if report is not None:
            final_status = str(report.get("final_status")) if report.get("final_status") else None
            verifier_passed = self._verifier_passed(report)
            created_at = report.get("created_at")
        approved_entry = self._approved_registry_entry_for_report(job_id, report) if report is not None else None
        return ensure_json_compatible(
            {
                "job_id": job_id,
                "status": final_status or "workspace",
                "final_status": final_status,
                "created_at": created_at,
                "verifier_passed": verifier_passed,
                "package_downloadable": approved_entry is not None,
                "links": self._links(job_id, package_downloadable=approved_entry is not None),
            }
        )  # type: ignore[return-value]

    def _approved_registry_entry_for_report(
        self,
        job_id: str,
        report: Mapping[str, Any] | None,
    ) -> RegistryEntry | None:
        if report is None or report.get("final_status") != "registered":
            return None
        report_package_hash = report.get("package_hash")
        refs = report.get("refs")
        registry_ref = refs.get("registry_entry") if isinstance(refs, Mapping) else None
        expected_skill_id = registry_ref.get("skill_id") if isinstance(registry_ref, Mapping) else None
        expected_version = registry_ref.get("version") if isinstance(registry_ref, Mapping) else None

        try:
            entries = LocalSkillRegistry(self.registry_path).list(
                status=APPROVAL_APPROVED,
                include_quarantined=False,
            )
        except Exception:
            return None

        job_root = self._job_root(job_id)
        package_dir = job_root / "package"
        for entry in entries:
            if entry.build_job_id != job_id:
                continue
            if entry.approval_status != APPROVAL_APPROVED or entry.quarantine_status != QUARANTINE_NONE:
                continue
            if isinstance(expected_skill_id, str) and entry.skill_id != expected_skill_id:
                continue
            if isinstance(expected_version, str) and entry.version != expected_version:
                continue
            if isinstance(report_package_hash, str) and entry.package_hash != report_package_hash:
                continue
            try:
                verification = LocalSkillRegistry(self.registry_path).verify_entry(entry)
                entry_package_dir = Path(entry.package_path).resolve(strict=True)
                if entry_package_dir != package_dir.resolve(strict=True):
                    continue
                assert_under_root(self._runs_root_resolved, entry_package_dir)
            except Exception:
                continue
            if verification.valid:
                return entry
        return None

    def _links(self, job_id: str, *, package_downloadable: bool) -> dict[str, JsonValue]:
        links: dict[str, JsonValue] = {
            "self": f"/jobs/{job_id}",
            "report": f"/jobs/{job_id}/report",
        }
        if package_downloadable:
            links["package"] = f"/jobs/{job_id}/package.zip"
        return links

    def _job_dirs(self) -> list[Path]:
        candidates: list[Path] = []
        for path in sorted(self._runs_root_resolved.iterdir(), key=lambda item: item.name):
            if not path.is_dir() or path.is_symlink():
                continue
            if not JOB_ID_RE.fullmatch(path.name):
                continue
            if any((path / marker).exists() for marker in ("final_report.json", "artifact_manifest.json", "build_contract.yaml")):
                candidates.append(path)
        return candidates

    def _relative_to_runs_root(self, path: Path) -> str:
        return path.resolve(strict=False).relative_to(self._runs_root_resolved).as_posix()

    def _parse_body(
        self,
        body: bytes | str | Mapping[str, Any] | None,
        *,
        content_type: str,
    ) -> Mapping[str, Any]:
        if isinstance(body, Mapping):
            return body
        raw = b"" if body is None else body.encode("utf-8") if isinstance(body, str) else body
        if content_type.startswith("application/x-www-form-urlencoded"):
            parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=False)
            return {key: values[-1] for key, values in parsed.items() if values}
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise APIError(400, "invalid_json", f"request body is invalid JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise APIError(400, "invalid_json", "request body must be a JSON object")
        return payload

    def _json_response(self, payload: Mapping[str, Any], *, status: int = 200) -> APIHTTPResult:
        compatible = ensure_json_compatible(dict(payload))
        data = (
            json.dumps(compatible, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        ).encode("utf-8")
        return APIHTTPResult(status, "application/json; charset=utf-8", data)

    def _coerce_attempt_limit(self, value: Any) -> int:
        if isinstance(value, bool):
            raise APIError(400, "invalid_attempt_limit", "attempt_limit must be a positive integer")
        try:
            attempt_limit = int(value)
        except (TypeError, ValueError) as exc:
            raise APIError(400, "invalid_attempt_limit", "attempt_limit must be a positive integer") from exc
        if attempt_limit <= 0:
            raise APIError(400, "invalid_attempt_limit", "attempt_limit must be a positive integer")
        return attempt_limit

    def _generate_job_id(self) -> str:
        return f"job-{uuid4().hex[:12]}"

    @staticmethod
    def _verifier_passed(report: Mapping[str, Any] | None) -> bool:
        if report is None:
            return False
        refs = report.get("refs")
        verifier = refs.get("verifier_result") if isinstance(refs, Mapping) else None
        return bool(isinstance(verifier, Mapping) and verifier.get("passed") is True)

    def _jobs_table_html(self, jobs: list[dict[str, JsonValue]]) -> str:
        if not jobs:
            return '<p class="muted">No jobs.</p>'
        rows = []
        for job in jobs:
            job_id = str(job["job_id"])
            links = job.get("links")
            report_link = f"/jobs/{job_id}/report"
            package_link = None
            if isinstance(links, Mapping) and isinstance(links.get("package"), str):
                package_link = str(links["package"])
            action_links = [f'<a href="{escape(report_link)}">Report</a>']
            if package_link is not None:
                action_links.append(f'<a href="{escape(package_link)}">Download</a>')
            rows.append(
                "        <tr>"
                f'<td><a href="/jobs/{escape(job_id)}">{escape(job_id)}</a></td>'
                f"<td>{escape(str(job.get('status') or 'workspace'))}</td>"
                f"<td>{'passed' if job.get('verifier_passed') is True else 'not passed'}</td>"
                f'<td><span class="links">{"".join(action_links)}</span></td>'
                "</tr>"
            )
        return "\n".join(
            [
                "      <table>",
                "        <thead><tr><th>Job</th><th>Status</th><th>Verifier</th><th>Links</th></tr></thead>",
                "        <tbody>",
                *rows,
                "        </tbody>",
                "      </table>",
            ]
        )

    def _frontdesk_table_html(self, jobs: list[dict[str, JsonValue]]) -> str:
        if not jobs:
            return '<p class="muted">暂无会话。</p>'
        rows = []
        for job in jobs:
            job_id = str(job["job_id"])
            label, cls = _frontdesk_status_label(str(job.get("readiness") or ""), str(job.get("next_action") or ""))
            rows.append(
                "        <tr>"
                f'<td><a href="/frontdesk/jobs/{escape(job_id)}">打开</a></td>'
                f'<td><span class="status {escape(cls)}">{escape(label)}</span></td>'
                f"<td>{escape(str(job.get('clarification_round') or 0))}</td>"
                f"<td>{escape(_truncate(str(job.get('current_understanding') or ''), 90))}</td>"
                "</tr>"
            )
        return "\n".join(
            [
                "      <table>",
                "        <thead><tr><th>会话</th><th>状态</th><th>轮次</th><th>当前理解</th></tr></thead>",
                "        <tbody>",
                *rows,
                "        </tbody>",
                "      </table>",
            ]
        )

    def _conversation_html(
        self,
        turns: list[ConversationTurn],
        *,
        workspace: JobWorkspace | None = None,
        state: Mapping[str, Any] | None = None,
    ) -> str:
        if not turns:
            return '<p class="muted">暂无对话。</p>'
        rows = ['<div class="conversation">']
        for index, turn in enumerate(turns, start=1):
            role = "你" if turn.role == "user" else turn.role
            role_class = escape(turn.role if turn.role in {"user", "assistant", "system", "tool"} else "system")
            rows.append(
                f'<div class="bubble {role_class}">'
                f'<div class="small muted">{escape(role)}</div>'
                f"<div>{escape(turn.content)}</div>"
                "</div>"
            )
            if workspace is not None:
                rows.extend(
                    self._answered_frontdesk_question_html(
                        workspace,
                        report_index=index,
                        has_later_user_turn=index < len(turns),
                    )
                )
        rows.append("</div>")
        return "\n".join(rows)

    def _answered_frontdesk_question_html(
        self,
        workspace: JobWorkspace,
        *,
        report_index: int,
        has_later_user_turn: bool,
    ) -> list[str]:
        if not has_later_user_turn:
            return []
        report_ref = f"frontdesk/elicitation_report_{report_index:03d}.json"
        report = self._read_optional_json_ref(workspace, report_ref)
        questions = report.get("next_questions") if isinstance(report, Mapping) else None
        if not isinstance(questions, list) or not questions:
            return []
        rows: list[str] = []
        for question in questions:
            if not isinstance(question, Mapping):
                continue
            question_text, question_options = _frontdesk_question_parts(str(question.get("text") or ""), question.get("options"))
            rows.append(
                '<div class="bubble assistant">'
                '<div class="small muted">需求澄清 Agent</div>'
                f"<div>{escape(question_text)}</div>"
                + self._compact_question_options_html(question_options)
                + "</div>"
            )
        return rows

    def _compact_question_options_html(self, options: list[str]) -> str:
        if not options:
            return ""
        return "<ul>" + "".join(f"<li>{escape(option)}</li>" for option in options) + "</ul>"

    def _questions_html(self, questions: list[Any], *, readiness: str, next_action: str) -> str:
        if readiness == "frozen" or next_action == "route_to_build":
            return '<div class="bubble"><strong>需求已经冻结。</strong><div class="small muted">下一步可以进入 Skill 构建和验收。</div></div>'
        if next_action == "human_review":
            return '<div class="bubble"><strong>需要人工审核。</strong><div class="small muted">当前需求涉及风险、权限或不可自动判断的边界。</div></div>'
        if next_action == "reject":
            return '<div class="bubble"><strong>需求已拒绝。</strong><div class="small muted">当前需求不可安全或可行地交付。</div></div>'
        if next_action == "fail_closed":
            return '<div class="bubble"><strong>澄清失败。</strong><div class="small muted">模型输出或系统边界校验未通过。</div></div>'
        if not questions:
            return '<p class="muted">等待下一轮问题。</p>'
        rows = ['<div class="conversation"><h3>接下来先确认一件事</h3>']
        for question in questions:
            if not isinstance(question, Mapping):
                continue
            options = question.get("options")
            reason = str(question.get("reason") or "")
            reason_html = (
                f'<div class="small muted question-reason">{escape(reason)}</div>' if reason else ""
            )
            question_text, question_options = _frontdesk_question_parts(str(question.get("text") or ""), options)
            rows.append(
                '<div class="question">'
                f'<div class="question-title">{escape(question_text)}</div>'
                + self._question_options_html(question_options)
                + reason_html
                + "</div>"
            )
        rows.append("</div>")
        return "\n".join(rows)

    def _frontdesk_answer_form_html(self, job_id: str, *, readiness: str, next_action: str) -> str:
        if readiness in {"frozen", "human_review_required", "rejected"}:
            return ""
        if next_action == "elicit" or (readiness == "failed" and next_action == "fail_closed"):
            return "\n".join(
                [
                    f'<form class="answer-form" method="post" action="/frontdesk/jobs/{escape(job_id)}/retry">',
                    "  <button type=\"submit\">重试生成下一步</button>",
                    '  <div class="small muted" data-submit-status>当前回答已保留，重试不会新增一条用户回答。</div>',
                    "</form>",
                ]
            )
        if next_action != "ask_user":
            return ""
        return "\n".join(
            [
                f'<form class="answer-form" method="post" action="/frontdesk/jobs/{escape(job_id)}/messages">',
                '  <label>你的回答 <textarea name="message" required placeholder="可以直接点上面的选项，也可以用自己的话补充背景、偏好或约束。"></textarea></label>',
                "  <button type=\"submit\">继续对话</button>",
                '  <div class="small muted" data-submit-status></div>',
                "</form>",
            ]
        )

    def _solution_plan_review_html(self, job_id: str, solution_plan: Mapping[str, Any], *, readiness: str) -> str:
        if readiness not in {"awaiting_plan_review", "plan_revision_requested"} or not solution_plan:
            return ""
        summary = escape(str(solution_plan.get("summary") or ""))
        approach = escape(str(solution_plan.get("approach") or ""))
        name = escape(str(solution_plan.get("proposed_skill_name") or "方案"))
        return "\n".join(
            [
                '<section class="question">',
                f"<h3>{name}</h3>",
                f"<p>{summary}</p>",
                f"<p>{approach}</p>",
                f'<form method="post" action="/frontdesk/jobs/{escape(job_id)}/plan-review">',
                '  <input type="hidden" name="decision" value="approve">',
                '  <input type="hidden" name="reason" value="方案已确认，可以进入实现规划冻结。">',
                "  <button type=\"submit\">批准方案</button>",
                "</form>",
                f'<form method="post" action="/frontdesk/jobs/{escape(job_id)}/plan-review">',
                '  <input type="hidden" name="decision" value="request_revision">',
                '  <label>修改意见 <textarea name="reason" required placeholder="说明哪里需要改，Front Desk 会据此重新澄清或修订方案。"></textarea></label>',
                "  <button type=\"submit\">请求修改</button>",
                "</form>",
                "</section>",
            ]
        )

    def _question_options_html(self, options: Any) -> str:
        if not isinstance(options, list) or not options:
            return ""
        rows = ['<div class="option-list">']
        for index, option in enumerate(options, start=1):
            key = chr(ord("A") + index - 1) if index <= 26 else str(index)
            option_text = _clean_frontdesk_option_text(str(option))
            rows.append(
                f'<button class="option-item" type="button" data-option-value="{escape(option_text, quote=True)}">'
                f'<span class="option-key">{escape(key)}.</span>'
                f"<span>{escape(option_text)}</span>"
                "</button>"
            )
        rows.append("</div>")
        return "\n".join(rows)

    def _frontdesk_status_html(self, readiness: str, next_action: str) -> str:
        label, cls = _frontdesk_status_label(readiness, next_action)
        description = _frontdesk_status_description(readiness, next_action)
        return "\n".join(
            [
                f'<span class="status {escape(cls)}">{escape(label)}</span>',
                "<dl>",
                f"<dt>进度</dt><dd>{escape(label)}</dd>",
                f"<dt>说明</dt><dd>{escape(description)}</dd>",
                "</dl>",
            ]
        )

    def _frontdesk_understanding_html(self, elicitation: Mapping[str, Any]) -> str:
        understanding = str(elicitation.get("current_understanding") or "")
        missing = elicitation.get("missing_fields")
        risks = elicitation.get("risk_flags")
        parts = ["<div>", "<h3>当前理解</h3>"]
        understanding_html = escape(understanding) if understanding else '<span class="muted">暂无。</span>'
        parts.append(f"<p>{understanding_html}</p>")
        if isinstance(missing, list) and missing:
            parts.append("<h3>缺失信息</h3><ul>")
            parts.extend(f"<li>{escape(str(item))}</li>" for item in missing)
            parts.append("</ul>")
        if isinstance(risks, list) and risks:
            parts.append("<h3>风险提示</h3><ul>")
            parts.extend(f"<li>{escape(str(item))}</li>" for item in risks)
            parts.append("</ul>")
        parts.append("</div>")
        return "\n".join(parts)

    def _frontdesk_artifact_refs_html(self, state: Mapping[str, Any]) -> str:
        refs = [
            ("核心需求", state.get("core_need_brief_ref")),
            ("方案文档", state.get("solution_plan_markdown_ref")),
            ("方案确认", state.get("latest_plan_review_ref")),
            ("规格", state.get("skill_spec_ref")),
            ("验收标准", state.get("acceptance_criteria_ref")),
            ("验证规格", state.get("verification_spec_ref")),
            ("冻结清单", state.get("freeze_manifest_ref")),
            ("澄清报告", state.get("latest_elicitation_report_ref")),
            ("审核报告", state.get("latest_audit_report_ref")),
        ]
        rows = []
        for label, ref in refs:
            ref_html = escape(str(ref)) if ref else '<span class="muted">未生成</span>'
            rows.append(f"<dt>{escape(label)}</dt><dd>{ref_html}</dd>")
        return "\n".join(["<details><summary>内部证据</summary><dl>", *rows, "</dl></details>"])

    def _submit_feedback_script(self) -> str:
        return "\n".join(
            [
                "<script>",
                "document.addEventListener('click', function (event) {",
                "  var target = event.target;",
                "  if (!(target instanceof Element)) return;",
                "  var option = target.closest('[data-option-value]');",
                "  if (!option) return;",
                "  var textarea = document.querySelector('textarea[name=\"message\"]');",
                "  if (!textarea) return;",
                "  textarea.value = option.getAttribute('data-option-value') || '';",
                "  textarea.focus();",
                "  var status = document.querySelector('[data-submit-status]');",
                "  if (status) { status.textContent = '已填入选项，可以直接继续对话，也可以再补充一句。'; }",
                "});",
                "document.addEventListener('submit', function (event) {",
                "  var form = event.target;",
                "  if (!(form instanceof HTMLFormElement)) return;",
                "  var button = form.querySelector('button[type=\"submit\"]');",
                "  var status = form.querySelector('[data-submit-status]');",
                "  var action = form.getAttribute('action') || '';",
                "  var isFrontDesk = action.indexOf('/frontdesk/jobs') === 0;",
                "  var isRetry = action.slice(-6) === '/retry';",
                "  if (button) { button.disabled = true; button.dataset.originalText = button.textContent || ''; button.textContent = isRetry ? '正在重试...' : '正在处理...'; }",
                "  if (status) { status.textContent = isRetry ? '正在重新请求需求澄清 Agent，通常需要 10-60 秒，请不要重复点击。' : '正在和需求澄清 Agent 对话，通常需要 10-60 秒。'; }",
                "  if (!isFrontDesk) return;",
                "  event.preventDefault();",
                "  var payload = {};",
                "  var formData = new FormData(form);",
                "  formData.forEach(function (value, key) {",
                "    if (Object.prototype.hasOwnProperty.call(payload, key)) {",
                "      if (!Array.isArray(payload[key])) payload[key] = [payload[key]];",
                "      payload[key].push(String(value));",
                "    } else {",
                "      payload[key] = String(value);",
                "    }",
                "  });",
                "  fetch(action, {",
                "    method: 'POST',",
                "    headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },",
                "    body: JSON.stringify(payload)",
                "  }).then(function (response) {",
                "    return response.text().then(function (text) {",
                "      var data = {};",
                "      try { data = text ? JSON.parse(text) : {}; } catch (_error) {}",
                "      if (!response.ok) {",
                "        var error = data.error || {};",
                "        throw new Error(error.message || error.code || ('HTTP ' + response.status));",
                "      }",
                "      if (data && data.status === 'fail_closed') {",
                "        var failure = data.latest_failure || {};",
                "        throw new Error(failure.message || failure.failure_type || '需求澄清没有通过，请查看内部证据。');",
                "      }",
                "      return data;",
                "    });",
                "  }).then(function (data) {",
                "    var next = data && data.links && data.links.self ? data.links.self : window.location.pathname;",
                "    window.location.assign(next);",
                "  }).catch(function (error) {",
                "    if (button) { button.disabled = false; button.textContent = button.dataset.originalText || '继续'; }",
                "    if (status) { status.textContent = '提交失败：' + (error && error.message ? error.message : String(error)); }",
                "  });",
                "});",
                "</script>",
            ]
        )

    def _registry_table_html(self, entries: JsonValue) -> str:
        if not isinstance(entries, list) or not entries:
            return '<p class="muted">No registry entries.</p>'
        rows = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            skill_id = str(entry.get("skill_id") or "")
            version = str(entry.get("version") or "")
            build_job_id = str(entry.get("build_job_id") or "")
            status = str(entry.get("approval_status") or "")
            rows.append(
                "        <tr>"
                f"<td>{escape(skill_id)}</td>"
                f"<td>{escape(version)}</td>"
                f'<td><a href="/jobs/{escape(build_job_id)}">{escape(build_job_id)}</a></td>'
                f"<td>{escape(status)}</td>"
                "</tr>"
            )
        return "\n".join(
            [
                "      <table>",
                "        <thead><tr><th>Skill</th><th>Version</th><th>Job</th><th>Status</th></tr></thead>",
                "        <tbody>",
                *rows,
                "        </tbody>",
                "      </table>",
            ]
        )


def make_handler(api: SkillFoundryAPI) -> type[BaseHTTPRequestHandler]:
    """Return a ``BaseHTTPRequestHandler`` class bound to ``api``."""

    class SkillFoundryHTTPRequestHandler(BaseHTTPRequestHandler):
        server_version = "SkillFoundryWP9/0.1"

        def do_GET(self) -> None:  # noqa: N802 - stdlib API
            self._send(api.handle("GET", self.path, headers=dict(self.headers)))

        def do_POST(self) -> None:  # noqa: N802 - stdlib API
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length else b""
            self._send(api.handle("POST", self.path, body=body, headers=dict(self.headers)))

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, result: APIHTTPResult) -> None:
            self.send_response(result.status)
            self.send_header("Content-Type", result.content_type)
            self.send_header("Content-Length", str(len(result.body)))
            for key, value in result.headers:
                self.send_header(key, value)
            self.end_headers()
            if result.body:
                self.wfile.write(result.body)

    return SkillFoundryHTTPRequestHandler


def make_server(
    api: SkillFoundryAPI,
    *,
    host: str = DEFAULT_SERVE_HOST,
    port: int = DEFAULT_SERVE_PORT,
) -> ThreadingHTTPServer:
    """Create a stdlib HTTP server for the WP9 API/UI."""

    return ThreadingHTTPServer((host, port), make_handler(api))


def serve_http(
    runs_root: str | Path,
    *,
    registry_path: str | Path | None = None,
    host: str = DEFAULT_SERVE_HOST,
    port: int = DEFAULT_SERVE_PORT,
) -> None:
    """Serve the minimal internal API/UI until interrupted."""

    api = SkillFoundryAPI(runs_root, registry_path=registry_path)
    server = make_server(api, host=host, port=port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return
    finally:
        server.server_close()


def _header(headers: Mapping[str, str] | None, name: str) -> str:
    if headers is None:
        return ""
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value.lower()
    return ""


def _query_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _wants_html(headers: Mapping[str, str] | None) -> bool:
    accept = _header(headers, "accept")
    if not accept:
        return False
    return "text/html" in accept and "application/json" not in accept


def _frontdesk_status_label(readiness: str, next_action: str) -> tuple[str, str]:
    if readiness == "frozen" or next_action == "route_to_build":
        return "需求已确定", "success"
    if readiness == "awaiting_plan_review" or next_action == "await_user_plan_review":
        return "等待确认方案", ""
    if readiness == "plan_revision_requested":
        return "等待修订方案", ""
    if readiness == "plan_approved" or next_action == "freeze_approved_plan":
        return "正在冻结方案", "soft"
    if next_action == "elicit":
        return "等待重试", "soft"
    if readiness == "needs_clarification" or next_action == "ask_user":
        return "等待你补充", ""
    if readiness == "human_review_required" or next_action == "human_review":
        return "需要人工审核", "soft"
    if readiness == "rejected" or next_action == "reject":
        return "无法交付", "danger"
    if readiness == "failed" or next_action == "fail_closed":
        return "系统已停止", "danger"
    return "澄清中", "soft"


def _frontdesk_status_description(readiness: str, next_action: str) -> str:
    if readiness == "frozen" or next_action == "route_to_build":
        return "已经形成可进入构建阶段的 Skill 需求规格。"
    if readiness == "awaiting_plan_review" or next_action == "await_user_plan_review":
        return "系统已经整理出核心需求和方案，请确认、要求修改或拒绝。"
    if readiness == "plan_revision_requested":
        return "系统记录了你的修改意见，下一轮会围绕方案修订继续。"
    if readiness == "plan_approved" or next_action == "freeze_approved_plan":
        return "方案已经确认，系统正在做确定性审核和冻结。"
    if next_action == "elicit":
        return "上次模型调用没有完成，已保留你的回答，可以重试生成下一步。"
    if readiness == "needs_clarification" or next_action == "ask_user":
        return "系统正在逐步了解你的真实目标和使用场景。"
    if readiness == "human_review_required" or next_action == "human_review":
        return "这个需求需要人工确认风险、权限或交付边界。"
    if readiness == "rejected" or next_action == "reject":
        return "当前需求不适合自动交付，需要重新定义目标或约束。"
    if readiness == "failed" or next_action == "fail_closed":
        return "系统没有得到可信的结构化结果，可以重试或调整描述。"
    return "系统正在整理上下文，准备进入下一轮判断。"


def _json_mapping(value: Any) -> dict[str, JsonValue]:
    return ensure_json_compatible(value) if isinstance(value, Mapping) else {}  # type: ignore[return-value]


def _json_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _nested_json_str(payload: Mapping[str, Any] | None, path: tuple[str, ...]) -> str | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return _json_str(current)


_FRONTDESK_OPTION_MARKER_RE = re.compile(r"(?:^|[\s：:；;，,。?？])([A-Z])\s*[\)\.、:：]\s*")
_FRONTDESK_OPTION_PREFIX_RE = re.compile(r"^\s*[A-Z]\s*[\)\.、:：]\s*")
_FRONTDESK_REPORT_REF_RE = re.compile(r"^frontdesk/elicitation_report_(\d{3,})\.json$")


def _active_frontdesk_questions(
    state: FrontDeskState | None,
    latest_elicitation: Mapping[str, Any] | None,
    *,
    turn_count: int,
) -> list[Any]:
    if state is None or state.next_action != "ask_user" or not isinstance(latest_elicitation, Mapping):
        return []
    round_index = latest_elicitation.get("round_index")
    if isinstance(round_index, int) and round_index < turn_count:
        return []
    questions = latest_elicitation.get("next_questions")
    return questions if isinstance(questions, list) else []


def _copy_frontdesk_state(state: FrontDeskState, **overrides: Any) -> FrontDeskState:
    payload = state.to_dict()
    payload.update(overrides)
    return FrontDeskState.from_dict(payload)


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _plan_revision_message(*, reason: str, requested_changes: list[str]) -> str:
    lines = [
        "Plan review requested changes.",
        f"Reason: {reason}",
    ]
    if requested_changes:
        lines.append("Requested changes:")
        lines.extend(f"- {item}" for item in requested_changes)
    return "\n".join(lines)


def _frontdesk_review_actions(state: FrontDeskState | None) -> list[dict[str, JsonValue]]:
    if state is None or state.readiness not in {"awaiting_plan_review", "plan_revision_requested"}:
        return []
    return [
        {"decision": "approve", "label": "Approve plan", "method": "POST", "href": f"/frontdesk/jobs/{state.job_id}/plan-review"},
        {
            "decision": "request_revision",
            "label": "Request revision",
            "method": "POST",
            "href": f"/frontdesk/jobs/{state.job_id}/plan-review",
        },
        {"decision": "reject", "label": "Reject", "method": "POST", "href": f"/frontdesk/jobs/{state.job_id}/plan-review"},
        {
            "decision": "human_review",
            "label": "Request human review",
            "method": "POST",
            "href": f"/frontdesk/jobs/{state.job_id}/plan-review",
        },
    ]


def _frontdesk_report_index(ref: str | None) -> int | None:
    if not isinstance(ref, str):
        return None
    match = _FRONTDESK_REPORT_REF_RE.fullmatch(ref)
    if match is None:
        return None
    return int(match.group(1))


def _frontdesk_question_parts(text: str, options: Any) -> tuple[str, list[str]]:
    compact = " ".join(text.split())
    fallback_options = _clean_frontdesk_options(options)
    inline_question, inline_options = _split_inline_frontdesk_options(compact)
    if inline_options and _frontdesk_options_are_richer(inline_options, fallback_options):
        return inline_question, inline_options
    return _clean_frontdesk_question_text(compact, fallback_options), fallback_options


def _split_inline_frontdesk_options(text: str) -> tuple[str, list[str]]:
    matches = list(_FRONTDESK_OPTION_MARKER_RE.finditer(text))
    if len(matches) < 2:
        return text, []

    question_text = text[: matches[0].start(1)].rstrip(" ：:；;，,。")
    options: list[str] = []
    for index, marker in enumerate(matches):
        start = marker.end()
        end = matches[index + 1].start(1) if index + 1 < len(matches) else len(text)
        option = text[start:end].strip(" ：:；;，,。")
        if option:
            options.append(option)
    return question_text, options


def _frontdesk_options_are_richer(inline_options: list[str], fallback_options: list[str]) -> bool:
    if not fallback_options:
        return True
    if len(inline_options) != len(fallback_options):
        return len("".join(inline_options)) > len("".join(fallback_options))
    return len("".join(inline_options)) > len("".join(fallback_options)) + len(inline_options) * 4


def _clean_frontdesk_question_text(text: str, options: Any) -> str:
    compact = " ".join(text.split())
    if isinstance(options, list) and options:
        marker = _FRONTDESK_OPTION_MARKER_RE.search(compact)
        if marker is not None:
            compact = compact[: marker.start(1)].rstrip(" ：:；;，,。")
    return compact


def _clean_frontdesk_options(options: Any) -> list[str]:
    if not isinstance(options, list):
        return []
    cleaned = []
    for option in options:
        option_text = _clean_frontdesk_option_text(str(option))
        if option_text:
            cleaned.append(option_text)
    return cleaned


def _clean_frontdesk_option_text(text: str) -> str:
    return _FRONTDESK_OPTION_PREFIX_RE.sub("", " ".join(text.split()), count=1)


def _truncate(text: str, limit: int) -> str:
    stripped = " ".join(text.split())
    if len(stripped) <= limit:
        return stripped
    return stripped[: max(0, limit - 1)] + "…"


__all__ = [
    "APIError",
    "APIHTTPResult",
    "API_VERSION",
    "DEFAULT_SERVE_HOST",
    "DEFAULT_SERVE_PORT",
    "SkillFoundryAPI",
    "make_handler",
    "make_server",
    "serve_http",
]
