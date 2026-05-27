"""WP7 offline end-to-end orchestration.

This module intentionally stays local and deterministic. It wires the existing
workspace, worker, verifier, and registry gates together without a real Codex
worker, network calls, API server, queue, provider, or production sandbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Mapping

from .final_report import OFFLINE_REPORT_VERSION, emit_final_report, read_final_report
from .registry import (
    APPROVAL_APPROVED,
    DEFAULT_REGISTRY_VERSION,
    DuplicatePolicy,
    LocalSkillRegistry,
    RegistryDuplicateError,
    RegistryGateError,
)
from .schema import (
    ArtifactManifest,
    ArtifactRecord,
    BuildContract,
    ExecutionReport,
    JsonValue,
    RegistryEntry,
    SkillSpec,
    VerificationResult,
    VerificationSpec,
    ensure_json_compatible,
    sha256_file,
    utc_now,
)
from .security import validate_relative_path
from .verifier import VERIFIER_VERSION, Verifier
from .worker import (
    WorkerAdapter,
    WorkerAttemptLimitError,
    WorkerExecutionOutcome,
    WorkerRunContext,
    WorkerRunResult,
)
from .workspace import JOB_ID_RE, LOCKED_INPUT_PATHS, JobWorkspace, initialize_job_workspace


OFFLINE_WORKER_TYPE_PREFIX = "offline"
DEFAULT_REVIEW_STATUS = "offline_wp7_verified"


class Route(StrEnum):
    """Legacy offline route values retained for the explicit compatibility path."""

    BUILD_NEW = "build_new"
    REUSE_EXISTING = "reuse_existing"
    REJECT_UNSAFE = "reject_unsafe"
    ASK_CLARIFYING_QUESTION = "ask_clarifying_question"


class WorkflowStatus(StrEnum):
    """Legacy offline final-report statuses retained outside the retired WP2 graph."""

    RUNNING = "running"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"
    REUSED = "reused"
    BUILT = "built"
    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"
    REPAIR_PLANNED = "repair_planned"
    REGISTERED = "registered"
    REPORT_EMITTED = "report_emitted"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    FAIL_CLOSED = "fail_closed"


class OfflineWorkerMode(StrEnum):
    """Deterministic WP7 worker fixtures."""

    VALID = "valid"
    REPAIRABLE = "repairable"
    ALWAYS_INVALID = "always_invalid"
    PATH_TRAVERSAL = "path_traversal"
    WORKER_PATH_ESCAPE = "worker_path_escape"


@dataclass(frozen=True)
class OfflineRunResult:
    """Result returned by the offline E2E orchestration API."""

    workspace: JobWorkspace
    final_report: dict[str, JsonValue]
    final_report_path: Path
    verification_result: VerificationResult | None = None
    registry_entry: RegistryEntry | None = None


class OfflineDeterministicWorker:
    """Local deterministic worker that produces verifier fixtures for WP7."""

    def __init__(self, mode: OfflineWorkerMode | str = OfflineWorkerMode.VALID) -> None:
        self.mode = OfflineWorkerMode(mode)

    @property
    def worker_type(self) -> str:
        return f"{OFFLINE_WORKER_TYPE_PREFIX}:{self.mode.value}"

    def run(self, context: WorkerRunContext) -> WorkerExecutionOutcome:
        if self.mode is OfflineWorkerMode.VALID:
            return self._valid_package(context, fixture_name="offline-valid")
        if self.mode is OfflineWorkerMode.REPAIRABLE:
            if context.previous_attempt_id is None:
                return self._invalid_package(context, "offline repair fixture failed verifier before repair")
            return self._valid_package(
                context,
                fixture_name="offline-repaired",
                summary=f"Offline worker repaired package after attempt {context.previous_attempt_id}.",
            )
        if self.mode is OfflineWorkerMode.ALWAYS_INVALID:
            return self._invalid_package(context, "offline fixture remains invalid for attempt-limit tests")
        if self.mode is OfflineWorkerMode.PATH_TRAVERSAL:
            return self._path_traversal_package(context)
        if self.mode is OfflineWorkerMode.WORKER_PATH_ESCAPE:
            context.write_text("../outside-job.txt", "must not be written\n")
        raise AssertionError(f"unhandled offline worker mode: {self.mode}")

    def _valid_package(
        self,
        context: WorkerRunContext,
        *,
        fixture_name: str,
        summary: str | None = None,
    ) -> WorkerExecutionOutcome:
        context.write_text("package/SKILL.md", _valid_skill_markdown(fixture_name))
        context.write_text("package/references/guide.md", _reference_markdown())
        context.write_text("package/scripts/helper.py", _helper_script())
        return WorkerExecutionOutcome(
            status="completed",
            exit_status="success",
            summary=summary or "Offline worker wrote a verifier-valid Skill package.",
            artifacts=[
                "package/SKILL.md",
                "package/references/guide.md",
                "package/scripts/helper.py",
            ],
            transcript_lines=["wrote verifier-valid offline package"],
            usage_unavailable_reason="Offline deterministic worker does not call model providers.",
        )

    def _invalid_package(self, context: WorkerRunContext, summary: str) -> WorkerExecutionOutcome:
        context.write_text(
            "package/SKILL.md",
            "\n".join(
                [
                    "---",
                    "name: offline-invalid",
                    "description: Invalid deterministic fixture.",
                    "---",
                    "",
                    "# Offline Invalid Fixture",
                    "",
                    "This package is intentionally missing required verifier sections.",
                    "",
                ]
            ),
        )
        return WorkerExecutionOutcome(
            status="completed",
            exit_status="success",
            summary=summary,
            artifacts=["package/SKILL.md"],
            transcript_lines=["wrote intentionally invalid offline package"],
            usage_unavailable_reason="Offline deterministic worker does not call model providers.",
        )

    def _path_traversal_package(self, context: WorkerRunContext) -> WorkerExecutionOutcome:
        context.write_text("package/SKILL.md", _unsafe_declared_path_skill_markdown())
        context.write_text("package/references/guide.md", _reference_markdown())
        context.write_text("package/scripts/helper.py", _helper_script())
        return WorkerExecutionOutcome(
            status="completed",
            exit_status="success",
            summary="Offline worker wrote a package with an unsafe declared path fixture.",
            artifacts=[
                "package/SKILL.md",
                "package/references/guide.md",
                "package/scripts/helper.py",
            ],
            transcript_lines=["wrote unsafe declared path fixture"],
            usage_unavailable_reason="Offline deterministic worker does not call model providers.",
        )


def build_offline(
    requirement_path: str | Path | None,
    output: str | Path,
    *,
    registry_path: str | Path | None = None,
    route: Route | str | None = None,
    worker_mode: OfflineWorkerMode | str | None = None,
    attempt_limit: int = 2,
    timeout_seconds: int = 300,
    version: str = DEFAULT_REGISTRY_VERSION,
    review_status: str = DEFAULT_REVIEW_STATUS,
    reuse_skill_id: str | None = None,
    reuse_version: str | None = None,
    resume: bool = False,
    overwrite: bool = False,
) -> OfflineRunResult:
    """Run the WP7 offline E2E flow and write ``final_report.json``.

    ``output`` is the job workspace path, for example ``runs/demo-001``.
    When ``resume`` is true, existing workspace refs and artifacts are read
    instead of requiring a requirement file or transcript state.
    """

    output_path = Path(output)
    registry_file = Path(registry_path) if registry_path is not None else output_path.parent / "registry.json"
    selected_mode = OfflineWorkerMode(worker_mode) if worker_mode is not None else None

    if resume:
        workspace = load_offline_workspace(output_path)
        if selected_mode is None:
            selected_mode = _infer_worker_mode(workspace) or OfflineWorkerMode.VALID
        selected_route = _coerce_route(route) if route is not None else Route.BUILD_NEW
    else:
        requirement_text = _read_requirement(requirement_path)
        selected_route = _decide_route(requirement_text, route)
        selected_mode = selected_mode or OfflineWorkerMode.VALID
        workspace = prepare_offline_workspace(
            requirement_path=requirement_path,
            output=output_path,
            requirement_text=requirement_text,
            attempt_limit=attempt_limit,
            timeout_seconds=timeout_seconds,
            overwrite=overwrite,
        )

    if selected_route is Route.REJECT_UNSAFE:
        return _reject_unsafe(workspace, route=selected_route)
    if selected_route is Route.ASK_CLARIFYING_QUESTION:
        return _require_human_review(workspace, route=selected_route)
    if selected_route is Route.REUSE_EXISTING:
        return _reuse_existing(
            workspace,
            registry_path=registry_file,
            route=selected_route,
            reuse_skill_id=reuse_skill_id,
            reuse_version=reuse_version,
        )

    assert selected_mode is not None
    return _run_build_loop(
        workspace,
        registry_path=registry_file,
        route=selected_route,
        worker_mode=selected_mode,
        version=version,
        review_status=review_status,
    )


def prepare_offline_workspace(
    requirement_path: str | Path | None,
    output: str | Path,
    *,
    requirement_text: str | None = None,
    attempt_limit: int = 2,
    timeout_seconds: int = 300,
    overwrite: bool = False,
) -> JobWorkspace:
    """Initialize a WP7 job workspace with offline SkillSpec and contract refs."""

    output_path = Path(output)
    job_id = output_path.name
    if not JOB_ID_RE.fullmatch(job_id):
        raise ValueError("output path name must be a safe SkillFoundry job_id")
    if attempt_limit <= 0:
        raise ValueError("attempt_limit must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    text = requirement_text if requirement_text is not None else _read_requirement(requirement_path)
    workspace = initialize_job_workspace(
        output_path.parent,
        job_id,
        skill_spec=_offline_skill_spec(job_id, text),
        verification_spec=_offline_verification_spec(job_id),
        worker_input=_worker_input_text(text, requirement_path),
        overwrite=overwrite,
    )
    _rewrite_build_contract(workspace, attempt_limit=attempt_limit, timeout_seconds=timeout_seconds)
    workspace.check_locked_inputs()
    return workspace


def load_offline_workspace(job: str | Path) -> JobWorkspace:
    """Load an existing job workspace by reading its refs, not transcript state."""

    root = Path(job)
    manifest = ArtifactManifest.read_json_file(root / "artifact_manifest.json")
    workspace = JobWorkspace(root=root, job_id=manifest.job_id)
    workspace.check_locked_inputs()
    return workspace


def run_offline_attempt(
    workspace: JobWorkspace,
    *,
    worker_mode: OfflineWorkerMode | str = OfflineWorkerMode.VALID,
    attempt_id: str | None = None,
    previous_attempt_id: str | None = None,
) -> WorkerRunResult:
    """Run one deterministic offline worker attempt and sync manifest refs."""

    mode = OfflineWorkerMode(worker_mode)
    selected_attempt_id = attempt_id or _next_attempt_id(workspace)
    adapter = WorkerAdapter(OfflineDeterministicWorker(mode))
    result = adapter.invoke(
        workspace,
        selected_attempt_id,
        previous_attempt_id=previous_attempt_id,
        worker_config={"offline_worker_mode": mode.value},
    )
    _sync_generated_manifest(workspace)
    return result


def verify_offline(job: str | Path, *, attempt_id: str | None = None) -> VerificationResult:
    """Run the independent verifier for an offline job workspace."""

    workspace = load_offline_workspace(job)
    _sync_generated_manifest(workspace)
    selected_attempt_id = attempt_id or _latest_attempt_id(workspace)
    result = Verifier().verify(workspace, attempt_id=selected_attempt_id)
    if selected_attempt_id is not None:
        _archive_verification_result(workspace, result, selected_attempt_id)
        _sync_generated_manifest(workspace)
    return result


def register_offline(
    job: str | Path,
    *,
    registry_path: str | Path,
    version: str = DEFAULT_REGISTRY_VERSION,
    review_status: str = DEFAULT_REVIEW_STATUS,
    duplicate_policy: DuplicatePolicy | str = DuplicatePolicy.IDEMPOTENT,
) -> RegistryEntry:
    """Register a verifier-approved offline package through LocalSkillRegistry."""

    workspace = load_offline_workspace(job)
    registry = LocalSkillRegistry(registry_path, duplicate_policy=duplicate_policy)
    return registry.add_verified(workspace, version=version, review_status=review_status)


def _run_build_loop(
    workspace: JobWorkspace,
    *,
    registry_path: Path,
    route: Route,
    worker_mode: OfflineWorkerMode,
    version: str,
    review_status: str,
) -> OfflineRunResult:
    while True:
        contract = BuildContract.read_yaml_file(workspace.resolve_path("build_contract.yaml", must_exist=True))
        attempts = _attempt_summaries(workspace)
        latest = attempts[-1] if attempts else None
        latest_report = _latest_execution_report(workspace)
        verification = _read_verification_result(workspace)
        verification_attempt_id = _verification_attempt_id(verification)

        if verification is not None and verification.passed and _verification_matches_latest(
            verification_attempt_id,
            latest_report,
        ):
            try:
                entry = LocalSkillRegistry(
                    registry_path,
                    duplicate_policy=DuplicatePolicy.IDEMPOTENT,
                ).add_verified(workspace, version=version, review_status=review_status)
            except (RegistryGateError, RegistryDuplicateError) as exc:
                return _fail_closed(
                    workspace,
                    route=route,
                    registry_path=registry_path,
                    errors=[_error("registry_gate_failed", str(exc))],
                    verification_result=verification,
                )
            return _registered(
                workspace,
                route=route,
                registry_path=registry_path,
                registry_entry=entry,
                verification_result=verification,
            )

        if latest_report is None:
            try:
                run_offline_attempt(workspace, worker_mode=worker_mode, attempt_id="001")
            except WorkerAttemptLimitError as exc:
                return _fail_closed(
                    workspace,
                    route=route,
                    registry_path=registry_path,
                    errors=[_error("attempt_limit_exceeded", str(exc))],
                    verification_result=verification,
                )
            continue

        if latest_report.status == "completed" and latest_report.exit_status == "success":
            if verification is None or verification_attempt_id != latest_report.attempt_id:
                verification = Verifier().verify(workspace, attempt_id=latest_report.attempt_id)
                _archive_verification_result(workspace, verification, latest_report.attempt_id)
                _sync_generated_manifest(workspace)
                continue

            if _is_security_verification_failure(verification):
                return _fail_closed(
                    workspace,
                    route=route,
                    registry_path=registry_path,
                    errors=[_error("security_verification_failed", "; ".join(verification.failures))],
                    verification_result=verification,
                )

            if int(latest_report.attempt_id) >= contract.attempt_limit:
                return _fail_closed(
                    workspace,
                    route=route,
                    registry_path=registry_path,
                    errors=[_error("attempt_limit_exceeded", f"attempt_limit={contract.attempt_limit}")],
                    verification_result=verification,
                )

            try:
                run_offline_attempt(
                    workspace,
                    worker_mode=worker_mode,
                    previous_attempt_id=latest_report.attempt_id,
                )
            except WorkerAttemptLimitError as exc:
                return _fail_closed(
                    workspace,
                    route=route,
                    registry_path=registry_path,
                    errors=[_error("attempt_limit_exceeded", str(exc))],
                    verification_result=verification,
                )
            continue

        if _is_security_execution_failure(latest_report):
            return _fail_closed(
                workspace,
                route=route,
                registry_path=registry_path,
                errors=[_error("security_worker_failed", "; ".join(latest_report.failures))],
                verification_result=verification,
            )

        if int(latest_report.attempt_id) >= contract.attempt_limit:
            return _fail_closed(
                workspace,
                route=route,
                registry_path=registry_path,
                errors=[_error("attempt_limit_exceeded", f"attempt_limit={contract.attempt_limit}")],
                verification_result=verification,
            )

        try:
            run_offline_attempt(
                workspace,
                worker_mode=worker_mode,
                previous_attempt_id=latest_report.attempt_id,
            )
        except WorkerAttemptLimitError as exc:
            return _fail_closed(
                workspace,
                route=route,
                registry_path=registry_path,
                errors=[_error("attempt_limit_exceeded", str(exc))],
                verification_result=verification,
            )


def _registered(
    workspace: JobWorkspace,
    *,
    route: Route,
    registry_path: Path,
    registry_entry: RegistryEntry,
    verification_result: VerificationResult,
) -> OfflineRunResult:
    report = emit_final_report(
        workspace.root,
        final_status=WorkflowStatus.REGISTERED,
        route=route,
        registry_path=registry_path,
        registry_entry=registry_entry,
    )
    return OfflineRunResult(
        workspace=workspace,
        final_report=report,
        final_report_path=workspace.resolve_path("final_report.json", must_exist=True),
        verification_result=verification_result,
        registry_entry=registry_entry,
    )


def _fail_closed(
    workspace: JobWorkspace,
    *,
    route: Route,
    registry_path: Path | None,
    errors: list[dict[str, JsonValue]],
    verification_result: VerificationResult | None,
) -> OfflineRunResult:
    report = emit_final_report(
        workspace.root,
        final_status=WorkflowStatus.FAIL_CLOSED,
        route=route,
        registry_path=registry_path,
        errors=errors,
    )
    return OfflineRunResult(
        workspace=workspace,
        final_report=report,
        final_report_path=workspace.resolve_path("final_report.json", must_exist=True),
        verification_result=verification_result,
        registry_entry=None,
    )


def _reject_unsafe(workspace: JobWorkspace, *, route: Route) -> OfflineRunResult:
    report = emit_final_report(
        workspace.root,
        final_status=WorkflowStatus.REJECTED,
        route=route,
        errors=[_error("unsafe_requirement", "requirement was rejected before worker build")],
    )
    return OfflineRunResult(
        workspace=workspace,
        final_report=report,
        final_report_path=workspace.resolve_path("final_report.json", must_exist=True),
    )


def _require_human_review(workspace: JobWorkspace, *, route: Route) -> OfflineRunResult:
    review_dir = workspace.resolve_path("human_review")
    review_dir.mkdir(parents=False, exist_ok=True)
    payload = {
        "schema_version": "skillfoundry.offline.human_review.v1",
        "job_id": workspace.job_id,
        "status": WorkflowStatus.HUMAN_REVIEW_REQUIRED.value,
        "reason": "requirement is ambiguous and needs clarification before build",
        "question": "Clarify the intended skill trigger, inputs, and expected outputs.",
        "created_at": utc_now(),
    }
    _write_json(workspace.resolve_path("human_review/clarification_request.json"), payload)
    report = emit_final_report(
        workspace.root,
        final_status=WorkflowStatus.HUMAN_REVIEW_REQUIRED,
        route=route,
        human_review={
            "required": True,
            "ref": "human_review/clarification_request.json",
            "sha256": sha256_file(workspace.resolve_path("human_review/clarification_request.json")),
            "reason": str(payload["reason"]),
        },
    )
    return OfflineRunResult(
        workspace=workspace,
        final_report=report,
        final_report_path=workspace.resolve_path("final_report.json", must_exist=True),
    )


def _reuse_existing(
    workspace: JobWorkspace,
    *,
    registry_path: Path,
    route: Route,
    reuse_skill_id: str | None,
    reuse_version: str | None,
) -> OfflineRunResult:
    registry = LocalSkillRegistry(registry_path)
    entry = _select_reuse_entry(registry, skill_id=reuse_skill_id, version=reuse_version)
    if entry is None:
        report = emit_final_report(
            workspace.root,
            final_status=WorkflowStatus.HUMAN_REVIEW_REQUIRED,
            route=route,
            registry_path=registry_path,
            errors=[_error("reuse_candidate_missing", "no approved registry entry matched reuse request")],
            human_review={
                "required": True,
                "reason": "no approved local registry entry is available for reuse",
            },
        )
        return OfflineRunResult(
            workspace=workspace,
            final_report=report,
            final_report_path=workspace.resolve_path("final_report.json", must_exist=True),
        )

    report = emit_final_report(
        workspace.root,
        final_status=WorkflowStatus.REUSED,
        route=route,
        registry_path=registry_path,
        registry_entry=entry,
    )
    return OfflineRunResult(
        workspace=workspace,
        final_report=report,
        final_report_path=workspace.resolve_path("final_report.json", must_exist=True),
        registry_entry=entry,
    )


def _select_reuse_entry(
    registry: LocalSkillRegistry,
    *,
    skill_id: str | None,
    version: str | None,
) -> RegistryEntry | None:
    if skill_id is not None and version is not None:
        try:
            entry = registry.get(skill_id, version)
        except Exception:
            return None
        if entry.approval_status == APPROVAL_APPROVED and entry.quarantine_status == "none":
            return entry
        return None

    candidates = registry.reuse_candidates()
    if skill_id is not None:
        candidates = [entry for entry in candidates if entry.skill_id == skill_id]
    if version is not None:
        candidates = [entry for entry in candidates if entry.version == version]
    return candidates[0] if candidates else None


def _attempt_summaries(workspace: JobWorkspace) -> list[dict[str, JsonValue]]:
    attempts_dir = workspace.resolve_path("attempts", must_exist=True)
    attempts: list[dict[str, JsonValue]] = []
    for child in sorted(attempts_dir.iterdir(), key=lambda path: int(path.name) if path.name.isdecimal() else -1):
        if not child.is_dir() or not child.name.isdecimal():
            continue
        attempt_id = child.name
        report = _read_execution_report(workspace, f"attempts/{attempt_id}/execution_report.json")
        attempts.append(
            ensure_json_compatible(
                {
                    "attempt_id": attempt_id,
                    "input_manifest": _file_ref(workspace, f"attempts/{attempt_id}/input_manifest.json"),
                    "execution_report": _file_ref(workspace, f"attempts/{attempt_id}/execution_report.json"),
                    "worker_transcript": _file_ref(workspace, f"attempts/{attempt_id}/worker_transcript.log"),
                    "output_diff": _file_ref(workspace, f"attempts/{attempt_id}/output_diff.patch"),
                    "verification_result": _file_ref(workspace, f"attempts/{attempt_id}/verification_result.json"),
                    "status": report.status if report is not None else None,
                    "exit_status": report.exit_status if report is not None else None,
                    "failures": report.failures if report is not None else [],
                }
            )  # type: ignore[arg-type]
        )
    return attempts


def _file_ref(workspace: JobWorkspace, ref: str) -> dict[str, JsonValue] | None:
    try:
        path = workspace.resolve_path(ref, must_exist=True)
    except Exception:
        return None
    if not path.is_file():
        return None
    return {"ref": ref, "sha256": sha256_file(path)}


def _rewrite_build_contract(workspace: JobWorkspace, *, attempt_limit: int, timeout_seconds: int) -> None:
    contract = BuildContract.read_yaml_file(workspace.resolve_path("build_contract.yaml", must_exist=True))
    updated = BuildContract(
        job_id=contract.job_id,
        skill_spec_ref=contract.skill_spec_ref,
        verification_spec_ref=contract.verification_spec_ref,
        workspace_root=contract.workspace_root,
        allowed_write_paths=contract.allowed_write_paths,
        blocked_paths=contract.blocked_paths,
        timeout_seconds=timeout_seconds,
        attempt_limit=attempt_limit,
        required_artifacts=contract.required_artifacts,
        locked_input_hashes=contract.locked_input_hashes,
        task_contract_ref=contract.task_contract_ref,
    )
    updated.write_yaml_file(workspace.resolve_path("build_contract.yaml", must_exist=True))
    _upsert_manifest_records(
        workspace,
        ["build_contract.yaml"],
        created_by="skillfoundry.offline",
        locked=True,
    )


def _sync_generated_manifest(workspace: JobWorkspace) -> None:
    refs: list[str] = []
    for root_ref in ("package", "attempts"):
        root = workspace.resolve_path(root_ref, must_exist=True)
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            refs.append(path.relative_to(workspace.root.resolve()).as_posix())
    _upsert_manifest_records(workspace, refs, created_by="skillfoundry.offline", locked=False)


def _upsert_manifest_records(
    workspace: JobWorkspace,
    refs: list[str],
    *,
    created_by: str,
    locked: bool,
) -> None:
    if not refs:
        return
    manifest = workspace.read_manifest()
    by_path = {record.path: record for record in manifest.artifacts}
    order = [record.path for record in manifest.artifacts]
    now = utc_now()
    for ref in refs:
        safe_ref = validate_relative_path(ref).as_posix()
        path = workspace.resolve_path(safe_ref, must_exist=True)
        if not path.is_file():
            continue
        existing = by_path.get(safe_ref)
        record_locked = existing.locked if existing is not None else locked
        attempt_id = _attempt_id_for_ref(safe_ref)
        by_path[safe_ref] = ArtifactRecord(
            artifact_id=existing.artifact_id if existing is not None else f"{workspace.job_id}:{safe_ref.replace('/', ':')}",
            path=safe_ref,
            kind="locked_input" if record_locked else _artifact_kind_for_ref(safe_ref),
            sha256=sha256_file(path),
            created_by=created_by,
            created_at=existing.created_at if existing is not None else now,
            job_id=workspace.job_id,
            attempt_id=attempt_id,
            locked=record_locked,
        )
        if safe_ref not in order:
            order.append(safe_ref)
    manifest.artifacts = [by_path[path] for path in order]
    workspace.write_manifest(manifest)


def _archive_verification_result(
    workspace: JobWorkspace,
    result: VerificationResult,
    attempt_id: str,
) -> None:
    archive_ref = f"attempts/{attempt_id}/verification_result.json"
    result.write_json_file(workspace.resolve_path(archive_ref))


def _artifact_kind_for_ref(ref: str) -> str:
    if ref.startswith("attempts/"):
        return "worker_attempt"
    if ref.startswith("package/"):
        return "skill_package"
    return "offline_artifact"


def _attempt_id_for_ref(ref: str) -> str | None:
    parts = ref.split("/")
    if len(parts) >= 3 and parts[0] == "attempts" and parts[1].isdecimal():
        return parts[1]
    return None


def _latest_execution_report(workspace: JobWorkspace) -> ExecutionReport | None:
    ref = _latest_execution_report_ref(workspace)
    if ref is None:
        return None
    return _read_execution_report(workspace, str(ref["ref"]))


def _latest_execution_report_ref(workspace: JobWorkspace) -> dict[str, JsonValue] | None:
    attempts = _attempt_summaries(workspace)
    for attempt in reversed(attempts):
        report = attempt.get("execution_report")
        if isinstance(report, dict) and report.get("ref"):
            return report  # type: ignore[return-value]
    return None


def _latest_attempt_id(workspace: JobWorkspace) -> str | None:
    attempts = _attempt_summaries(workspace)
    if not attempts:
        return None
    return str(attempts[-1]["attempt_id"])


def _read_execution_report(workspace: JobWorkspace, ref: str) -> ExecutionReport | None:
    try:
        return ExecutionReport.read_json_file(workspace.resolve_path(ref, must_exist=True))
    except Exception:
        return None


def _read_verification_result(workspace: JobWorkspace) -> VerificationResult | None:
    try:
        return VerificationResult.read_json_file(workspace.resolve_path("verifier/verification_result.json", must_exist=True))
    except Exception:
        return None


def _verification_attempt_id(result: VerificationResult | None) -> str | None:
    if result is None:
        return None
    for ref in result.evidence_refs:
        parts = ref.split("/")
        if len(parts) == 3 and parts[0] == "attempts" and parts[2] == "execution_report.json":
            return parts[1]
    return None


def _verification_matches_latest(
    verification_attempt_id: str | None,
    latest_report: ExecutionReport | None,
) -> bool:
    if latest_report is None:
        return verification_attempt_id is None
    return verification_attempt_id == latest_report.attempt_id


def _next_attempt_id(workspace: JobWorkspace) -> str:
    attempts_dir = workspace.resolve_path("attempts", must_exist=True)
    numbers = [int(path.name) for path in attempts_dir.iterdir() if path.is_dir() and path.name.isdecimal()]
    return f"{(max(numbers) if numbers else 0) + 1:03d}"


def _is_security_verification_failure(result: VerificationResult) -> bool:
    security_checks = {
        "artifact_manifest_hashes",
        "locked_input_integrity",
        "package_declared_path_safety",
        "package_path_confinement",
    }
    return any(
        check.get("name") in security_checks and check.get("passed") is False
        for check in result.checks
    )


def _is_security_execution_failure(report: ExecutionReport) -> bool:
    return report.exit_status == "rejected" or any("outside allowed" in item or "unsafe" in item for item in report.failures)


def _infer_worker_mode(workspace: JobWorkspace) -> OfflineWorkerMode | None:
    attempts_dir = workspace.resolve_path("attempts", must_exist=True)
    candidates = sorted(
        [path for path in attempts_dir.iterdir() if path.is_dir() and path.name.isdecimal()],
        key=lambda path: int(path.name),
    )
    for attempt_dir in reversed(candidates):
        input_path = attempt_dir / "input_manifest.json"
        if not input_path.exists():
            continue
        try:
            payload = json.loads(input_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        config = payload.get("worker_config")
        if not isinstance(config, dict):
            continue
        mode = config.get("offline_worker_mode")
        if isinstance(mode, str):
            try:
                return OfflineWorkerMode(mode)
            except ValueError:
                continue
    return None


def _coerce_route(route: Route | str | None) -> Route:
    if route is None:
        return Route.BUILD_NEW
    return route if isinstance(route, Route) else Route(str(route))


def _decide_route(requirement_text: str, route: Route | str | None) -> Route:
    if route is not None:
        return _coerce_route(route)
    lowered = requirement_text.lower()
    if any(marker in lowered for marker in ("reuse_existing", "reuse existing", "reuse-approved")):
        return Route.REUSE_EXISTING
    if any(marker in lowered for marker in ("ambiguous", "unclear", "???", "clarify")):
        return Route.ASK_CLARIFYING_QUESTION
    if any(marker in lowered for marker in ("reject_unsafe", "delete /", "exfiltrate", "steal credentials")):
        return Route.REJECT_UNSAFE
    return Route.BUILD_NEW


def _read_requirement(requirement_path: str | Path | None) -> str:
    if requirement_path is None:
        raise ValueError("requirement_path is required unless resume=True")
    text = Path(requirement_path).read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("requirement file must not be empty")
    return text


def _offline_skill_spec(job_id: str, requirement_text: str) -> SkillSpec:
    title = _first_content_line(requirement_text) or "Offline SkillFoundry Skill"
    return SkillSpec(
        skill_id=f"{job_id}-skill",
        title=title[:120],
        description="Deterministic WP7 offline Skill package request.",
        trigger_scenarios=["The user asks for the local offline fixture skill described by the requirement."],
        non_trigger_scenarios=["The request requires network, a real provider, production queueing, or a real Codex worker."],
        required_inputs=["A local markdown requirement file."],
        expected_outputs=["A verifier-approved Skill package or a fail-closed report."],
        constraints=[
            "No network calls.",
            "No real model provider.",
            "No real Codex worker.",
            "Verifier and registry gates must not be bypassed.",
        ],
        acceptance_criteria=["Final report links build, worker, verifier, registry, manifest, and package hash evidence."],
        reference_materials=[],
        security_notes=["Unsafe or ambiguous requirements stop before package approval."],
    )


def _offline_verification_spec(job_id: str) -> VerificationSpec:
    return VerificationSpec(
        spec_id=f"{job_id}-offline-verification",
        job_id=job_id,
        required_checks=[
            "locked_input_integrity",
            "artifact_manifest_hashes",
            "execution_report_success",
            "skill_required_section",
            "package_declared_path_safety",
            "package_path_confinement",
            "sandbox_smoke",
            "package_hash_recorded",
        ],
        artifact_requirements=list(LOCKED_INPUT_PATHS) + ["package/SKILL.md"],
        path_policies=[
            "reject_absolute_paths",
            "reject_parent_traversal",
            "ban_symlink_components",
        ],
        acceptance_criteria=["Verifier passes and LocalSkillRegistry accepts the hash-matching package."],
        verifier_version=VERIFIER_VERSION,
    )


def _worker_input_text(requirement_text: str, requirement_path: str | Path | None) -> str:
    source = Path(requirement_path).as_posix() if requirement_path is not None else "inline"
    return "\n".join(
        [
            "# Worker Input",
            "",
            f"Requirement source: {source}",
            "",
            requirement_text.strip(),
            "",
        ]
    )


def _first_content_line(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip(" #\t")
        if stripped:
            return stripped
    return None


def _valid_skill_markdown(name: str) -> str:
    return "\n".join(
        [
            "---",
            f"name: {name}",
            "description: Deterministic WP7 offline Skill package.",
            "references:",
            "  - references/guide.md",
            "scripts:",
            "  - scripts/helper.py",
            "---",
            "",
            f"# {name}",
            "",
            "## Overview",
            "",
            "This package is a local offline SkillFoundry fixture for end-to-end verification.",
            "",
            "## When To Use",
            "",
            "- Use when SkillFoundry needs a deterministic offline build artifact.",
            "",
            "## When Not To Use",
            "",
            "- Do not use when the task requires a real provider, network access, or a real Codex worker.",
            "",
            "## Inputs",
            "",
            "- A locked SkillFoundry build contract and worker input manifest.",
            "",
            "## Outputs",
            "",
            "- A verifier-approved local Skill package with traceable evidence refs.",
            "",
            "## Workflow",
            "",
            "1. Read the locked local requirement.",
            "2. Build the package in `package/`.",
            "3. Let the independent verifier and registry gate decide acceptance.",
            "",
            "## Safety",
            "",
            "- Never treat the deterministic worker self-report as approval evidence.",
            "- Keep referenced files inside the package directory.",
            "",
        ]
    )


def _unsafe_declared_path_skill_markdown() -> str:
    return _valid_skill_markdown("offline-unsafe-path").replace(
        "scripts:\n  - scripts/helper.py",
        "scripts:\n  - scripts/../escape.sh",
    )


def _reference_markdown() -> str:
    return "# Offline Guide\n\nReference material for the deterministic WP7 package.\n"


def _helper_script() -> str:
    return "# Deterministic helper fixture; the verifier never executes this file.\n"


def _error(code: str, message: str) -> dict[str, JsonValue]:
    return {"code": code, "message": message}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    compatible = ensure_json_compatible(dict(payload))
    path.write_text(
        json.dumps(compatible, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
