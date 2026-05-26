"""Deterministic adaptive steering loop for SkillFoundry-on-ForgeUnit."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from skillfoundry.adaptive import (
    CapabilityStateEstimate,
    DecisionRecord,
    NextStepContract,
    ObservationReport,
    StateCorrection,
)
from skillfoundry.adaptive_workspace import (
    ADAPTIVE_CAPABILITY_STATE_REF,
    ADAPTIVE_DECISION_LEDGER_REF,
    adaptive_contract_ref,
    adaptive_correction_ref,
    adaptive_observation_ref,
    append_decision_record,
    initialize_adaptive_workspace,
    read_next_step_contract,
    read_observation_report,
    write_capability_state_estimate,
    write_next_step_contract,
    write_observation_report,
    write_state_correction,
)
from skillfoundry.bundle import BUNDLE_MANIFEST_REF
from skillfoundry.bundle_verifier import BUNDLE_VERIFICATION_RESULT_REF, BundleVerifier
from skillfoundry.graph_v2 import SkillFoundryV2State, V2Route, V2Stage, V2Status, validate_v2_graph_state
from skillfoundry.product_contract import (
    PRODUCT_ACCEPTANCE_MATRIX_REF,
    PRODUCT_GRADE_REPORT_REF,
    PRODUCT_REPAIR_PACKET_REF,
    ProductRepairPacket,
)
from skillfoundry.product_grade_gate import ProductGradeGate
from skillfoundry.security import PathSecurityError, assert_under_root, validate_relative_path
from skillfoundry.workspace import JobWorkspace, initialize_job_workspace

from .config import ForgeUnitSkillFoundryError, validate_job_id


ADAPTIVE_GRAPH_SCHEMA_VERSION = "forgeunit_skillfoundry.adaptive_graph.v1"
ADAPTIVE_WORK_UNIT_RESULT_SCHEMA_VERSION = "forgeunit_skillfoundry.adaptive_work_unit_result.v1"
DEFAULT_ADAPTIVE_MAX_ITERATIONS = 4
DEFAULT_REPEATED_FAILURE_THRESHOLD = 2


@dataclass(frozen=True)
class AdaptiveGraphConfig:
    """Configuration for one deterministic adaptive steering run."""

    runs_root: Path
    job_id: str
    max_iterations: int = DEFAULT_ADAPTIVE_MAX_ITERATIONS
    repeated_failure_threshold: int = DEFAULT_REPEATED_FAILURE_THRESHOLD
    overwrite_workspace: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "runs_root", Path(self.runs_root))
        validate_job_id(self.job_id)
        if not isinstance(self.max_iterations, int) or isinstance(self.max_iterations, bool) or self.max_iterations <= 0:
            raise ForgeUnitSkillFoundryError("max_iterations must be a positive integer")
        if (
            not isinstance(self.repeated_failure_threshold, int)
            or isinstance(self.repeated_failure_threshold, bool)
            or self.repeated_failure_threshold <= 0
        ):
            raise ForgeUnitSkillFoundryError("repeated_failure_threshold must be a positive integer")


@dataclass(frozen=True)
class AdaptiveWorkUnitResult:
    """Refs-only result from one bounded adaptive work unit."""

    produced_artifacts: list[str] = field(default_factory=list)
    changed_refs: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    worker_claims: list[str] = field(default_factory=list)
    verifier_evidence: list[str] = field(default_factory=list)
    new_unknowns: list[str] = field(default_factory=list)
    recommended_next_steps: list[str] = field(default_factory=list)
    verification_status: str = "passed"

    def validate(self) -> None:
        for name in ("produced_artifacts", "changed_refs", "verifier_evidence"):
            for item in getattr(self, name):
                validate_relative_path(item)
        for name in (
            "commands_run",
            "tests_run",
            "failures",
            "worker_claims",
            "new_unknowns",
            "recommended_next_steps",
        ):
            value = getattr(self, name)
            if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
                raise ForgeUnitSkillFoundryError(f"{name} must be a list of non-empty strings")
        if self.verification_status not in {"passed", "failed", "not_run", "review_required"}:
            raise ForgeUnitSkillFoundryError("verification_status is not supported")


AdaptiveWorkUnit = Callable[[JobWorkspace, NextStepContract], AdaptiveWorkUnitResult]


@dataclass(frozen=True)
class AdaptiveGraphResult:
    """Result returned by the adaptive steering graph."""

    job_id: str
    workspace_root: Path
    state: SkillFoundryV2State


def compile_adaptive_graph(
    config: AdaptiveGraphConfig,
    *,
    worker: AdaptiveWorkUnit | None = None,
) -> Any:
    """Compile the deterministic adaptive steering loop."""

    selected_worker = worker or default_adaptive_worker
    graph = StateGraph(SkillFoundryV2State)
    graph.add_node("initialize_adaptive_state", _initialize_adaptive_state_node(config))
    graph.add_node("propose_next_step", _propose_next_step_node(config))
    graph.add_node("execute_work_unit", _execute_work_unit_node(config, selected_worker))
    graph.add_node("collect_observation", _collect_observation_node(config))
    graph.add_node("correct_state", _correct_state_node(config))
    graph.add_edge(START, "initialize_adaptive_state")
    graph.add_edge("initialize_adaptive_state", "propose_next_step")
    graph.add_edge("propose_next_step", "execute_work_unit")
    graph.add_edge("execute_work_unit", "collect_observation")
    graph.add_edge("collect_observation", "correct_state")
    graph.add_conditional_edges(
        "correct_state",
        _route_after_correction(config),
        {
            "loop": "propose_next_step",
            "end": END,
        },
    )
    return graph.compile()


def run_adaptive_graph(
    config: AdaptiveGraphConfig,
    *,
    worker: AdaptiveWorkUnit | None = None,
) -> AdaptiveGraphResult:
    """Run the deterministic adaptive steering loop."""

    graph = compile_adaptive_graph(config, worker=worker)
    state = graph.invoke({"job_id": config.job_id})
    validate_v2_graph_state(state)
    workspace = JobWorkspace(root=config.runs_root / config.job_id, job_id=config.job_id)
    return AdaptiveGraphResult(job_id=config.job_id, workspace_root=workspace.root, state=state)


def default_adaptive_worker(workspace: JobWorkspace, contract: NextStepContract) -> AdaptiveWorkUnitResult:
    """Write deterministic fixture artifacts requested by a next-step contract."""

    produced: list[str] = []
    claims: list[str] = []
    for ref in contract.expected_outputs:
        if ref == "package/SKILL.md":
            path = workspace.resolve_path(ref)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "# Adaptive Fixture Skill\n\n"
                "## Overview\n\n"
                "Deterministic skill entry generated by the adaptive graph fixture.\n",
                encoding="utf-8",
            )
            produced.append(ref)
            claims.append("Wrote package/SKILL.md.")
        elif ref == "package/skillfoundry.bundle.json":
            path = workspace.resolve_path(ref)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "skillfoundry.bundle.v1",
                        "bundle_id": workspace.job_id,
                        "bundle_type": "prompt_only",
                        "entrypoint": "SKILL.md",
                        "capability_surface": {},
                        "runtime_assets": [],
                        "data_assets": [],
                        "references": [],
                        "environment": {},
                        "permissions": {},
                        "verification": {},
                        "distribution": {},
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            produced.append(ref)
            claims.append("Wrote package/skillfoundry.bundle.json.")
        elif ref.startswith("adaptive/"):
            path = _writable_workspace_path(workspace, ref)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("deterministic adaptive evidence\n", encoding="utf-8")
            produced.append(ref)
            claims.append(f"Wrote {ref}.")

    return AdaptiveWorkUnitResult(
        produced_artifacts=produced,
        changed_refs=list(produced),
        worker_claims=claims or ["No file changes were required."],
        verifier_evidence=list(produced),
        recommended_next_steps=["Re-run steering correction."],
        verification_status="passed",
    )


def _initialize_adaptive_state_node(config: AdaptiveGraphConfig) -> Any:
    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        _require_config_job_state(config, state)
        workspace = _prepare_workspace(config)
        initialize_adaptive_workspace(workspace)
        initial_state = CapabilityStateEstimate(
            job_id=config.job_id,
            iteration=0,
            objective="Build a verified capability bundle through adaptive steering.",
            current_phase="adaptive_build",
            known_good=["Workspace and locked inputs exist."],
            known_bad=[],
            known_unknowns=["Package entrypoint and bundle manifest status must be inspected."],
            current_risks=["Worker self-report cannot be treated as acceptance."],
            latest_verification_status="not_run",
            next_best_step="Inspect package state and propose the next bounded work unit.",
            confidence=0.4,
        )
        write_capability_state_estimate(workspace, initial_state)
        next_state: SkillFoundryV2State = {
            "schema_version": "skillfoundry.graph_v2_state.v1",
            "job_id": config.job_id,
            "stage": V2Stage.BUILD_GOAL_NODE.value,
            "status": V2Status.RUNNING.value,
            "attempt_count": 0,
            "attempt_limit": config.max_iterations,
            "refs": {
                "adaptive_state": ADAPTIVE_CAPABILITY_STATE_REF,
                "decision_ledger": ADAPTIVE_DECISION_LEDGER_REF,
            },
            "hashes": {},
            "contextforge": {
                "adaptive_graph_schema_version": ADAPTIVE_GRAPH_SCHEMA_VERSION,
                "adaptive_latest_iteration": 0,
                "adaptive_latest_route": "continue",
                "adaptive_latest_decision": "continue",
                "adaptive_latest_verification_status": "not_run",
                "worker_self_report_is_not_acceptance": True,
            },
            "human_review_required": False,
            "next_route": V2Route.CONTINUE.value,
        }
        validate_v2_graph_state(next_state)
        return next_state

    return _node


def _propose_next_step_node(config: AdaptiveGraphConfig) -> Any:
    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        _require_config_job_state(config, state)
        workspace = JobWorkspace(root=config.runs_root / config.job_id, job_id=config.job_id)
        contextforge = dict(state.get("contextforge", {}))
        iteration = int(contextforge.get("adaptive_latest_iteration", 0)) + 1
        contract = _build_next_step_contract(workspace, config=config, state=state, iteration=iteration)
        write_next_step_contract(workspace, contract)
        refs = dict(state.get("refs", {}))
        refs["latest_next_step_contract"] = adaptive_contract_ref(iteration)
        contextforge.update(
            {
                "adaptive_latest_iteration": iteration,
                "adaptive_latest_route": "continue",
                "adaptive_current_contract_ref": adaptive_contract_ref(iteration),
            }
        )
        next_state: SkillFoundryV2State = dict(state)
        next_state.update(
            {
                "attempt_count": iteration,
                "refs": refs,
                "contextforge": contextforge,
                "next_route": V2Route.CONTINUE.value,
            }
        )
        validate_v2_graph_state(next_state)
        return next_state

    return _node


def _execute_work_unit_node(config: AdaptiveGraphConfig, worker: AdaptiveWorkUnit) -> Any:
    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        _require_config_job_state(config, state)
        workspace = JobWorkspace(root=config.runs_root / config.job_id, job_id=config.job_id)
        iteration = _latest_iteration(state)
        contract = read_next_step_contract(workspace, iteration)
        result = worker(workspace, contract)
        result.validate()
        work_unit_result_ref = adaptive_work_unit_result_ref(iteration)
        _write_work_unit_result(workspace, iteration=iteration, result=result)
        refs = dict(state.get("refs", {}))
        refs["latest_work_unit_result"] = work_unit_result_ref
        contextforge = dict(state.get("contextforge", {}))
        contextforge.update(
            {
                "adaptive_current_work_unit_result_ref": work_unit_result_ref,
                "adaptive_latest_worker_reported_status": result.verification_status,
                "adaptive_latest_verification_status": "not_run",
            }
        )
        next_state: SkillFoundryV2State = dict(state)
        next_state.update({"refs": refs, "contextforge": contextforge})
        validate_v2_graph_state(next_state)
        return next_state

    return _node


def _collect_observation_node(config: AdaptiveGraphConfig) -> Any:
    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        _require_config_job_state(config, state)
        workspace = JobWorkspace(root=config.runs_root / config.job_id, job_id=config.job_id)
        contextforge = dict(state.get("contextforge", {}))
        iteration = _latest_iteration(state)
        work_unit_result = _read_work_unit_result(workspace, iteration)
        bundle_result = BundleVerifier().verify(workspace)
        verifier_evidence = _dedupe_refs([*work_unit_result.verifier_evidence, BUNDLE_VERIFICATION_RESULT_REF])
        failures = list(work_unit_result.failures)
        if work_unit_result.verification_status in {"failed", "review_required"} and not failures:
            failures.append(f"worker_reported_status: {work_unit_result.verification_status}")
        if bundle_result.manifest_status != "missing" and not bundle_result.passed:
            failures.extend(bundle_result.failures)
        verification_status = (
            "passed"
            if bundle_result.manifest_status == "valid" and bundle_result.passed
            else "failed"
            if bundle_result.manifest_status != "missing" and not bundle_result.passed
            else "not_run"
        )
        product_grade_ran = _product_acceptance_matrix_exists(workspace)
        if product_grade_ran:
            try:
                product_report = ProductGradeGate().evaluate(workspace)
            except Exception as exc:
                failures.append(f"product_grade_gate_error: {exc}")
                contextforge["adaptive_product_grade_passed"] = False
                contextforge["adaptive_product_grade_error"] = type(exc).__name__
                verification_status = "failed"
            else:
                verifier_evidence = _dedupe_refs(
                    [*verifier_evidence, PRODUCT_GRADE_REPORT_REF, PRODUCT_REPAIR_PACKET_REF]
                )
                product_finding_ids = [finding.finding_id for finding in product_report.findings]
                contextforge["adaptive_product_grade_report_ref"] = PRODUCT_GRADE_REPORT_REF
                contextforge["adaptive_product_repair_packet_ref"] = PRODUCT_REPAIR_PACKET_REF
                contextforge["adaptive_product_grade_passed"] = product_report.product_grade
                contextforge["adaptive_product_grade_finding_ids"] = product_finding_ids
                if product_report.product_grade:
                    contextforge["adaptive_product_grade_status"] = "passed"
                else:
                    contextforge["adaptive_product_grade_status"] = "failed"
                    verification_status = "failed"
                    failures.extend(
                        f"product_grade:{finding.finding_id}: {finding.title}"
                        for finding in product_report.findings
                    )
        observation = ObservationReport(
            job_id=config.job_id,
            iteration=iteration,
            contract_ref=adaptive_contract_ref(iteration),
            produced_artifacts=list(work_unit_result.produced_artifacts),
            changed_refs=list(work_unit_result.changed_refs),
            commands_run=list(work_unit_result.commands_run),
            tests_run=list(work_unit_result.tests_run),
            failures=failures,
            worker_claims=list(work_unit_result.worker_claims),
            verifier_evidence=verifier_evidence,
            new_unknowns=list(work_unit_result.new_unknowns),
            recommended_next_steps=list(work_unit_result.recommended_next_steps),
        )
        write_observation_report(workspace, observation)
        refs = dict(state.get("refs", {}))
        refs["latest_observation_report"] = adaptive_observation_ref(iteration)
        refs["bundle_verification_result"] = BUNDLE_VERIFICATION_RESULT_REF
        if product_grade_ran:
            refs["product_grade_report"] = PRODUCT_GRADE_REPORT_REF
            refs["product_repair_packet"] = PRODUCT_REPAIR_PACKET_REF
        contextforge["adaptive_current_observation_ref"] = adaptive_observation_ref(iteration)
        contextforge["adaptive_bundle_verification_result_ref"] = BUNDLE_VERIFICATION_RESULT_REF
        contextforge["adaptive_bundle_verification_passed"] = bundle_result.passed
        contextforge["adaptive_bundle_manifest_status"] = bundle_result.manifest_status
        contextforge["adaptive_latest_verification_status"] = verification_status
        next_state: SkillFoundryV2State = dict(state)
        next_state.update({"refs": refs, "contextforge": contextforge})
        validate_v2_graph_state(next_state)
        return next_state

    return _node


def _correct_state_node(config: AdaptiveGraphConfig) -> Any:
    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        _require_config_job_state(config, state)
        workspace = JobWorkspace(root=config.runs_root / config.job_id, job_id=config.job_id)
        contextforge = dict(state.get("contextforge", {}))
        iteration = _latest_iteration(state)
        observation = read_observation_report(workspace, iteration)
        route, decision, failure_count, status = _decide_after_observation(
            workspace,
            state=state,
            observation=observation,
            config=config,
        )
        corrected_state = CapabilityStateEstimate(
            job_id=config.job_id,
            iteration=iteration,
            objective="Build a verified capability bundle through adaptive steering.",
            current_phase="adaptive_build",
            known_good=_known_good(workspace, route),
            known_bad=list(observation.failures),
            known_unknowns=list(observation.new_unknowns),
            current_risks=_current_risks(route),
            latest_verification_status=str(contextforge.get("adaptive_latest_verification_status", "not_run")),
            next_best_step=_next_best_step(route),
            confidence=_confidence(route),
        )
        write_capability_state_estimate(workspace, corrected_state)
        correction = StateCorrection(
            job_id=config.job_id,
            iteration=iteration,
            previous_state_ref=ADAPTIVE_CAPABILITY_STATE_REF,
            observation_ref=adaptive_observation_ref(iteration),
            corrected_state_ref=ADAPTIVE_CAPABILITY_STATE_REF,
            decision=decision,
            rationale=_decision_rationale(route),
            next_route=route,
        )
        write_state_correction(workspace, correction)
        append_decision_record(
            workspace,
            DecisionRecord(
                decision_id=f"adaptive-decision-{iteration:03d}",
                iteration=iteration,
                context=f"Adaptive route after observation {adaptive_observation_ref(iteration)}.",
                options=["continue", "repair", "review_required", "closure"],
                chosen_option=route,
                rationale=correction.rationale,
                risk="Incorrect route selection can either hide quality failures or waste work units.",
                expected_evidence=[adaptive_observation_ref(iteration), adaptive_correction_ref(iteration)],
                fallback="Request reviewer or shrink the next-step contract.",
                reviewer="deterministic-adaptive-policy",
            ),
        )
        refs = dict(state.get("refs", {}))
        refs.update(
            {
                "adaptive_state": ADAPTIVE_CAPABILITY_STATE_REF,
                "latest_state_correction": adaptive_correction_ref(iteration),
                "decision_ledger": ADAPTIVE_DECISION_LEDGER_REF,
            }
        )
        contextforge.update(
            {
                "adaptive_failure_count": failure_count,
                "adaptive_latest_decision": decision,
                "adaptive_latest_route": route,
                "adaptive_latest_verification_status": corrected_state.latest_verification_status,
            }
        )
        next_state: SkillFoundryV2State = dict(state)
        next_state.update(
            {
                "stage": V2Stage.HUMAN_REVIEW.value if route == "review_required" else V2Stage.EMIT_REPORT.value if route == "closure" else V2Stage.BUILD_GOAL_NODE.value,
                "status": status,
                "refs": refs,
                "contextforge": contextforge,
                "human_review_required": route == "review_required",
                "next_route": V2Route.HUMAN_REVIEW.value if route == "review_required" else V2Route.CONTINUE.value,
            }
        )
        validate_v2_graph_state(next_state)
        return next_state

    return _node


def _route_after_correction(config: AdaptiveGraphConfig) -> Callable[[SkillFoundryV2State], str]:
    def _route(state: SkillFoundryV2State) -> str:
        _require_config_job_state(config, state)
        contextforge = state.get("contextforge", {})
        route = contextforge.get("adaptive_latest_route") if isinstance(contextforge, dict) else None
        if route in {"continue", "repair"} and int(state.get("attempt_count", 0)) < config.max_iterations:
            return "loop"
        return "end"

    return _route


def _prepare_workspace(config: AdaptiveGraphConfig) -> JobWorkspace:
    workspace_root = config.runs_root / config.job_id
    if workspace_root.exists() and (workspace_root / "artifact_manifest.json").is_file() and not config.overwrite_workspace:
        workspace = JobWorkspace(root=workspace_root, job_id=config.job_id)
        workspace.check_locked_inputs()
        return workspace
    return initialize_job_workspace(config.runs_root, config.job_id, overwrite=config.overwrite_workspace)


def _require_config_job_state(config: AdaptiveGraphConfig, state: SkillFoundryV2State) -> None:
    validate_v2_graph_state(state)
    job_id = state.get("job_id")
    if job_id != config.job_id:
        raise ForgeUnitSkillFoundryError(f"adaptive graph state job_id must be {config.job_id!r}, got {job_id!r}")


def _latest_iteration(state: SkillFoundryV2State) -> int:
    contextforge = state.get("contextforge", {})
    if not isinstance(contextforge, dict):
        raise ForgeUnitSkillFoundryError("adaptive graph requires contextforge state")
    iteration = contextforge.get("adaptive_latest_iteration")
    if not isinstance(iteration, int) or isinstance(iteration, bool) or iteration < 0:
        raise ForgeUnitSkillFoundryError("adaptive_latest_iteration must be a non-negative integer")
    return iteration


def adaptive_work_unit_result_ref(iteration: int) -> str:
    if not isinstance(iteration, int) or isinstance(iteration, bool) or iteration <= 0:
        raise ForgeUnitSkillFoundryError("work-unit iteration must be a positive integer")
    return f"adaptive/attempts/{iteration:03d}/work_unit_result.json"


def _write_work_unit_result(workspace: JobWorkspace, *, iteration: int, result: AdaptiveWorkUnitResult) -> None:
    result.validate()
    ref = adaptive_work_unit_result_ref(iteration)
    payload = {
        "schema_version": ADAPTIVE_WORK_UNIT_RESULT_SCHEMA_VERSION,
        "job_id": workspace.job_id,
        "iteration": iteration,
        "contract_ref": adaptive_contract_ref(iteration),
        "produced_artifacts": list(result.produced_artifacts),
        "changed_refs": list(result.changed_refs),
        "commands_run": list(result.commands_run),
        "tests_run": list(result.tests_run),
        "failures": list(result.failures),
        "worker_claims": list(result.worker_claims),
        "verifier_evidence": list(result.verifier_evidence),
        "new_unknowns": list(result.new_unknowns),
        "recommended_next_steps": list(result.recommended_next_steps),
        "worker_verification_status": result.verification_status,
    }
    path = _writable_workspace_path(workspace, ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _writable_workspace_path(workspace: JobWorkspace, ref: str) -> Path:
    safe = validate_relative_path(ref)
    root = workspace.root.resolve(strict=True)
    current = root
    for part in safe.parts[:-1]:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise ForgeUnitSkillFoundryError(f"unsafe adaptive artifact parent: {ref}")
            assert_under_root(root, current)
        else:
            current.mkdir()
    path = current / safe.parts[-1]
    if path.exists() and path.is_symlink():
        raise ForgeUnitSkillFoundryError(f"unsafe adaptive artifact target: {ref}")
    try:
        return assert_under_root(root, path)
    except PathSecurityError as exc:
        raise ForgeUnitSkillFoundryError(f"adaptive artifact path escapes workspace: {ref}") from exc


def _read_work_unit_result(workspace: JobWorkspace, iteration: int) -> AdaptiveWorkUnitResult:
    ref = adaptive_work_unit_result_ref(iteration)
    try:
        payload = json.loads(workspace.resolve_path(ref, must_exist=True).read_text(encoding="utf-8"))
    except Exception as exc:
        raise ForgeUnitSkillFoundryError(f"adaptive work-unit result is missing or invalid: {ref}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ForgeUnitSkillFoundryError(f"adaptive work-unit result must be a JSON object: {ref}")
    if payload.get("schema_version") != ADAPTIVE_WORK_UNIT_RESULT_SCHEMA_VERSION:
        raise ForgeUnitSkillFoundryError(f"adaptive work-unit result has unsupported schema_version: {ref}")
    if payload.get("job_id") != workspace.job_id:
        raise ForgeUnitSkillFoundryError(f"adaptive work-unit result job_id mismatch: {ref}")
    if payload.get("iteration") != iteration:
        raise ForgeUnitSkillFoundryError(f"adaptive work-unit result iteration mismatch: {ref}")
    result = AdaptiveWorkUnitResult(
        produced_artifacts=_string_list(payload.get("produced_artifacts")),
        changed_refs=_string_list(payload.get("changed_refs")),
        commands_run=_string_list(payload.get("commands_run")),
        tests_run=_string_list(payload.get("tests_run")),
        failures=_string_list(payload.get("failures")),
        worker_claims=_string_list(payload.get("worker_claims")),
        verifier_evidence=_string_list(payload.get("verifier_evidence")),
        new_unknowns=_string_list(payload.get("new_unknowns")),
        recommended_next_steps=_string_list(payload.get("recommended_next_steps")),
        verification_status=str(payload.get("worker_verification_status", "not_run")),
    )
    result.validate()
    return result


def _build_next_step_contract(
    workspace: JobWorkspace,
    *,
    config: AdaptiveGraphConfig,
    state: SkillFoundryV2State,
    iteration: int,
) -> NextStepContract:
    contextforge = state.get("contextforge", {})
    route = contextforge.get("adaptive_latest_route") if isinstance(contextforge, dict) else None
    attempt_dir = f"adaptive/attempts/{iteration:03d}"
    if route == "repair":
        product_repair_contract = _build_product_repair_next_step_contract(
            workspace,
            config=config,
            iteration=iteration,
            attempt_dir=attempt_dir,
        )
        if product_repair_contract is not None:
            return product_repair_contract
        objective = "Repair the failed adaptive work unit with the smallest evidence-producing change."
        outputs = [f"{attempt_dir}/repair_evidence.md"]
        why_now = "The previous observation reported failures."
    elif not workspace.resolve_path("package/SKILL.md").exists():
        objective = "Create package/SKILL.md as the capability bundle agent entrypoint."
        outputs = ["package/SKILL.md"]
        why_now = "The package entrypoint is required before bundle closure."
    elif not workspace.resolve_path("package/skillfoundry.bundle.json").exists():
        objective = "Create package/skillfoundry.bundle.json as the machine-readable bundle boundary."
        outputs = ["package/skillfoundry.bundle.json"]
        why_now = "The bundle manifest is required before final verification."
    else:
        objective = "Run final adaptive closure over the existing package artifacts."
        outputs = [f"{attempt_dir}/closure_evidence.md"]
        why_now = "The package entrypoint and bundle manifest both exist."
    return NextStepContract(
        job_id=config.job_id,
        iteration=iteration,
        current_state_ref=ADAPTIVE_CAPABILITY_STATE_REF,
        next_objective=objective,
        why_now=why_now,
        risk_if_too_large="Combining unrelated assets in one work unit can hide the failing boundary.",
        risk_if_too_small="A non-evidence-producing step does not reduce adaptive uncertainty.",
        allowed_scope=["package", attempt_dir],
        visible_refs=["skill_spec.yaml", "verification_spec.yaml", ADAPTIVE_CAPABILITY_STATE_REF],
        expected_outputs=outputs,
        exit_criteria=["Expected refs exist or an explicit failure is recorded."],
        stop_conditions=["Spec contradiction found.", "Path safety violation detected."],
        estimated_followups=["Observe artifacts and correct the capability state estimate."],
    )


def _build_product_repair_next_step_contract(
    workspace: JobWorkspace,
    *,
    config: AdaptiveGraphConfig,
    iteration: int,
    attempt_dir: str,
) -> NextStepContract | None:
    packet = _read_optional_product_repair_packet(workspace)
    if packet is None or not packet.repair_required:
        return None
    repair_item_ids = [item.finding_id for item in packet.repair_items]
    if not repair_item_ids:
        repair_item_ids = [finding.finding_id for finding in packet.findings]
    repair_summary = _short_repair_summary(repair_item_ids)
    return NextStepContract(
        job_id=config.job_id,
        iteration=iteration,
        current_state_ref=ADAPTIVE_CAPABILITY_STATE_REF,
        next_objective=f"Repair product-grade findings: {repair_summary}.",
        why_now="ProductGradeGate produced a failing repair packet for the latest work-unit observation.",
        risk_if_too_large="Fixing unrelated package surfaces can hide which product-grade finding was actually repaired.",
        risk_if_too_small="Changing only documentation or claims may leave ProductGradeGate findings unresolved.",
        allowed_scope=["package", "qa", attempt_dir],
        visible_refs=[
            "skill_spec.yaml",
            "verification_spec.yaml",
            ADAPTIVE_CAPABILITY_STATE_REF,
            PRODUCT_GRADE_REPORT_REF,
            PRODUCT_REPAIR_PACKET_REF,
        ],
        expected_outputs=[
            "package",
            PRODUCT_GRADE_REPORT_REF,
            PRODUCT_REPAIR_PACKET_REF,
        ],
        exit_criteria=[
            "ProductGradeGate is rerun after the work unit.",
            "qa/product_grade_report.json reports product_grade=true.",
            "qa/product_repair_packet.json reports repair_required=false.",
        ],
        stop_conditions=[
            "Repair requires changing frozen user requirements.",
            "Repair would need access outside the allowed package or qa refs.",
        ],
        estimated_followups=["Observe ProductGradeGate evidence and correct the adaptive state estimate."],
        metadata={
            "product_grade_report_ref": PRODUCT_GRADE_REPORT_REF,
            "product_repair_packet_ref": PRODUCT_REPAIR_PACKET_REF,
            "product_repair_item_ids": repair_item_ids[:20],
            "product_required_tests": packet.required_tests[:20],
        },
    )


def _read_optional_product_repair_packet(workspace: JobWorkspace) -> ProductRepairPacket | None:
    path = _optional_workspace_path(workspace, PRODUCT_REPAIR_PACKET_REF)
    if not path.exists():
        return None
    try:
        return ProductRepairPacket.read_json_file(path)
    except Exception:
        return None


def _short_repair_summary(repair_item_ids: list[str]) -> str:
    if not repair_item_ids:
        return "product repair packet has no item ids"
    summary = ", ".join(repair_item_ids[:4])
    if len(repair_item_ids) > 4:
        summary += f", and {len(repair_item_ids) - 4} more"
    return summary


def _product_acceptance_matrix_exists(workspace: JobWorkspace) -> bool:
    return _optional_workspace_path(workspace, PRODUCT_ACCEPTANCE_MATRIX_REF).is_file()


def _optional_workspace_path(workspace: JobWorkspace, ref: str) -> Path:
    safe = validate_relative_path(ref)
    return workspace.root.joinpath(*safe.parts)


def _decide_after_observation(
    workspace: JobWorkspace,
    *,
    state: SkillFoundryV2State,
    observation: ObservationReport,
    config: AdaptiveGraphConfig,
) -> tuple[str, str, int, str]:
    contextforge = state.get("contextforge", {})
    assert isinstance(contextforge, dict)
    previous_failure_count = int(contextforge.get("adaptive_failure_count", 0))
    verification_status = contextforge.get("adaptive_latest_verification_status")
    failed = bool(observation.failures) or verification_status == "failed"
    if failed:
        failure_count = previous_failure_count + 1
        if failure_count >= config.repeated_failure_threshold:
            return "review_required", "require_reviewer", failure_count, V2Status.HUMAN_REVIEW_REQUIRED.value
        return "repair", "repair", failure_count, V2Status.REPAIR_PLANNED.value

    failure_count = 0
    has_skill = workspace.resolve_path("package/SKILL.md").exists()
    has_manifest = workspace.resolve_path(BUNDLE_MANIFEST_REF).exists()
    bundle_verification_passed = contextforge.get("adaptive_bundle_verification_passed") is True
    manifest_status = contextforge.get("adaptive_bundle_manifest_status")
    if has_skill and has_manifest and manifest_status == "valid" and bundle_verification_passed:
        return "closure", "close", failure_count, V2Status.REPORT_EMITTED.value
    return "continue", "continue", failure_count, V2Status.RUNNING.value


def _dedupe_refs(refs: list[str]) -> list[str]:
    result: list[str] = []
    for ref in refs:
        if ref and ref not in result:
            result.append(ref)
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _known_good(workspace: JobWorkspace, route: str) -> list[str]:
    result = ["Adaptive artifacts are recorded as refs."]
    if workspace.resolve_path("package/SKILL.md").exists():
        result.append("package/SKILL.md exists.")
    if workspace.resolve_path("package/skillfoundry.bundle.json").exists():
        result.append("package/skillfoundry.bundle.json exists.")
    product_report_path = _optional_workspace_path(workspace, PRODUCT_GRADE_REPORT_REF)
    if product_report_path.exists():
        result.append("ProductGradeGate report exists.")
    if route == "closure":
        result.append("Independent bundle verification passed.")
    return result


def _current_risks(route: str) -> list[str]:
    if route == "review_required":
        return ["Repeated failures require independent review."]
    if route == "repair":
        return ["A failed work unit needs a smaller repair contract."]
    if route == "continue":
        return ["The bundle is not ready for closure."]
    return []


def _next_best_step(route: str) -> str:
    if route == "review_required":
        return "Request reviewer judgment before continuing."
    if route == "repair":
        return "Generate a focused repair next-step contract."
    if route == "continue":
        return "Generate the next bounded work unit."
    if route == "closure":
        return "Proceed to final verifier integration."
    return "Stop adaptive execution."


def _confidence(route: str) -> float:
    if route == "closure":
        return 0.85
    if route == "review_required":
        return 0.35
    if route == "repair":
        return 0.45
    return 0.6


def _decision_rationale(route: str) -> str:
    if route == "closure":
        return "Required package entrypoint and bundle manifest exist with passing independent BundleVerifier evidence."
    if route == "review_required":
        return "Repeated work-unit failures exceeded the adaptive failure threshold."
    if route == "repair":
        return "The latest observation failed and the failure threshold has not been exhausted."
    return "The latest observation passed but additional bundle assets are still missing."
