from __future__ import annotations

import json
from pathlib import Path

from forgeunit_skillfoundry import (
    AdaptiveGraphConfig,
    benchmark_report,
    benchmark_scenarios,
    run_adaptive_graph,
    run_adaptive_steering_benchmark,
    write_benchmark_report,
)
from skillfoundry.adaptive_workspace import read_next_step_contract, read_route_plan
from skillfoundry.workspace import JobWorkspace


def test_adaptive_config_can_disable_route_plan_steering_for_baseline(tmp_path: Path) -> None:
    config = AdaptiveGraphConfig(
        runs_root=tmp_path / "runs",
        job_id="adaptive-baseline-no-route-plan",
        max_iterations=1,
        route_plan_steering=False,
    )

    result = run_adaptive_graph(config)

    workspace = JobWorkspace(root=result.workspace_root, job_id=result.job_id)
    contract = read_next_step_contract(workspace, 1)
    serialized_state = json.dumps(result.state)
    assert contract.route_plan_ref is None
    assert "adaptive/route_plan_000.json" not in contract.visible_refs
    assert "latest_route_plan" not in result.state["refs"]
    assert "adaptive_current_route_plan_ref" not in result.state["contextforge"]
    assert "route_plan_ref" not in serialized_state


def test_adaptive_steering_benchmark_compares_expected_pressure_scenarios(tmp_path: Path) -> None:
    comparisons = run_adaptive_steering_benchmark(tmp_path / "runs")

    by_name = {comparison.scenario: comparison for comparison in comparisons}
    assert set(by_name) == {scenario.name for scenario in benchmark_scenarios()}

    recommendation = by_name["recommendation_pivot"]
    assert recommendation.baseline.recommendation_captured is False
    assert recommendation.upgraded.recommendation_captured is True
    assert recommendation.baseline.route_plan_refs_exposed == 0
    assert recommendation.upgraded.route_plan_refs_exposed == recommendation.upgraded.iterations

    unknown = by_name["new_unknown"]
    assert unknown.baseline.unknown_captured is False
    assert unknown.upgraded.unknown_captured is True
    assert unknown.upgraded.route_plan_revisions > unknown.baseline.route_plan_revisions

    product = by_name["product_grade_repair"]
    assert product.baseline.product_repair_packet_prioritized is True
    assert product.baseline.route_aware_product_repair is False
    assert product.upgraded.route_aware_product_repair is True
    assert product.upgraded.product_repair_packet_prioritized is True
    assert product.baseline.verified_or_closed is False
    assert product.upgraded.verified_or_closed is True
    assert product.upgraded.repair_loops == 1

    false_success = by_name["false_success"]
    assert false_success.baseline.verified_or_closed is False
    assert false_success.upgraded.verified_or_closed is False
    assert false_success.baseline.worker_raw_leaked_to_state is False
    assert false_success.upgraded.worker_raw_leaked_to_state is False

    repeated_failure = by_name["repeated_failure"]
    assert repeated_failure.baseline.review_boundary_reached is True
    assert repeated_failure.upgraded.review_boundary_reached is True
    assert repeated_failure.upgraded.route_plan_revisions > repeated_failure.baseline.route_plan_revisions


def test_adaptive_steering_benchmark_report_is_json_safe(tmp_path: Path) -> None:
    comparisons = run_adaptive_steering_benchmark(tmp_path / "runs")
    report = benchmark_report(comparisons)

    report_text = json.dumps(report, sort_keys=True)
    assert report["schema_version"] == "forgeunit_skillfoundry.adaptive_steering_benchmark.v1"
    assert report["scenario_count"] == 5
    assert "raw_prompt" not in report_text
    assert "raw_transcript" not in report_text

    report_path = tmp_path / "adaptive_steering_benchmark_report.json"
    write_benchmark_report(report_path, comparisons)
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted == report


def test_upgraded_route_plan_artifact_contains_advisory_signal_but_state_does_not(tmp_path: Path) -> None:
    comparisons = run_adaptive_steering_benchmark(tmp_path / "runs")
    recommendation = {comparison.scenario: comparison for comparison in comparisons}["recommendation_pivot"]
    workspace = JobWorkspace(
        root=tmp_path / "runs" / recommendation.upgraded.job_id,
        job_id=recommendation.upgraded.job_id,
    )

    route_plan = read_route_plan(workspace, 1)
    state_text = (workspace.root / "adaptive" / "route_plan_001.json").read_text(encoding="utf-8")
    assert "BENCH_RECOMMENDATION_PIVOT" in "\n".join(route_plan.next_step_policy + route_plan.phase_plan)
    assert "BENCH_RECOMMENDATION_PIVOT" in state_text
    assert recommendation.upgraded.worker_raw_leaked_to_state is False
