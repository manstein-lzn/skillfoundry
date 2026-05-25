import sys
from pathlib import Path

from skillfoundry import (
    PRODUCT_GRADE_REPORT_REF,
    PRODUCT_REPAIR_PACKET_REF,
    PRODUCT_RUNTIME_CHECK_PLAN_REF,
    PRODUCT_RUNTIME_CHECK_RESULT_REF,
    ProductAcceptanceMatrix,
    ProductContractCompiler,
    ProductGradeGate,
    ProductGradeReport,
    ProductRepairPacket,
    RuntimeCheckCommand,
    RuntimeCheckPlan,
    SkillSpec,
    initialize_job_workspace,
)


def runtime_skill_spec() -> SkillSpec:
    return SkillSpec(
        skill_id="runtime-local-safety",
        title="Runtime local safety skill",
        description=(
            "Build a Codex skill with a Rust runtime helper for JSON manifest input, compact notes, "
            "and local wiki write plans."
        ),
        trigger_scenarios=["The user provides authorized compact evidence for local Markdown wiki notes."],
        non_trigger_scenarios=["Do not scan raw chat or whole computers."],
        required_inputs=["JSON manifest", "compact notes", "wiki root", "write plan"],
        expected_outputs=["Candidate notes and conflict proposals without overwrite."],
        constraints=["No overwrite; reject unsafe paths; return conflict proposals."],
        acceptance_criteria=["Runtime fixtures cover duplicate path and duplicate title conflicts."],
        reference_materials=[],
        security_notes=["Only process explicitly provided files."],
    )


def make_runtime_workspace(tmp_path: Path, job_id: str = "product-gate-001"):
    workspace = initialize_job_workspace(tmp_path / "runs", job_id, skill_spec=runtime_skill_spec())
    ProductContractCompiler().compile(workspace)
    workspace.resolve_path("package/src").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("package/tests").mkdir(parents=True, exist_ok=True)
    return workspace


def write_passing_runtime_matrix_plan(workspace) -> None:
    workspace.resolve_path("package/scripts").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("package/scripts/product_matrix_check.py").write_text(
        """
import sys

print(sys.argv[1])
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    matrix = ProductAcceptanceMatrix.read_json_file(workspace.resolve_path("product_contract/product_acceptance_matrix.json"))
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


def test_product_gate_fails_runtime_skill_without_duplicate_and_parser_evidence(tmp_path: Path):
    workspace = make_runtime_workspace(tmp_path)
    workspace.resolve_path("package/src/lib.rs").write_text(
        """
pub fn validate_write_plan(input: &str) -> bool {
    input.contains("\"target_path\"") && input.contains("\"title\"")
}
""",
        encoding="utf-8",
    )

    report = ProductGradeGate().evaluate(workspace)

    finding_ids = {finding.finding_id for finding in report.findings}
    assert report.product_grade is False
    assert "P0-runtime-matrix-checks-failed" in finding_ids
    assert "P0-runtime-same-plan-conflict-coverage-missing" in finding_ids
    assert "P1-structured-parser-not-typed" in finding_ids
    assert workspace.resolve_path(PRODUCT_RUNTIME_CHECK_RESULT_REF, must_exist=True).is_file()
    assert workspace.resolve_path(PRODUCT_GRADE_REPORT_REF, must_exist=True).is_file()
    repair = ProductRepairPacket.read_json_file(workspace.resolve_path(PRODUCT_REPAIR_PACKET_REF, must_exist=True))
    assert repair.repair_required is True
    assert "duplicate path fixture" in repair.required_tests


def test_product_gate_passes_mvp_when_duplicate_and_parser_evidence_exists(tmp_path: Path):
    workspace = make_runtime_workspace(tmp_path, job_id="product-gate-pass")
    write_passing_runtime_matrix_plan(workspace)
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

    report = ProductGradeGate().evaluate(workspace)

    assert report.product_grade is True
    assert {finding.finding_id for finding in report.findings} == set()
    assert "PG-RUNTIME-SAME-PLAN-DUPLICATE-PATH" in report.checked_item_ids
    assert "PG-STRUCTURED-TYPED-PARSER" in report.checked_item_ids


def test_product_gate_fails_closed_when_matrix_is_missing(tmp_path: Path):
    workspace = initialize_job_workspace(tmp_path / "runs", "product-gate-missing-matrix")

    report = ProductGradeGate().evaluate(workspace)

    assert report.product_grade is False
    assert report.findings[0].finding_id == "P0-product-acceptance-matrix-missing"
    loaded = ProductGradeReport.read_json_file(workspace.resolve_path(PRODUCT_GRADE_REPORT_REF, must_exist=True))
    assert loaded.to_dict() == report.to_dict()
