"""ForgeUnit-facing PiWorker adapter helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import shlex
from pathlib import Path
from typing import Any, Mapping, Sequence

from skillfoundry.acceptance import (
    ACCEPTANCE_COVERAGE_PLAN_REF,
    ACCEPTANCE_COVERAGE_RESULT_REF,
    AcceptanceCoverageResult,
)
from skillfoundry.adaptive import NextStepContract
from skillfoundry.adaptive_workspace import adaptive_contract_ref
from skillfoundry.bundle_verifier import BUNDLE_VERIFICATION_RESULT_REF
from skillfoundry.forgeunit_adapter import build_forgeunit_registry_gate_node
from skillfoundry.forgeunit_adapter import _maybe_write_contextforge_frontdesk_boundary_evidence
from skillfoundry.forgeunit_adapter import _upsert_existing_manifest_records
from skillfoundry.frontdesk_workspace import FRONTDESK_TASK_CONTRACT_REF
from skillfoundry.graph_v2 import SkillFoundryV2State, V2Route, V2Stage, V2Status, validate_v2_graph_state
from skillfoundry.pi_worker import (
    PiWorker,
    PiWorkerConfig,
    build_pi_worker_execution_report,
    load_pi_worker_run_result,
)
from skillfoundry.product_contract import PRODUCT_GRADE_REPORT_REF, PRODUCT_REPAIR_PACKET_REF
from skillfoundry.registry import DEFAULT_REGISTRY_VERSION
from skillfoundry.schema import VerificationResult, ensure_json_compatible, sha256_file, utc_now
from skillfoundry.verifier import Verifier
from skillfoundry.workspace import JobWorkspace

from .adaptive_graph import AdaptiveGraphConfig, AdaptiveWorkUnitResult, adaptive_work_unit_result_ref, run_adaptive_graph
from .config import ForgeUnitSkillFoundryError
from .graph import FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF, GRAPH_STATE_SCHEMA_VERSION
from .report import write_evidence_summary
from .state import PRODUCT_TRUST_BOUNDARIES, build_adaptive_summary, write_product_state


ADAPTIVE_PI_WORKER_MODE = "adaptive_pi_worker"


@dataclass(frozen=True)
class AdaptivePiWorkerSkillFactoryResult:
    """Result returned by the opt-in adaptive PiWorker FrontDesk path."""

    job_id: str
    mode: str
    workspace_root: Path
    registry_path: Path
    state: SkillFoundryV2State


@dataclass(frozen=True)
class AdaptivePiWorker:
    """Expose ``PiWorker`` as an ``AdaptiveWorkUnit`` callable."""

    pi_worker: PiWorker

    def __call__(self, workspace: JobWorkspace, contract: object) -> AdaptiveWorkUnitResult:
        result = self.pi_worker.invoke(workspace, contract)
        return AdaptiveWorkUnitResult(**result.to_adaptive_kwargs())


def run_existing_workspace_pi_worker_factory(
    workspace: JobWorkspace,
    *,
    registry_path: str | Path,
    command: str | Sequence[str],
    attempt_limit: int = 2,
    version: str = DEFAULT_REGISTRY_VERSION,
    created_at: str | None = None,
) -> AdaptivePiWorkerSkillFactoryResult:
    """Run a frozen workspace through adaptive steering and PiWorker."""

    if not isinstance(workspace, JobWorkspace):
        raise ForgeUnitSkillFoundryError("workspace must be a JobWorkspace")
    workspace.check_locked_inputs()
    if attempt_limit <= 0:
        raise ForgeUnitSkillFoundryError("attempt_limit must be a positive integer")

    config = AdaptiveGraphConfig(
        runs_root=workspace.root.parent,
        job_id=workspace.job_id,
        max_iterations=attempt_limit,
        repeated_failure_threshold=max(2, min(attempt_limit, 3)),
    )
    pi_worker = _build_pi_worker(command)
    adaptive_result = run_adaptive_graph(config, worker=AdaptivePiWorker(pi_worker))
    state = _with_latest_gate_refs(workspace, adaptive_result.state)
    latest_route = _latest_adaptive_route(state)
    if latest_route != "closure":
        _write_pi_worker_graph_state(workspace, state)
        raise ForgeUnitSkillFoundryError(f"adaptive PiWorker build did not reach closure: {latest_route}")

    latest_iteration = _latest_iteration(state)
    attempt_id = f"{latest_iteration:03d}"
    pi_worker_result = load_pi_worker_run_result(workspace, latest_iteration)
    execution_report = build_pi_worker_execution_report(
        workspace,
        pi_worker_result,
        attempt_id=attempt_id,
        created_at=created_at,
    )
    workspace.resolve_path(f"attempts/{attempt_id}").mkdir(parents=True, exist_ok=True)
    input_manifest_payload = {
        "schema_version": "skillfoundry.pi_worker_attempt_input_manifest.v1",
        "invocation_id": execution_report.invocation_id,
        "job_id": workspace.job_id,
        "attempt_id": attempt_id,
        "worker_type": "skillfoundry.pi_worker.node_sidecar",
        "adapter_version": "skillfoundry.pi_worker.adapter.v1",
        "build_contract_ref": "build_contract.yaml",
        "worker_input_ref": "worker_input.md",
        "task_contract_ref": (
            FRONTDESK_TASK_CONTRACT_REF
            if _optional_workspace_path(workspace, FRONTDESK_TASK_CONTRACT_REF).is_file()
            else None
        ),
        "pi_worker_input_ref": pi_worker_result.input_ref,
        "pi_worker_output_ref": pi_worker_result.output_ref,
        "pi_worker_session_ref": pi_worker_result.session_ref,
        "pi_worker_events_ref": pi_worker_result.events_ref,
        "pi_worker_metrics_ref": pi_worker_result.metrics_ref,
    }
    workspace.resolve_path(f"attempts/{attempt_id}/input_manifest.json").write_text(
        json.dumps(ensure_json_compatible(input_manifest_payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    execution_report.write_json_file(workspace.resolve_path(f"attempts/{attempt_id}/execution_report.json"))
    _maybe_write_contextforge_frontdesk_boundary_evidence(workspace, created_at=created_at)
    _upsert_existing_manifest_records(
        workspace,
        [
            "package/SKILL.md",
            "package/skillfoundry.bundle.json",
            f"attempts/{attempt_id}/input_manifest.json",
            f"attempts/{attempt_id}/execution_report.json",
            "contextforge/goal_contract.json",
            "contextforge/build_node_contract.json",
            "contextforge/verification_gate.json",
            "contextforge/contract_manifest.json",
            "contextforge/ledger.sqlite3",
            "contextforge/goal_harness_state.json",
            BUNDLE_VERIFICATION_RESULT_REF,
        ],
        created_by="skillfoundry.pi_worker.pre_verifier_refresh",
    )
    verifier_result = Verifier().verify(workspace, attempt_id=attempt_id)
    verification_result_path = workspace.resolve_path(f"attempts/{attempt_id}/verification_result.json")
    verifier_result.write_json_file(verification_result_path)
    _upsert_existing_manifest_records(
        workspace,
        [
            "package/SKILL.md",
            "package/skillfoundry.bundle.json",
            f"attempts/{attempt_id}/input_manifest.json",
            f"attempts/{attempt_id}/execution_report.json",
            f"attempts/{attempt_id}/verification_result.json",
            "contextforge/goal_contract.json",
            "contextforge/build_node_contract.json",
            "contextforge/verification_gate.json",
            "contextforge/contract_manifest.json",
            "contextforge/ledger.sqlite3",
            "contextforge/goal_harness_state.json",
            "verifier/verification_result.json",
            "verifier/static_report.json",
            "verifier/sandbox.log",
            BUNDLE_VERIFICATION_RESULT_REF,
        ],
        created_by="skillfoundry.pi_worker",
    )
    state = _with_pi_worker_verification_refs(workspace, state, verifier_result)
    if not verifier_result.passed:
        _write_pi_worker_graph_state(workspace, state)
        raise ForgeUnitSkillFoundryError("adaptive PiWorker build did not pass the SkillFoundry verifier")

    registry_state = build_forgeunit_registry_gate_node(
        workspace.root.parent,
        registry_path=registry_path,
        version=version,
        created_at=created_at,
    )(state)
    final_state = _emit_pi_worker_product_state(
        workspace,
        registry_state,
        registry_path=Path(registry_path),
        created_at=created_at,
    )
    _upsert_existing_manifest_records(
        workspace,
        [
            "contextforge/verification_result.json",
            "registry/decision.json",
            "registry/entry.json",
            "final_report.json",
            "contextforge/forgeunit_skillfoundry_summary.json",
            "contextforge/forgeunit_skillfoundry_product_state.json",
            "contextforge/forgeunit_skillfoundry_graph_state.json",
            f"attempts/{attempt_id}/input_manifest.json",
            f"attempts/{attempt_id}/execution_report.json",
            f"attempts/{attempt_id}/verification_result.json",
            "verifier/verification_result.json",
            "verifier/static_report.json",
            "verifier/sandbox.log",
            BUNDLE_VERIFICATION_RESULT_REF,
        ],
        created_by="skillfoundry.pi_worker",
    )
    return AdaptivePiWorkerSkillFactoryResult(
        job_id=workspace.job_id,
        mode=ADAPTIVE_PI_WORKER_MODE,
        workspace_root=workspace.root,
        registry_path=Path(registry_path),
        state=final_state,
    )


def _build_pi_worker(command: str | Sequence[str]) -> PiWorker:
    parts = _normalize_command(command)
    timeout_seconds = _positive_int(os.environ.get("PI_WORKER_TIMEOUT_SECONDS", "300"), "PI_WORKER_TIMEOUT_SECONDS")
    runtime_name = _optional_env("PI_WORKER_RUNTIME_NAME") or "pi-worker"
    metadata = _pi_worker_runtime_metadata_from_env()
    config = PiWorkerConfig(
        command=tuple(parts),
        timeout_seconds=timeout_seconds,
        runtime_name=runtime_name,
        model_provider=_optional_env("PI_WORKER_PROVIDER"),
        model=_optional_env("PI_WORKER_MODEL"),
        metadata=metadata,
    )
    return PiWorker(config)


def _with_latest_gate_refs(workspace: JobWorkspace, state: SkillFoundryV2State) -> SkillFoundryV2State:
    refs = dict(state.get("refs", {}))
    hashes = dict(state.get("hashes", {}))
    contextforge = dict(state.get("contextforge", {}))

    for ref_key, ref in {
        "bundle_verification_result": BUNDLE_VERIFICATION_RESULT_REF,
        "product_grade_report": PRODUCT_GRADE_REPORT_REF,
        "product_repair_packet": PRODUCT_REPAIR_PACKET_REF,
    }.items():
        path = _optional_workspace_path(workspace, ref)
        if path.is_file():
            refs[ref_key] = ref
            hashes[ref_key] = sha256_file(path)

    for ref_key, ref in {
        "acceptance_coverage_plan": ACCEPTANCE_COVERAGE_PLAN_REF,
        "acceptance_coverage_result": ACCEPTANCE_COVERAGE_RESULT_REF,
    }.items():
        path = _optional_workspace_path(workspace, ref)
        if path.is_file():
            refs[ref_key] = ref
            hashes[ref_key] = sha256_file(path)
            if ref_key == "acceptance_coverage_result":
                try:
                    acceptance = AcceptanceCoverageResult.read_json_file(path)
                except Exception:
                    acceptance = None
                if acceptance is not None:
                    contextforge["acceptance_coverage_passed"] = acceptance.passed
                    contextforge["acceptance_coverage_result_ref"] = ACCEPTANCE_COVERAGE_RESULT_REF

    contextforge["forgeunit_skillfoundry_engine"] = "forgeunit"
    contextforge["forgeunit_skillfoundry_mode"] = ADAPTIVE_PI_WORKER_MODE
    contextforge["worker_self_report_is_not_acceptance"] = True
    contextforge.setdefault("registry_approved", False)

    next_state: SkillFoundryV2State = dict(state)
    next_state.update({"refs": refs, "hashes": hashes, "contextforge": contextforge})
    validate_v2_graph_state(next_state)
    return next_state


def _with_pi_worker_verification_refs(
    workspace: JobWorkspace,
    state: SkillFoundryV2State,
    verification_result: VerificationResult,
) -> SkillFoundryV2State:
    refs = dict(state.get("refs", {}))
    hashes = dict(state.get("hashes", {}))
    contextforge = dict(state.get("contextforge", {}))

    verification_ref = "verifier/verification_result.json"
    verification_path = workspace.resolve_path(verification_ref, must_exist=True)
    refs["skillfoundry_verification_result"] = verification_ref
    refs["verification_result"] = verification_ref
    hashes["skillfoundry_verification_result"] = sha256_file(verification_path)
    hashes["verification_result"] = hashes["skillfoundry_verification_result"]
    contextforge["last_verification_result_id"] = verification_result.result_id
    contextforge["last_verification_status"] = "passed" if verification_result.passed else "failed"
    contextforge["skillfoundry_verification_result_ref"] = verification_ref

    next_state: SkillFoundryV2State = dict(state)
    next_state.update({"refs": refs, "hashes": hashes, "contextforge": contextforge})
    validate_v2_graph_state(next_state)
    return next_state


def _write_pi_worker_graph_state(workspace: JobWorkspace, state: SkillFoundryV2State) -> SkillFoundryV2State:
    payload = _pi_worker_graph_state_payload(workspace, state)
    path = workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    refs = dict(state.get("refs", {}))
    refs["forgeunit_skillfoundry_graph_state"] = FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF
    hashes = dict(state.get("hashes", {}))
    hashes["forgeunit_skillfoundry_graph_state"] = sha256_file(path)
    contextforge = dict(state.get("contextforge", {}))
    contextforge["forgeunit_skillfoundry_graph_state_ref"] = FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF

    next_state: SkillFoundryV2State = dict(state)
    next_state.update({"refs": refs, "hashes": hashes, "contextforge": contextforge})
    validate_v2_graph_state(next_state)
    return next_state


def _emit_pi_worker_product_state(
    workspace: JobWorkspace,
    state: SkillFoundryV2State,
    *,
    registry_path: Path,
    created_at: str | None,
) -> SkillFoundryV2State:
    state = _write_pi_worker_graph_state(workspace, state)
    state = write_product_state(
        workspace,
        state,
        mode=ADAPTIVE_PI_WORKER_MODE,
        registry_path=registry_path,
        created_at=created_at,
    )
    state = write_evidence_summary(
        workspace,
        state,
        mode=ADAPTIVE_PI_WORKER_MODE,
        registry_path=registry_path,
        created_at=created_at,
    )
    return state


def _pi_worker_graph_state_payload(workspace: JobWorkspace, state: SkillFoundryV2State) -> dict[str, Any]:
    refs = state.get("refs", {})
    contextforge = state.get("contextforge", {})
    assert isinstance(refs, dict)
    assert isinstance(contextforge, dict)
    selected_refs = {
        key: value
        for key, value in refs.items()
        if isinstance(value, str)
        and key
        in {
            "adaptive_state",
            "latest_route_plan",
            "latest_next_step_contract",
            "latest_work_unit_result",
            "latest_observation_report",
            "latest_state_correction",
            "decision_ledger",
            "bundle_verification_result",
            "product_grade_report",
            "product_repair_packet",
            "skillfoundry_verification_result",
            "verification_result",
            "acceptance_coverage_plan",
            "acceptance_coverage_result",
            "final_report",
            "registry_decision",
            "registry_entry",
        }
    }
    payload = {
        "schema_version": GRAPH_STATE_SCHEMA_VERSION,
        "job_id": workspace.job_id,
        "engine": "forgeunit",
        "mode": ADAPTIVE_PI_WORKER_MODE,
        "stage": state.get("stage"),
        "status": state.get("status"),
        "refs": selected_refs,
        "adaptive_summary": build_adaptive_summary(contextforge),
        "contextforge": {
            key: value
            for key, value in contextforge.items()
            if key
            in {
                "acceptance_coverage_passed",
                "adaptive_bundle_verification_passed",
                "adaptive_bundle_manifest_status",
                "adaptive_product_grade_passed",
                "last_verification_status",
                "registry_approved",
                "registry_skill_id",
                "registry_version",
                "worker_self_report_is_not_acceptance",
            }
            and isinstance(value, (str, int, bool))
        },
        "trust_boundaries": {
            **PRODUCT_TRUST_BOUNDARIES,
            "command_string_included": False,
        },
    }
    compatible = ensure_json_compatible(payload)
    if not isinstance(compatible, dict):
        raise ForgeUnitSkillFoundryError("adaptive PiWorker graph state payload must be a JSON object")
    return compatible


def _latest_iteration(state: SkillFoundryV2State) -> int:
    contextforge = state.get("contextforge", {})
    if not isinstance(contextforge, dict):
        raise ForgeUnitSkillFoundryError("adaptive graph requires contextforge state")
    iteration = contextforge.get("adaptive_latest_iteration")
    if not isinstance(iteration, int) or isinstance(iteration, bool) or iteration < 0:
        raise ForgeUnitSkillFoundryError("adaptive_latest_iteration must be a non-negative integer")
    return iteration


def _latest_adaptive_route(state: SkillFoundryV2State) -> str:
    contextforge = state.get("contextforge", {})
    if not isinstance(contextforge, dict):
        return ""
    route = contextforge.get("adaptive_latest_route")
    return route if isinstance(route, str) else ""


def _optional_workspace_path(workspace: JobWorkspace, ref: str) -> Path:
    return workspace.root.joinpath(*Path(ref).parts)


def _normalize_command(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        parts = shlex.split(command)
    else:
        parts = [str(part) for part in command if isinstance(part, str) and part.strip()]
    if not parts:
        raise ForgeUnitSkillFoundryError("PiWorker command must not be empty")
    return parts


def _pi_worker_runtime_metadata_from_env() -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for env_name, key in {
        "PI_WORKER_BASE_URL": "base_url",
        "OPENAI_BASE_URL": "base_url",
        "PI_WORKER_REASONING_EFFORT": "reasoning_effort",
        "PI_WORKER_THINKING_LEVEL": "thinking_level",
        "PI_WORKER_REASONING_WITH_TOOLS": "reasoning_with_tools",
        "PI_WORKER_PROMPT_CACHE_KEY": "prompt_cache_key",
        "PI_WORKER_MAX_TOKENS": "max_tokens",
        "PI_WORKER_TOOL_CHOICE": "tool_choice",
    }.items():
        value = os.environ.get(env_name)
        if value is None or not value.strip():
            continue
        if key in metadata:
            continue
        metadata[key] = value
    return metadata


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _positive_int(value: str, field_name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ForgeUnitSkillFoundryError(f"{field_name} must be a positive integer") from exc
    if parsed <= 0:
        raise ForgeUnitSkillFoundryError(f"{field_name} must be a positive integer")
    return parsed
