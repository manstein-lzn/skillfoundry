from __future__ import annotations

import json
from pathlib import Path

from forgeunit_skillfoundry import (
    ADAPTIVE_GRAPH_SCHEMA_VERSION,
    AdaptiveGraphConfig,
    AdaptiveWorkUnitResult,
    run_adaptive_graph,
)
from skillfoundry.adaptive_workspace import (
    ADAPTIVE_CAPABILITY_STATE_REF,
    ADAPTIVE_DECISION_LEDGER_REF,
    adaptive_contract_ref,
    adaptive_correction_ref,
    adaptive_observation_ref,
    read_decision_ledger,
    read_next_step_contract,
    read_observation_report,
    read_state_correction,
)
from skillfoundry.graph_v2 import V2Status, validate_v2_graph_state
from skillfoundry.workspace import JobWorkspace, initialize_job_workspace


def test_adaptive_graph_happy_path_reaches_closure_in_two_iterations(tmp_path: Path) -> None:
    config = AdaptiveGraphConfig(runs_root=tmp_path / "runs", job_id="adaptive-happy-001")

    result = run_adaptive_graph(config)

    workspace = JobWorkspace(root=result.workspace_root, job_id=result.job_id)
    state = result.state
    serialized = json.dumps(state)
    validate_v2_graph_state(state)
    assert state["status"] == V2Status.REPORT_EMITTED.value
    assert state["contextforge"]["adaptive_graph_schema_version"] == ADAPTIVE_GRAPH_SCHEMA_VERSION
    assert state["contextforge"]["adaptive_latest_iteration"] == 2
    assert state["contextforge"]["adaptive_latest_route"] == "closure"
    assert state["contextforge"]["adaptive_latest_decision"] == "close"
    assert state["refs"]["adaptive_state"] == ADAPTIVE_CAPABILITY_STATE_REF
    assert state["refs"]["decision_ledger"] == ADAPTIVE_DECISION_LEDGER_REF
    assert state["refs"]["latest_next_step_contract"] == adaptive_contract_ref(2)
    assert state["refs"]["latest_observation_report"] == adaptive_observation_ref(2)
    assert state["refs"]["latest_state_correction"] == adaptive_correction_ref(2)
    assert workspace.resolve_path("package/SKILL.md", must_exist=True).is_file()
    assert workspace.resolve_path("package/skillfoundry.bundle.json", must_exist=True).is_file()

    first_contract = read_next_step_contract(workspace, 1)
    second_contract = read_next_step_contract(workspace, 2)
    assert first_contract.expected_outputs == ["package/SKILL.md"]
    assert second_contract.expected_outputs == ["package/skillfoundry.bundle.json"]
    assert read_observation_report(workspace, 2).produced_artifacts == ["package/skillfoundry.bundle.json"]
    assert read_state_correction(workspace, 2).next_route == "closure"
    ledger = read_decision_ledger(workspace)
    assert [decision.decision_id for decision in ledger.decisions] == [
        "adaptive-decision-001",
        "adaptive-decision-002",
    ]
    assert "raw_prompt" not in serialized
    assert "raw_transcript" not in serialized
    assert "package_content" not in serialized


def test_adaptive_graph_missing_manifest_generates_manifest_contract(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "adaptive-manifest-001")
    workspace.resolve_path("package/SKILL.md").write_text("# Existing Skill\n", encoding="utf-8")
    config = AdaptiveGraphConfig(runs_root=tmp_path / "runs", job_id=workspace.job_id, max_iterations=1)

    result = run_adaptive_graph(config)

    contract = read_next_step_contract(workspace, 1)
    assert contract.expected_outputs == ["package/skillfoundry.bundle.json"]
    assert result.state["contextforge"]["adaptive_latest_iteration"] == 1
    assert workspace.resolve_path("package/skillfoundry.bundle.json", must_exist=True).is_file()


def test_adaptive_graph_failed_verification_routes_to_repair(tmp_path: Path) -> None:
    calls = 0

    def fail_once_worker(workspace: JobWorkspace, contract) -> AdaptiveWorkUnitResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            return AdaptiveWorkUnitResult(
                failures=["fixture verifier failed"],
                worker_claims=["failed intentionally"],
                verification_status="failed",
            )
        path = workspace.resolve_path("package/SKILL.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Repaired Skill\n", encoding="utf-8")
        return AdaptiveWorkUnitResult(
            produced_artifacts=["package/SKILL.md"],
            changed_refs=["package/SKILL.md"],
            worker_claims=["repair wrote package/SKILL.md"],
            verifier_evidence=["package/SKILL.md"],
            verification_status="passed",
        )

    config = AdaptiveGraphConfig(
        runs_root=tmp_path / "runs",
        job_id="adaptive-repair-001",
        max_iterations=2,
        repeated_failure_threshold=3,
    )

    result = run_adaptive_graph(config, worker=fail_once_worker)

    workspace = JobWorkspace(root=result.workspace_root, job_id=result.job_id)
    assert calls == 2
    assert read_state_correction(workspace, 1).next_route == "repair"
    assert read_next_step_contract(workspace, 2).expected_outputs == ["adaptive/attempts/002/repair_evidence.md"]
    assert result.state["contextforge"]["adaptive_latest_route"] == "continue"
    assert result.state["contextforge"]["adaptive_failure_count"] == 0


def test_adaptive_graph_repeated_failure_routes_to_review_required(tmp_path: Path) -> None:
    def always_fail_worker(workspace: JobWorkspace, contract) -> AdaptiveWorkUnitResult:
        return AdaptiveWorkUnitResult(
            failures=["deterministic failure"],
            worker_claims=["failed intentionally"],
            verification_status="failed",
        )

    config = AdaptiveGraphConfig(
        runs_root=tmp_path / "runs",
        job_id="adaptive-review-001",
        max_iterations=4,
        repeated_failure_threshold=2,
    )

    result = run_adaptive_graph(config, worker=always_fail_worker)

    workspace = JobWorkspace(root=result.workspace_root, job_id=result.job_id)
    state = result.state
    serialized = json.dumps(state)
    validate_v2_graph_state(state)
    assert state["status"] == V2Status.HUMAN_REVIEW_REQUIRED.value
    assert state["human_review_required"] is True
    assert state["contextforge"]["adaptive_latest_iteration"] == 2
    assert state["contextforge"]["adaptive_latest_route"] == "review_required"
    assert state["contextforge"]["adaptive_latest_decision"] == "require_reviewer"
    assert read_state_correction(workspace, 2).next_route == "review_required"
    assert "deterministic failure" in read_observation_report(workspace, 2).failures
    assert "raw_prompt" not in serialized
    assert "raw_transcript" not in serialized


def test_adaptive_graph_does_not_require_live_codex_by_default(tmp_path: Path) -> None:
    config = AdaptiveGraphConfig(runs_root=tmp_path / "runs", job_id="adaptive-offline-001")

    result = run_adaptive_graph(config)

    serialized = json.dumps(result.state)
    assert "codex" not in serialized.lower()
    assert result.state["contextforge"]["worker_self_report_is_not_acceptance"] is True
