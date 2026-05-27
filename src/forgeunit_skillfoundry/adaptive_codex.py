"""Opt-in FrontDesk adaptive Codex build path.

This module connects the verified adaptive steering loop to the existing
ForgeUnit command boundary. The worker result remains evidence only; closure is
decided by SkillFoundry verifier, acceptance coverage, BundleVerifier, and the
registry gate.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from skillfoundry.acceptance import (
    ACCEPTANCE_COVERAGE_PLAN_REF,
    ACCEPTANCE_COVERAGE_RESULT_REF,
    ACCEPTANCE_CRITERIA_REF,
    AcceptanceCoverageEvaluator,
    AcceptanceCoverageResult,
    AcceptanceCriteriaPlanner,
)
from skillfoundry.adaptive import NextStepContract
from skillfoundry.adaptive_workspace import adaptive_contract_ref
from skillfoundry.bundle_verifier import BUNDLE_VERIFICATION_RESULT_REF
from skillfoundry.forgeunit_adapter import (
    FORGEUNIT_ADAPTER_VERSION,
    FORGEUNIT_SUMMARY_REF,
    FORGEUNIT_VERIFICATION_RESULT_REF,
    _archive_current_forgeunit_summary,
    _archive_current_verification_result,
    _artifact_paths,
    _bridge_and_verify_forgeunit_attempt_state,
    _dedupe_strings,
    _read_json_object,
    _relative_ref,
    _string_list,
    _upsert_manifest_records,
    build_forgeunit_registry_gate_node,
    run_forgeunit_codex_exec_node,
)
from skillfoundry.graph_v2 import SkillFoundryV2State, V2Route, V2Stage, V2Status, validate_v2_graph_state
from skillfoundry.product_contract import PRODUCT_GRADE_REPORT_REF, PRODUCT_REPAIR_PACKET_REF
from skillfoundry.registry import DEFAULT_REGISTRY_VERSION
from skillfoundry.schema import VerificationResult, ensure_json_compatible, sha256_file, utc_now
from skillfoundry.security import validate_relative_path
from skillfoundry.workspace import JobWorkspace

from .adaptive_graph import AdaptiveGraphConfig, AdaptiveGraphResult, AdaptiveWorkUnitResult, run_adaptive_graph
from .config import ForgeUnitSkillFoundryError
from .graph import FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF, GRAPH_STATE_SCHEMA_VERSION
from .report import write_evidence_summary
from .state import PRODUCT_TRUST_BOUNDARIES, write_product_state


ADAPTIVE_CODEX_MODE = "adaptive_codex"
ADAPTIVE_CODEX_WORKER_INPUT_SCHEMA_VERSION = "forgeunit_skillfoundry.adaptive_codex_worker_input.v1"


@dataclass(frozen=True)
class AdaptiveCodexSkillFactoryResult:
    """Result returned by the opt-in adaptive Codex FrontDesk path."""

    job_id: str
    mode: str
    workspace_root: Path
    registry_path: Path
    state: SkillFoundryV2State


class ForgeUnitCodexAdaptiveWorker:
    """Run one adaptive work unit through the existing ForgeUnit command bridge."""

    def __init__(self, *, command: str, created_at: str | None = None) -> None:
        if not isinstance(command, str) or not command.strip():
            raise ForgeUnitSkillFoundryError("adaptive Codex worker requires a non-empty command")
        self.command = command
        self.created_at = created_at

    def __call__(self, workspace: JobWorkspace, contract: NextStepContract) -> AdaptiveWorkUnitResult:
        attempt_id = f"{contract.iteration:03d}"
        worker_input_ref = _write_adaptive_worker_input(workspace, contract, created_at=self.created_at)
        try:
            node_result = run_forgeunit_codex_exec_node(
                workspace,
                dry_run=False,
                command=self.command,
                adaptive_contract_ref=adaptive_contract_ref(contract.iteration),
                adaptive_worker_input_ref=worker_input_ref,
                unit_objective=contract.next_objective,
                expected_output_refs=_task_expected_outputs(contract),
                write_scope=_worker_write_scope(contract),
            )
            build_state = _build_state_from_node_result(workspace, contract, node_result)
            verified_state = _bridge_and_verify_forgeunit_attempt_state(
                workspace,
                build_state,
                attempt_id=attempt_id,
                created_at=self.created_at,
            )
            summary_archive_ref = _archive_current_forgeunit_summary(workspace, attempt_id)
            verification_archive_ref, verification = _archive_current_verification_result(workspace, attempt_id)
            acceptance_refs, acceptance_failures, acceptance_tests = _run_acceptance_coverage(workspace)
            worker_refs = _worker_result_refs(workspace)
            failures = _verification_failures(verification)
            failures.extend(acceptance_failures)
            produced = _dedupe_strings(
                [
                    *worker_refs,
                    *_existing_refs(workspace, contract.expected_outputs),
                    worker_input_ref,
                ]
            )
            verifier_evidence = _dedupe_strings(
                [
                    FORGEUNIT_SUMMARY_REF,
                    summary_archive_ref,
                    FORGEUNIT_VERIFICATION_RESULT_REF,
                    verification_archive_ref,
                    BUNDLE_VERIFICATION_RESULT_REF,
                    *acceptance_refs,
                ]
            )
            return AdaptiveWorkUnitResult(
                produced_artifacts=produced,
                changed_refs=produced,
                commands_run=["forgeunit codex command boundary"],
                tests_run=[
                    "SkillFoundry Verifier",
                    *acceptance_tests,
                ],
                failures=failures,
                worker_claims=["ForgeUnit command worker completed; independent gates decide acceptance."],
                verifier_evidence=verifier_evidence,
                recommended_next_steps=_recommended_next_steps(failures, verified_state),
                verification_status="failed" if failures else "passed",
            )
        except Exception as exc:
            return AdaptiveWorkUnitResult(
                produced_artifacts=_existing_refs(workspace, [worker_input_ref]),
                changed_refs=_existing_refs(workspace, [worker_input_ref]),
                commands_run=["forgeunit codex command boundary"],
                tests_run=[],
                failures=[_safe_failure("adaptive_codex_worker", exc)],
                worker_claims=["ForgeUnit command worker failed before independent acceptance."],
                verifier_evidence=_existing_refs(
                    workspace,
                    [
                        worker_input_ref,
                        FORGEUNIT_SUMMARY_REF,
                        FORGEUNIT_VERIFICATION_RESULT_REF,
                        BUNDLE_VERIFICATION_RESULT_REF,
                    ],
                ),
                new_unknowns=["The Codex command boundary failed before a complete verifier observation."],
                recommended_next_steps=["Retry with a narrowed contract or inspect command-boundary evidence refs."],
                verification_status="failed",
            )


def run_existing_workspace_adaptive_codex_factory(
    workspace: JobWorkspace,
    *,
    registry_path: str | Path,
    command: str,
    attempt_limit: int = 2,
    version: str = DEFAULT_REGISTRY_VERSION,
    created_at: str | None = None,
) -> AdaptiveCodexSkillFactoryResult:
    """Run a locked workspace through adaptive steering and the Codex command boundary."""

    if not isinstance(workspace, JobWorkspace):
        raise ForgeUnitSkillFoundryError("workspace must be a JobWorkspace")
    workspace.check_locked_inputs()
    if not isinstance(command, str) or not command.strip():
        raise ForgeUnitSkillFoundryError("adaptive Codex build requires a command")
    if not isinstance(attempt_limit, int) or isinstance(attempt_limit, bool) or attempt_limit <= 0:
        raise ForgeUnitSkillFoundryError("attempt_limit must be a positive integer")
    if not isinstance(version, str) or not version.strip():
        raise ForgeUnitSkillFoundryError("version must be a non-empty string")

    config = AdaptiveGraphConfig(
        runs_root=workspace.root.parent,
        job_id=workspace.job_id,
        max_iterations=attempt_limit,
        repeated_failure_threshold=max(2, min(attempt_limit, 3)),
    )
    worker = ForgeUnitCodexAdaptiveWorker(command=command, created_at=created_at)
    adaptive_result = run_adaptive_graph(config, worker=worker)
    state = _with_latest_gate_refs(workspace, adaptive_result.state)
    latest_route = _latest_adaptive_route(state)
    if latest_route != "closure":
        _write_adaptive_codex_graph_state(workspace, state)
        raise ForgeUnitSkillFoundryError(f"adaptive Codex build did not reach closure: {latest_route}")

    registry_state = build_forgeunit_registry_gate_node(
        workspace.root.parent,
        registry_path=registry_path,
        version=version,
        created_at=created_at,
    )(state)
    final_state = _emit_adaptive_codex_product_state(
        workspace,
        registry_state,
        registry_path=Path(registry_path),
        created_at=created_at,
    )
    return AdaptiveCodexSkillFactoryResult(
        job_id=workspace.job_id,
        mode=ADAPTIVE_CODEX_MODE,
        workspace_root=workspace.root,
        registry_path=Path(registry_path),
        state=final_state,
    )


def _write_adaptive_worker_input(
    workspace: JobWorkspace,
    contract: NextStepContract,
    *,
    created_at: str | None,
) -> str:
    ref = f"adaptive/attempts/{contract.iteration:03d}/codex_worker_input.md"
    attempts_dir = workspace.resolve_path("adaptive/attempts", must_exist=True)
    path = attempts_dir / f"{contract.iteration:03d}" / "codex_worker_input.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": ADAPTIVE_CODEX_WORKER_INPUT_SCHEMA_VERSION,
        "job_id": workspace.job_id,
        "iteration": contract.iteration,
        "contract_ref": adaptive_contract_ref(contract.iteration),
        "created_at": created_at or utc_now(),
        "worker_boundary": "forgeunit_codex_exec_command",
        "worker_self_report_is_not_acceptance": True,
        "contract": contract.to_dict(),
    }
    text = "\n".join(
        [
            "# Adaptive Codex Work Unit",
            "",
            "Follow this bounded next-step contract. Do not broaden the mission.",
            "Read the frozen SkillFoundry files and the JSON contract below.",
            "Write only inside the allowed scope plus required ForgeUnit evidence refs.",
            "",
            "Independent verifier, acceptance coverage, ProductGradeGate, and registry gates decide acceptance.",
            "",
            "If the contract asks for `package/skillfoundry.bundle.json`, write a valid prompt_only bundle manifest.",
            "If you create a complete package in an earlier step, writing that manifest is allowed.",
            "",
            "```json",
            json.dumps(payload, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")
    _upsert_manifest_records(workspace, [ref], created_by="forgeunit_skillfoundry.adaptive_codex")
    return ref


def _build_state_from_node_result(
    workspace: JobWorkspace,
    contract: NextStepContract,
    node_result: Any,
) -> SkillFoundryV2State:
    refs = {
        "forgeunit_task_yaml": node_result.task_pack.task_yaml_ref,
        "forgeunit_run": node_result.run_dir_ref,
        "forgeunit_summary": node_result.summary_ref,
    }
    if node_result.dry_run_plan_ref:
        refs["forgeunit_codex_exec_plan"] = node_result.dry_run_plan_ref
    hashes = {
        "forgeunit_task_yaml": node_result.task_pack.task_yaml_hash,
        "forgeunit_summary": node_result.summary_hash,
    }
    contextforge = {
        "forgeunit_adapter_version": FORGEUNIT_ADAPTER_VERSION,
        "forgeunit_run_id": node_result.run_id,
        "forgeunit_status": node_result.status,
        "forgeunit_route": node_result.route,
        "forgeunit_current_node": node_result.current_node,
        "forgeunit_codex_exec_dry_run": False,
        "forgeunit_worker_self_report_is_not_acceptance": True,
        "worker_self_report_is_not_acceptance": True,
        "adaptive_codex_contract_ref": adaptive_contract_ref(contract.iteration),
    }
    state: SkillFoundryV2State = {
        "schema_version": "skillfoundry.graph_v2_state.v1",
        "job_id": workspace.job_id,
        "stage": V2Stage.BUILD_GOAL_NODE.value,
        "status": V2Status.BUILD_RECORDED.value,
        "attempt_count": contract.iteration,
        "attempt_limit": max(contract.iteration, 1),
        "refs": refs,
        "hashes": hashes,
        "contextforge": contextforge,
        "human_review_required": False,
        "next_route": V2Route.CONTINUE.value,
    }
    validate_v2_graph_state(state)
    return state


def _run_acceptance_coverage(workspace: JobWorkspace) -> tuple[list[str], list[str], list[str]]:
    if not workspace.resolve_path(ACCEPTANCE_CRITERIA_REF).is_file():
        return [], [], []
    try:
        plan = AcceptanceCriteriaPlanner().plan(workspace)
        result = AcceptanceCoverageEvaluator().evaluate(workspace, plan=plan)
    except Exception as exc:
        return [], [_safe_failure("acceptance_coverage", exc)], ["AcceptanceCoverageEvaluator"]

    refs = [ACCEPTANCE_COVERAGE_PLAN_REF, ACCEPTANCE_COVERAGE_RESULT_REF]
    _upsert_manifest_records(workspace, refs, created_by="forgeunit_skillfoundry.adaptive_codex")
    if result.passed:
        return refs, [], ["AcceptanceCoverageEvaluator"]
    failures = result.failures or [f"acceptance coverage did not pass: must_failed={result.must_failed}"]
    return refs, [f"acceptance_coverage: {failure}" for failure in failures], ["AcceptanceCoverageEvaluator"]


def _verification_failures(verification: VerificationResult) -> list[str]:
    if verification.passed:
        return []
    return [f"skillfoundry_verifier: {failure}" for failure in verification.failures]


def _worker_result_refs(workspace: JobWorkspace) -> list[str]:
    try:
        summary = _read_json_object(workspace.resolve_path(FORGEUNIT_SUMMARY_REF, must_exist=True), "ForgeUnit summary")
        adapter_result = summary.get("adapter_result")
        if not isinstance(adapter_result, Mapping):
            return []
        worker_result_value = adapter_result.get("worker_result")
        if not isinstance(worker_result_value, str) or not worker_result_value.strip():
            return []
        worker_result_path = Path(worker_result_value)
        if not worker_result_path.is_absolute():
            worker_result_path = workspace.root / worker_result_path
        worker_result_ref = _relative_ref(workspace, worker_result_path)
        worker_result = _read_json_object(workspace.resolve_path(worker_result_ref, must_exist=True), "ForgeUnit worker_result")
    except Exception:
        return []
    return _dedupe_strings(
        [
            worker_result_ref,
            *_artifact_paths(worker_result.get("output_artifacts")),
            *_artifact_paths(worker_result.get("boundary_evidence")),
            *_string_list(worker_result.get("changed_files")),
        ]
    )


def _task_expected_outputs(contract: NextStepContract) -> list[str]:
    # ForgeUnit's command adapter should validate the stable command boundary,
    # while the adaptive contract itself remains visible to the worker. Dynamic
    # contract refs such as adaptive repair evidence are observed by
    # SkillFoundry's verifier loop, not by ForgeUnit's internal task verifier.
    return ["package/SKILL.md", "package/skillfoundry.bundle.json"]


def _worker_write_scope(contract: NextStepContract) -> list[str]:
    scope = [ref for ref in contract.allowed_scope if isinstance(ref, str) and ref.strip()]
    return _dedupe_strings([*scope, "evidence", "verifier", "qa"])


def _existing_refs(workspace: JobWorkspace, refs: list[str]) -> list[str]:
    existing: list[str] = []
    for ref in refs:
        try:
            validate_relative_path(ref)
        except Exception:
            continue
        if workspace.resolve_path(ref).exists():
            existing.append(ref)
    return _dedupe_strings(existing)


def _with_latest_gate_refs(workspace: JobWorkspace, state: SkillFoundryV2State) -> SkillFoundryV2State:
    refs = dict(state.get("refs", {}))
    hashes = dict(state.get("hashes", {}))
    contextforge = dict(state.get("contextforge", {}))

    verification_path = workspace.resolve_path(FORGEUNIT_VERIFICATION_RESULT_REF)
    if verification_path.is_file():
        verification = VerificationResult.read_json_file(verification_path)
        refs["skillfoundry_verification_result"] = FORGEUNIT_VERIFICATION_RESULT_REF
        refs["verification_result"] = FORGEUNIT_VERIFICATION_RESULT_REF
        hashes["skillfoundry_verification_result"] = sha256_file(verification_path)
        hashes["verification_result"] = hashes["skillfoundry_verification_result"]
        contextforge["last_verification_result_id"] = verification.result_id
        contextforge["last_verification_status"] = "passed" if verification.passed else "failed"
        contextforge["skillfoundry_verification_result_ref"] = FORGEUNIT_VERIFICATION_RESULT_REF

    acceptance_path = _optional_workspace_path(workspace, ACCEPTANCE_COVERAGE_RESULT_REF)
    if acceptance_path.is_file():
        acceptance = AcceptanceCoverageResult.read_json_file(acceptance_path)
        refs["acceptance_coverage_plan"] = ACCEPTANCE_COVERAGE_PLAN_REF
        refs["acceptance_coverage_result"] = ACCEPTANCE_COVERAGE_RESULT_REF
        hashes["acceptance_coverage_plan"] = sha256_file(workspace.resolve_path(ACCEPTANCE_COVERAGE_PLAN_REF, must_exist=True))
        hashes["acceptance_coverage_result"] = sha256_file(acceptance_path)
        contextforge["acceptance_coverage_passed"] = acceptance.passed
        contextforge["acceptance_coverage_result_ref"] = ACCEPTANCE_COVERAGE_RESULT_REF

    for key, ref in {
        "bundle_verification_result": BUNDLE_VERIFICATION_RESULT_REF,
        "product_grade_report": PRODUCT_GRADE_REPORT_REF,
        "product_repair_packet": PRODUCT_REPAIR_PACKET_REF,
    }.items():
        if _optional_workspace_path(workspace, ref).is_file():
            refs[key] = ref
            hashes[key] = sha256_file(workspace.resolve_path(ref, must_exist=True))

    contextforge["forgeunit_skillfoundry_engine"] = "forgeunit"
    contextforge["forgeunit_skillfoundry_mode"] = ADAPTIVE_CODEX_MODE
    contextforge["worker_self_report_is_not_acceptance"] = True
    contextforge.setdefault("registry_approved", False)
    next_state: SkillFoundryV2State = dict(state)
    next_state.update({"refs": refs, "hashes": hashes, "contextforge": contextforge})
    validate_v2_graph_state(next_state)
    return next_state


def _emit_adaptive_codex_product_state(
    workspace: JobWorkspace,
    state: SkillFoundryV2State,
    *,
    registry_path: Path,
    created_at: str | None,
) -> SkillFoundryV2State:
    contextforge = dict(state.get("contextforge", {}))
    contextforge.update(
        {
            "forgeunit_skillfoundry_engine": "forgeunit",
            "forgeunit_skillfoundry_mode": ADAPTIVE_CODEX_MODE,
            "forgeunit_skillfoundry_graph_node": "adaptive_codex_emit_product_report",
        }
    )
    final_state: SkillFoundryV2State = dict(state)
    final_state.update(
        {
            "stage": V2Stage.EMIT_REPORT.value,
            "status": V2Status.REPORT_EMITTED.value,
            "contextforge": contextforge,
            "human_review_required": False,
            "next_route": V2Route.CONTINUE.value,
        }
    )
    final_state = _write_adaptive_codex_graph_state(workspace, final_state)
    final_state = write_product_state(
        workspace,
        final_state,
        mode=ADAPTIVE_CODEX_MODE,
        registry_path=registry_path,
        created_at=created_at,
    )
    final_state = write_evidence_summary(
        workspace,
        final_state,
        mode=ADAPTIVE_CODEX_MODE,
        registry_path=registry_path,
        created_at=created_at,
    )
    return final_state


def _write_adaptive_codex_graph_state(workspace: JobWorkspace, state: SkillFoundryV2State) -> SkillFoundryV2State:
    payload = _adaptive_codex_graph_state_payload(workspace, state)
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


def _adaptive_codex_graph_state_payload(workspace: JobWorkspace, state: SkillFoundryV2State) -> dict[str, Any]:
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
            "acceptance_coverage_plan",
            "acceptance_coverage_result",
            "final_report",
            "registry_decision",
            "registry_entry",
            "skillfoundry_verification_result",
            "verification_result",
        }
    }
    payload = {
        "schema_version": GRAPH_STATE_SCHEMA_VERSION,
        "job_id": workspace.job_id,
        "engine": "forgeunit",
        "mode": ADAPTIVE_CODEX_MODE,
        "stage": state.get("stage"),
        "status": state.get("status"),
        "refs": selected_refs,
        "adaptive_summary": {
            "latest_iteration": contextforge.get("adaptive_latest_iteration"),
            "latest_route": contextforge.get("adaptive_latest_route"),
            "latest_decision": contextforge.get("adaptive_latest_decision"),
            "latest_verification_status": contextforge.get("adaptive_latest_verification_status"),
            "current_route_plan_ref": contextforge.get("adaptive_current_route_plan_ref"),
        },
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
        raise ForgeUnitSkillFoundryError("adaptive graph state payload must be a JSON object")
    return compatible


def _latest_adaptive_route(state: Mapping[str, Any]) -> str:
    contextforge = state.get("contextforge") if isinstance(state, Mapping) else None
    if not isinstance(contextforge, Mapping):
        return "unknown"
    route = contextforge.get("adaptive_latest_route")
    return route if isinstance(route, str) and route else "unknown"


def _optional_workspace_path(workspace: JobWorkspace, ref: str) -> Path:
    safe = validate_relative_path(ref)
    return workspace.root.joinpath(*safe.parts)


def _recommended_next_steps(failures: list[str], state: Mapping[str, Any]) -> list[str]:
    if not failures:
        return ["Proceed to adaptive observation and closure check."]
    route = _latest_adaptive_route(state)
    if route == "repair":
        return ["Use the next adaptive contract to repair the failing verifier or acceptance boundary."]
    return ["Shrink the next contract around the first failing verifier or acceptance finding."]


def _safe_failure(prefix: str, exc: Exception) -> str:
    return f"{prefix}: {type(exc).__name__}"
