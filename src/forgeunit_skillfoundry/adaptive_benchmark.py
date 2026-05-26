"""Deterministic benchmark scenarios for adaptive RoutePlan steering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
from typing import Literal

from skillfoundry.adaptive_workspace import read_next_step_contract, read_route_plan, read_state_correction
from skillfoundry.bundle import BUNDLE_MANIFEST_REF
from skillfoundry.graph_v2 import V2Status
from skillfoundry.product_contract import PRODUCT_ACCEPTANCE_MATRIX_REF, PRODUCT_REPAIR_PACKET_REF, ProductAcceptanceMatrix
from skillfoundry.product_contract_compiler import ProductContractCompiler
from skillfoundry.product_runtime_checks import PRODUCT_RUNTIME_CHECK_PLAN_REF, RuntimeCheckCommand, RuntimeCheckPlan
from skillfoundry.schema import SkillSpec
from skillfoundry.workspace import JobWorkspace, initialize_job_workspace

from .adaptive_graph import (
    AdaptiveGraphConfig,
    AdaptiveGraphResult,
    AdaptiveWorkUnitResult,
    AdaptiveWorkUnit,
    run_adaptive_graph,
)


BenchmarkScenarioName = Literal[
    "false_success",
    "recommendation_pivot",
    "new_unknown",
    "product_grade_repair",
    "repeated_failure",
]
BenchmarkMode = Literal["baseline", "upgraded"]


@dataclass(frozen=True)
class AdaptiveBenchmarkScenario:
    name: BenchmarkScenarioName
    max_iterations: int
    repeated_failure_threshold: int = 2
    prepare_workspace: Callable[[Path, str], JobWorkspace] | None = None
    worker_factory: Callable[[BenchmarkMode], AdaptiveWorkUnit] = field(default=lambda _mode: _noop_worker)


@dataclass(frozen=True)
class AdaptiveBenchmarkMetrics:
    scenario: str
    mode: BenchmarkMode
    job_id: str
    status: str
    latest_route: str
    latest_decision: str
    iterations: int
    repair_loops: int
    route_plan_revisions: int
    route_plan_refs_exposed: int
    recommendation_captured: bool
    unknown_captured: bool
    worker_raw_leaked_to_state: bool
    product_repair_packet_prioritized: bool
    route_aware_product_repair: bool
    review_boundary_reached: bool
    verified_or_closed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "mode": self.mode,
            "job_id": self.job_id,
            "status": self.status,
            "latest_route": self.latest_route,
            "latest_decision": self.latest_decision,
            "iterations": self.iterations,
            "repair_loops": self.repair_loops,
            "route_plan_revisions": self.route_plan_revisions,
            "route_plan_refs_exposed": self.route_plan_refs_exposed,
            "recommendation_captured": self.recommendation_captured,
            "unknown_captured": self.unknown_captured,
            "worker_raw_leaked_to_state": self.worker_raw_leaked_to_state,
            "product_repair_packet_prioritized": self.product_repair_packet_prioritized,
            "route_aware_product_repair": self.route_aware_product_repair,
            "review_boundary_reached": self.review_boundary_reached,
            "verified_or_closed": self.verified_or_closed,
        }


@dataclass(frozen=True)
class AdaptiveBenchmarkComparison:
    scenario: str
    baseline: AdaptiveBenchmarkMetrics
    upgraded: AdaptiveBenchmarkMetrics

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "baseline": self.baseline.to_dict(),
            "upgraded": self.upgraded.to_dict(),
        }


def run_adaptive_steering_benchmark(runs_root: Path) -> list[AdaptiveBenchmarkComparison]:
    """Run deterministic baseline/upgraded steering comparisons."""

    return [run_adaptive_steering_scenario(scenario, runs_root) for scenario in benchmark_scenarios()]


def run_adaptive_steering_scenario(
    scenario: AdaptiveBenchmarkScenario,
    runs_root: Path,
) -> AdaptiveBenchmarkComparison:
    baseline = _run_scenario_mode(scenario, runs_root, mode="baseline")
    upgraded = _run_scenario_mode(scenario, runs_root, mode="upgraded")
    return AdaptiveBenchmarkComparison(scenario=scenario.name, baseline=baseline, upgraded=upgraded)


def benchmark_scenarios() -> list[AdaptiveBenchmarkScenario]:
    return [
        AdaptiveBenchmarkScenario(
            name="false_success",
            max_iterations=2,
            repeated_failure_threshold=3,
            worker_factory=_false_success_worker,
        ),
        AdaptiveBenchmarkScenario(
            name="recommendation_pivot",
            max_iterations=2,
            repeated_failure_threshold=3,
            worker_factory=_recommendation_worker,
        ),
        AdaptiveBenchmarkScenario(
            name="new_unknown",
            max_iterations=2,
            repeated_failure_threshold=3,
            worker_factory=_new_unknown_worker,
        ),
        AdaptiveBenchmarkScenario(
            name="product_grade_repair",
            max_iterations=3,
            repeated_failure_threshold=3,
            prepare_workspace=_prepare_product_grade_workspace,
            worker_factory=_product_grade_worker,
        ),
        AdaptiveBenchmarkScenario(
            name="repeated_failure",
            max_iterations=4,
            repeated_failure_threshold=2,
            worker_factory=_repeated_failure_worker,
        ),
    ]


def benchmark_report(comparisons: list[AdaptiveBenchmarkComparison]) -> dict[str, object]:
    """Return a JSON-safe report for benchmark storage or inspection."""

    return {
        "schema_version": "forgeunit_skillfoundry.adaptive_steering_benchmark.v1",
        "comparison_axis": "baseline_no_route_plan_steering_vs_upgraded_route_plan_revision",
        "scenario_count": len(comparisons),
        "comparisons": [comparison.to_dict() for comparison in comparisons],
    }


def write_benchmark_report(path: Path, comparisons: list[AdaptiveBenchmarkComparison]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(benchmark_report(comparisons), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_scenario_mode(
    scenario: AdaptiveBenchmarkScenario,
    runs_root: Path,
    *,
    mode: BenchmarkMode,
) -> AdaptiveBenchmarkMetrics:
    job_id = f"benchmark-{scenario.name}-{mode}"
    if scenario.prepare_workspace is not None:
        scenario.prepare_workspace(runs_root, job_id)
    config = AdaptiveGraphConfig(
        runs_root=runs_root,
        job_id=job_id,
        max_iterations=scenario.max_iterations,
        repeated_failure_threshold=scenario.repeated_failure_threshold,
        route_plan_steering=mode == "upgraded",
    )
    result = run_adaptive_graph(config, worker=scenario.worker_factory(mode))
    workspace = JobWorkspace(root=result.workspace_root, job_id=result.job_id)
    return _collect_metrics(result, workspace, scenario=scenario.name, mode=mode)


def _collect_metrics(
    result: AdaptiveGraphResult,
    workspace: JobWorkspace,
    *,
    scenario: str,
    mode: BenchmarkMode,
) -> AdaptiveBenchmarkMetrics:
    state = result.state
    contextforge = state.get("contextforge", {})
    iterations = int(contextforge.get("adaptive_latest_iteration", 0)) if isinstance(contextforge, dict) else 0
    state_text = json.dumps(state, sort_keys=True)
    route_plan_revisions = 0
    route_plan_refs_exposed = 0
    recommendation_captured = False
    unknown_captured = False
    product_repair_packet_prioritized = False
    route_aware_product_repair = False
    repair_loops = 0
    for iteration in range(1, iterations + 1):
        try:
            correction = read_state_correction(workspace, iteration)
        except Exception:
            continue
        if correction.next_route == "repair":
            repair_loops += 1
        try:
            contract = read_next_step_contract(workspace, iteration)
        except Exception:
            contract = None
        if contract is not None:
            if contract.route_plan_ref is not None:
                route_plan_refs_exposed += 1
            if PRODUCT_REPAIR_PACKET_REF in contract.visible_refs and "product_gate:" in contract.next_objective:
                product_repair_packet_prioritized = True
                route_aware_product_repair = route_aware_product_repair or contract.route_plan_ref is not None
        try:
            route_plan = read_route_plan(workspace, iteration)
        except Exception:
            route_plan = None
        if route_plan is not None:
            route_plan_revisions += 1
            route_plan_text = "\n".join(
                [
                    *route_plan.phase_plan,
                    *route_plan.plan_b,
                    *route_plan.assumptions,
                    *route_plan.risk_register,
                    *route_plan.next_step_policy,
                ]
            )
            recommendation_captured = recommendation_captured or "BENCH_RECOMMENDATION_PIVOT" in route_plan_text
            unknown_captured = unknown_captured or "BENCH_NEW_UNKNOWN" in route_plan_text
    status = str(state.get("status", ""))
    latest_route = str(contextforge.get("adaptive_latest_route", "")) if isinstance(contextforge, dict) else ""
    latest_decision = str(contextforge.get("adaptive_latest_decision", "")) if isinstance(contextforge, dict) else ""
    return AdaptiveBenchmarkMetrics(
        scenario=scenario,
        mode=mode,
        job_id=result.job_id,
        status=status,
        latest_route=latest_route,
        latest_decision=latest_decision,
        iterations=iterations,
        repair_loops=repair_loops,
        route_plan_revisions=route_plan_revisions,
        route_plan_refs_exposed=route_plan_refs_exposed,
        recommendation_captured=recommendation_captured,
        unknown_captured=unknown_captured,
        worker_raw_leaked_to_state="BENCH_RAW_STATE_MARKER" in state_text,
        product_repair_packet_prioritized=product_repair_packet_prioritized,
        route_aware_product_repair=route_aware_product_repair,
        review_boundary_reached=bool(state.get("human_review_required")) or status == V2Status.HUMAN_REVIEW_REQUIRED.value,
        verified_or_closed=latest_route == "closure" and status == V2Status.REPORT_EMITTED.value,
    )


def _noop_worker(_workspace: JobWorkspace, _contract) -> AdaptiveWorkUnitResult:
    return AdaptiveWorkUnitResult(verification_status="not_run")


def _false_success_worker(_mode: BenchmarkMode) -> AdaptiveWorkUnit:
    def worker(workspace: JobWorkspace, _contract) -> AdaptiveWorkUnitResult:
        workspace.resolve_path("package/SKILL.md").write_text("# False Success\n", encoding="utf-8")
        workspace.resolve_path(BUNDLE_MANIFEST_REF).write_text(
            json.dumps(
                {
                    "schema_version": "skillfoundry.bundle.v1",
                    "bundle_id": "wrong-id",
                    "bundle_type": "prompt_only",
                    "entrypoint": "../SKILL.md",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return AdaptiveWorkUnitResult(
            produced_artifacts=["package/SKILL.md", BUNDLE_MANIFEST_REF],
            changed_refs=["package/SKILL.md", BUNDLE_MANIFEST_REF],
            worker_claims=["BENCH_RAW_STATE_MARKER worker claims success despite invalid manifest."],
            verifier_evidence=["package/SKILL.md", BUNDLE_MANIFEST_REF],
            verification_status="passed",
        )

    return worker


def _recommendation_worker(_mode: BenchmarkMode) -> AdaptiveWorkUnit:
    def worker(workspace: JobWorkspace, contract) -> AdaptiveWorkUnitResult:
        if "package/SKILL.md" in contract.expected_outputs:
            workspace.resolve_path("package/SKILL.md").write_text("# Recommendation Pivot\n", encoding="utf-8")
            return AdaptiveWorkUnitResult(
                produced_artifacts=["package/SKILL.md"],
                changed_refs=["package/SKILL.md"],
                worker_claims=["Wrote entrypoint."],
                verifier_evidence=["package/SKILL.md"],
                recommended_next_steps=["BENCH_RECOMMENDATION_PIVOT prioritize bundle manifest next."],
                verification_status="passed",
            )
        _write_valid_bundle_manifest(workspace)
        return AdaptiveWorkUnitResult(
            produced_artifacts=[BUNDLE_MANIFEST_REF],
            changed_refs=[BUNDLE_MANIFEST_REF],
            worker_claims=["Wrote manifest."],
            verifier_evidence=[BUNDLE_MANIFEST_REF],
            verification_status="passed",
        )

    return worker


def _new_unknown_worker(_mode: BenchmarkMode) -> AdaptiveWorkUnit:
    def worker(workspace: JobWorkspace, contract) -> AdaptiveWorkUnitResult:
        if "package/SKILL.md" in contract.expected_outputs:
            workspace.resolve_path("package/SKILL.md").write_text("# New Unknown\n", encoding="utf-8")
            return AdaptiveWorkUnitResult(
                produced_artifacts=["package/SKILL.md"],
                changed_refs=["package/SKILL.md"],
                worker_claims=["Wrote entrypoint."],
                verifier_evidence=["package/SKILL.md"],
                new_unknowns=["BENCH_NEW_UNKNOWN runtime profile has unresolved local-file safety boundary."],
                verification_status="passed",
            )
        _write_valid_bundle_manifest(workspace)
        return AdaptiveWorkUnitResult(
            produced_artifacts=[BUNDLE_MANIFEST_REF],
            changed_refs=[BUNDLE_MANIFEST_REF],
            worker_claims=["Wrote manifest."],
            verifier_evidence=[BUNDLE_MANIFEST_REF],
            verification_status="passed",
        )

    return worker


def _product_grade_worker(mode: BenchmarkMode) -> AdaptiveWorkUnit:
    def worker(workspace: JobWorkspace, contract) -> AdaptiveWorkUnitResult:
        if contract.route_plan_ref is not None and PRODUCT_REPAIR_PACKET_REF in contract.visible_refs:
            _write_product_runtime_repair_evidence(workspace)
            return AdaptiveWorkUnitResult(
                produced_artifacts=[
                    "package/src/lib.rs",
                    "package/tests/helper_contract.rs",
                    PRODUCT_RUNTIME_CHECK_PLAN_REF,
                ],
                changed_refs=[
                    "package/src/lib.rs",
                    "package/tests/helper_contract.rs",
                    PRODUCT_RUNTIME_CHECK_PLAN_REF,
                ],
                commands_run=[f"{sys.executable} package/scripts/product_matrix_check.py PG-RUNTIME-CLI-OK-EXIT-CODE"],
                tests_run=["ProductGradeGate runtime matrix checks"],
                worker_claims=["Repaired product-grade runtime helper evidence."],
                verifier_evidence=[PRODUCT_RUNTIME_CHECK_PLAN_REF, "package/src/lib.rs", "package/tests/helper_contract.rs"],
                verification_status="passed",
            )
        return AdaptiveWorkUnitResult(
            produced_artifacts=[f"adaptive/attempts/{contract.iteration:03d}/closure_evidence.md"],
            changed_refs=[f"adaptive/attempts/{contract.iteration:03d}/closure_evidence.md"],
            worker_claims=["Closure attempt without route-plan repair context."],
            verifier_evidence=[f"adaptive/attempts/{contract.iteration:03d}/closure_evidence.md"],
            verification_status="passed",
        )

    return worker


def _repeated_failure_worker(_mode: BenchmarkMode) -> AdaptiveWorkUnit:
    def worker(_workspace: JobWorkspace, _contract) -> AdaptiveWorkUnitResult:
        return AdaptiveWorkUnitResult(
            failures=["deterministic benchmark failure"],
            worker_claims=["failed intentionally"],
            verification_status="failed",
        )

    return worker


def _prepare_product_grade_workspace(runs_root: Path, job_id: str) -> JobWorkspace:
    workspace = initialize_job_workspace(runs_root, job_id, skill_spec=_product_runtime_skill_spec())
    ProductContractCompiler().compile(workspace)
    workspace.resolve_path("package/SKILL.md").write_text("# Adaptive Product Skill\n", encoding="utf-8")
    _write_valid_bundle_manifest(workspace)
    return workspace


def _product_runtime_skill_spec() -> SkillSpec:
    return SkillSpec(
        skill_id="adaptive-product-runtime",
        title="Adaptive product runtime skill",
        description=(
            "Build a Codex skill with a Rust runtime helper that validates JSON write plans, "
            "rejects duplicate target paths and duplicate titles, and emits local file conflict proposals."
        ),
        trigger_scenarios=["The user provides a JSON manifest and asks for local Markdown write proposals."],
        non_trigger_scenarios=["Do not scan raw chat or unauthorized local files."],
        required_inputs=["JSON manifest", "write plan", "wiki root"],
        expected_outputs=["Conflict proposals without overwriting files."],
        constraints=["No overwrite; reject unsafe paths; validate structured JSON."],
        acceptance_criteria=["Runtime matrix checks cover duplicate path and duplicate title conflicts."],
        reference_materials=[],
        security_notes=["Only use explicitly provided files."],
    )


def _write_valid_bundle_manifest(workspace: JobWorkspace) -> None:
    workspace.resolve_path(BUNDLE_MANIFEST_REF).write_text(
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


def _write_product_runtime_repair_evidence(workspace: JobWorkspace) -> None:
    workspace.resolve_path("package/src").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("package/tests").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("package/scripts").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("package/src/lib.rs").write_text(
        """
use serde::Deserialize;
use serde_json;

#[derive(Deserialize)]
struct WritePlanItem { target_path: String, title: String }

pub fn validate_write_plan(input: &str) -> Result<(), String> {
    let plan: Vec<WritePlanItem> = serde_json::from_str(input).map_err(|err| err.to_string())?;
    let mut paths = std::collections::BTreeSet::new();
    let mut titles = std::collections::BTreeSet::new();
    for item in plan {
        if !paths.insert(item.target_path) { return Err("duplicate target path".to_string()); }
        if !titles.insert(item.title) { return Err("duplicate title".to_string()); }
    }
    Ok(())
}
""",
        encoding="utf-8",
    )
    workspace.resolve_path("package/tests/helper_contract.rs").write_text(
        """
#[test]
fn rejects_same_plan_duplicate_path() {
    assert!("duplicate target path fixture covers write plan".contains("duplicate target path"));
}

#[test]
fn rejects_same_plan_duplicate_title() {
    assert!("duplicate title fixture covers write plan".contains("duplicate title"));
}
""",
        encoding="utf-8",
    )
    workspace.resolve_path("package/scripts/product_matrix_check.py").write_text(
        """
import sys

print(sys.argv[1])
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    matrix = ProductAcceptanceMatrix.read_json_file(workspace.resolve_path(PRODUCT_ACCEPTANCE_MATRIX_REF))
    runtime_item_ids = sorted(item.item_id for item in matrix.items if item.item_id.startswith("PG-RUNTIME-"))
    RuntimeCheckPlan(
        commands=[
            RuntimeCheckCommand(
                check_id=f"runtime-{index:02d}",
                item_id=item_id,
                command=[sys.executable, "scripts/product_matrix_check.py", item_id],
                expected_exit_code=0,
                cwd="package",
            )
            for index, item_id in enumerate(runtime_item_ids, start=1)
        ]
    ).write_json_file(workspace.resolve_path(PRODUCT_RUNTIME_CHECK_PLAN_REF))
