from __future__ import annotations

import json
from pathlib import Path
import sys

from forgeunit_skillfoundry import (
    ADAPTIVE_GRAPH_SCHEMA_VERSION,
    AdaptiveGraphConfig,
    AdaptiveWorkUnitResult,
    adaptive_work_unit_result_ref,
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
from skillfoundry.bundle import BUNDLE_MANIFEST_REF
from skillfoundry.bundle_verifier import BUNDLE_VERIFICATION_RESULT_REF, BundleVerificationResult
from skillfoundry.graph_v2 import V2Status, validate_v2_graph_state
from skillfoundry.product_contract import (
    PRODUCT_ACCEPTANCE_MATRIX_REF,
    PRODUCT_GRADE_REPORT_REF,
    PRODUCT_REPAIR_PACKET_REF,
    ProductAcceptanceMatrix,
    ProductGradeReport,
)
from skillfoundry.product_contract_compiler import ProductContractCompiler
from skillfoundry.product_runtime_checks import PRODUCT_RUNTIME_CHECK_PLAN_REF, RuntimeCheckCommand, RuntimeCheckPlan
from skillfoundry.schema import SkillSpec
from skillfoundry.workspace import JobWorkspace, initialize_job_workspace


def product_runtime_skill_spec() -> SkillSpec:
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


def write_valid_prompt_bundle(workspace: JobWorkspace) -> None:
    workspace.resolve_path("package/SKILL.md").write_text("# Adaptive Product Skill\n", encoding="utf-8")
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
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_product_runtime_repair_evidence(workspace: JobWorkspace) -> None:
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
    assert state["refs"]["latest_work_unit_result"] == adaptive_work_unit_result_ref(2)
    assert state["refs"]["latest_observation_report"] == adaptive_observation_ref(2)
    assert state["refs"]["latest_state_correction"] == adaptive_correction_ref(2)
    assert state["refs"]["bundle_verification_result"] == BUNDLE_VERIFICATION_RESULT_REF
    assert workspace.resolve_path("package/SKILL.md", must_exist=True).is_file()
    assert workspace.resolve_path("package/skillfoundry.bundle.json", must_exist=True).is_file()
    bundle_result = BundleVerificationResult.read_json_file(
        workspace.resolve_path(BUNDLE_VERIFICATION_RESULT_REF, must_exist=True)
    )
    assert bundle_result.passed is True
    assert bundle_result.manifest_status == "valid"

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
    assert "adaptive_last_worker_claims" not in serialized


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


def test_adaptive_graph_does_not_close_on_worker_self_reported_pass_with_invalid_manifest(tmp_path: Path) -> None:
    def invalid_manifest_worker(workspace: JobWorkspace, contract) -> AdaptiveWorkUnitResult:
        workspace.resolve_path("package/SKILL.md").write_text("# Invalid Manifest Fixture\n", encoding="utf-8")
        workspace.resolve_path(BUNDLE_MANIFEST_REF).write_text(
            json.dumps(
                {
                    "schema_version": "skillfoundry.bundle.v1",
                    "bundle_id": "bad",
                    "bundle_type": "prompt_only",
                    "entrypoint": "../SKILL.md",
                }
            ),
            encoding="utf-8",
        )
        return AdaptiveWorkUnitResult(
            produced_artifacts=["package/SKILL.md", BUNDLE_MANIFEST_REF],
            changed_refs=["package/SKILL.md", BUNDLE_MANIFEST_REF],
            worker_claims=["Worker claims verification passed, but this is not acceptance."],
            verifier_evidence=["package/SKILL.md", BUNDLE_MANIFEST_REF],
            verification_status="passed",
        )

    config = AdaptiveGraphConfig(
        runs_root=tmp_path / "runs",
        job_id="adaptive-invalid-manifest-001",
        max_iterations=1,
    )

    result = run_adaptive_graph(config, worker=invalid_manifest_worker)

    workspace = JobWorkspace(root=result.workspace_root, job_id=result.job_id)
    state = result.state
    bundle_result = BundleVerificationResult.read_json_file(
        workspace.resolve_path(BUNDLE_VERIFICATION_RESULT_REF, must_exist=True)
    )
    assert state["status"] != V2Status.REPORT_EMITTED.value
    assert state["contextforge"]["adaptive_latest_route"] == "repair"
    assert state["contextforge"]["adaptive_latest_verification_status"] == "failed"
    assert bundle_result.manifest_present is True
    assert bundle_result.manifest_status == "invalid"
    assert bundle_result.passed is False
    assert any("bundle_manifest_valid" in failure for failure in read_observation_report(workspace, 1).failures)


def test_adaptive_graph_routes_product_grade_failure_to_repair_contract(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(
        tmp_path / "runs",
        "adaptive-product-grade-001",
        skill_spec=product_runtime_skill_spec(),
    )
    ProductContractCompiler().compile(workspace)
    write_valid_prompt_bundle(workspace)
    seen_objectives: list[str] = []

    def product_repair_worker(workspace: JobWorkspace, contract) -> AdaptiveWorkUnitResult:
        seen_objectives.append(contract.next_objective)
        if PRODUCT_REPAIR_PACKET_REF in contract.visible_refs:
            write_product_runtime_repair_evidence(workspace)
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
                commands_run=["python package/scripts/product_matrix_check.py PG-RUNTIME-CLI-OK-EXIT-CODE"],
                tests_run=["ProductGradeGate runtime matrix checks"],
                worker_claims=["Repaired product-grade runtime helper evidence."],
                verifier_evidence=[PRODUCT_RUNTIME_CHECK_PLAN_REF, "package/src/lib.rs", "package/tests/helper_contract.rs"],
                verification_status="passed",
            )
        return AdaptiveWorkUnitResult(
            produced_artifacts=["adaptive/attempts/001/closure_evidence.md"],
            changed_refs=["adaptive/attempts/001/closure_evidence.md"],
            worker_claims=["Initial closure attempt before product gate observation."],
            verifier_evidence=["adaptive/attempts/001/closure_evidence.md"],
            verification_status="passed",
        )

    config = AdaptiveGraphConfig(
        runs_root=tmp_path / "runs",
        job_id=workspace.job_id,
        max_iterations=3,
        repeated_failure_threshold=3,
    )

    result = run_adaptive_graph(config, worker=product_repair_worker)

    state = result.state
    assert state["contextforge"]["adaptive_latest_iteration"] == 2
    assert state["contextforge"]["adaptive_latest_route"] == "closure"
    assert state["contextforge"]["adaptive_product_grade_passed"] is True
    assert state["refs"]["product_grade_report"] == PRODUCT_GRADE_REPORT_REF
    assert state["refs"]["product_repair_packet"] == PRODUCT_REPAIR_PACKET_REF
    first_observation = read_observation_report(workspace, 1)
    assert any("product_grade:P0-runtime-matrix-checks-failed" in failure for failure in first_observation.failures)
    second_contract = read_next_step_contract(workspace, 2)
    assert PRODUCT_REPAIR_PACKET_REF in second_contract.visible_refs
    assert "product_gate:P0-runtime-matrix-checks-failed" in second_contract.next_objective
    assert seen_objectives[1] == second_contract.next_objective
    product_report = ProductGradeReport.read_json_file(workspace.resolve_path(PRODUCT_GRADE_REPORT_REF, must_exist=True))
    assert product_report.product_grade is True
    assert read_state_correction(workspace, 1).next_route == "repair"
    assert read_state_correction(workspace, 2).next_route == "closure"


def test_adaptive_graph_state_keeps_worker_strings_in_artifacts_not_contextforge(tmp_path: Path) -> None:
    marker = "RAW_SECRET_PROMPT_MARKER"

    def marker_worker(workspace: JobWorkspace, contract) -> AdaptiveWorkUnitResult:
        workspace.resolve_path("package/SKILL.md").write_text("# Marker Fixture\n", encoding="utf-8")
        return AdaptiveWorkUnitResult(
            produced_artifacts=["package/SKILL.md"],
            changed_refs=["package/SKILL.md"],
            commands_run=[marker],
            tests_run=[marker],
            worker_claims=[marker],
            verifier_evidence=["package/SKILL.md"],
            recommended_next_steps=[marker],
            verification_status="passed",
        )

    config = AdaptiveGraphConfig(
        runs_root=tmp_path / "runs",
        job_id="adaptive-refsonly-001",
        max_iterations=1,
    )

    result = run_adaptive_graph(config, worker=marker_worker)

    workspace = JobWorkspace(root=result.workspace_root, job_id=result.job_id)
    serialized_state = json.dumps(result.state)
    assert marker not in serialized_state
    assert "adaptive_last_worker_claims" not in serialized_state
    assert result.state["refs"]["latest_work_unit_result"] == adaptive_work_unit_result_ref(1)
    assert marker in workspace.resolve_path(adaptive_work_unit_result_ref(1), must_exist=True).read_text(
        encoding="utf-8"
    )
    assert marker in read_observation_report(workspace, 1).worker_claims


def test_adaptive_graph_does_not_require_live_codex_by_default(tmp_path: Path) -> None:
    config = AdaptiveGraphConfig(runs_root=tmp_path / "runs", job_id="adaptive-offline-001")

    result = run_adaptive_graph(config)

    serialized = json.dumps(result.state)
    assert "codex" not in serialized.lower()
    assert result.state["contextforge"]["worker_self_report_is_not_acceptance"] is True
