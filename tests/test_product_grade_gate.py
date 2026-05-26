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


def reference_skill_spec() -> SkillSpec:
    return SkillSpec(
        skill_id="eda-reference-skill",
        title="EDA reference skill",
        description=(
            "Convert official PDF documentation into a structured domain reference database "
            "with citation/source mapping and retrieval smoke tests."
        ),
        trigger_scenarios=["The user needs domain help grounded in official manuals."],
        non_trigger_scenarios=["Ungrounded general advice."],
        required_inputs=["Official PDF manuals", "conversion logs", "domain examples"],
        expected_outputs=["Chunked Markdown references, indexed database assets, and factual QA samples."],
        constraints=["Every generated fact must map back to source documents."],
        acceptance_criteria=["Retrieval smoke tests and random factual citation checks pass."],
        reference_materials=["Official PDF documentation"],
        security_notes=["Do not invent unsupported domain facts."],
    )


def service_skill_spec() -> SkillSpec:
    return SkillSpec(
        skill_id="service-bundle-skill",
        title="Service bundle skill",
        description="Package a long-running local server daemon with startup, healthcheck, and shutdown docs.",
        trigger_scenarios=["The user needs a local service bundle."],
        non_trigger_scenarios=["Prompt-only planning."],
        required_inputs=["Service config", "environment variables"],
        expected_outputs=["Service bundle package and lifecycle docs."],
        constraints=["Document background process ownership."],
        acceptance_criteria=["Startup, healthcheck, and shutdown docs exist."],
        reference_materials=[],
        security_notes=["Do not leak environment secrets."],
    )


def make_runtime_workspace(tmp_path: Path, job_id: str = "product-gate-001"):
    workspace = initialize_job_workspace(tmp_path / "runs", job_id, skill_spec=runtime_skill_spec())
    ProductContractCompiler().compile(workspace)
    workspace.resolve_path("package/src").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("package/tests").mkdir(parents=True, exist_ok=True)
    return workspace


def make_compiled_workspace(tmp_path: Path, skill_spec: SkillSpec, job_id: str):
    workspace = initialize_job_workspace(tmp_path / "runs", job_id, skill_spec=skill_spec)
    ProductContractCompiler().compile(workspace)
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


def test_product_gate_fails_reference_skill_without_reference_evidence(tmp_path: Path):
    workspace = make_compiled_workspace(tmp_path, reference_skill_spec(), "product-gate-reference-missing")

    report = ProductGradeGate().evaluate(workspace)

    finding_ids = {finding.finding_id for finding in report.findings}
    assert report.product_grade is False
    assert "P1-reference-source-inventory-missing" in finding_ids
    assert "P1-reference-conversion-provenance-missing" in finding_ids
    assert "P1-reference-citation-mapping-missing" in finding_ids
    assert "PG-REFERENCE-SOURCE-INVENTORY" in report.checked_item_ids
    repair = ProductRepairPacket.read_json_file(workspace.resolve_path(PRODUCT_REPAIR_PACKET_REF, must_exist=True))
    assert "source inventory exists" in repair.required_tests


def test_product_gate_passes_reference_skill_with_reference_evidence(tmp_path: Path):
    workspace = make_compiled_workspace(tmp_path, reference_skill_spec(), "product-gate-reference-pass")
    workspace.resolve_path("package/references").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("package/references/source_inventory.json").write_text(
        """
{
  "source_inventory": [
    {"source_document": "official-layout-manual.pdf", "sha256": "0000"}
  ]
}
""",
        encoding="utf-8",
    )
    workspace.resolve_path("package/references/conversion_provenance.md").write_text(
        """
# Conversion Provenance

- conversion command: pdf-extract official-layout-manual.pdf
- tool version: pdf-extract 1.0
- failed-source handling: fail closed and record the source ref.
""",
        encoding="utf-8",
    )
    workspace.resolve_path("package/references/citation_mapping.json").write_text(
        """
{
  "citation_mapping": [
    {"chunk_id": "layout-001", "source_ref": "official-layout-manual.pdf#page=1"}
  ]
}
""",
        encoding="utf-8",
    )
    workspace.resolve_path("package/tests/retrieval_smoke.md").write_text(
        "Retrieval smoke test: factual QA answer includes citation check for chunk_id layout-001.",
        encoding="utf-8",
    )

    report = ProductGradeGate().evaluate(workspace)

    assert report.product_grade is True
    assert {finding.finding_id for finding in report.findings} == set()
    assert "PG-REFERENCE-CITATION-MAPPING" in report.checked_item_ids


def test_product_gate_fails_service_bundle_without_lifecycle_evidence(tmp_path: Path):
    workspace = make_compiled_workspace(tmp_path, service_skill_spec(), "product-gate-service-missing")

    report = ProductGradeGate().evaluate(workspace)

    finding_ids = {finding.finding_id for finding in report.findings}
    assert report.product_grade is False
    assert "P1-service-startup-contract-missing" in finding_ids
    assert "P1-service-healthcheck-missing" in finding_ids
    assert "P1-service-shutdown-boundary-missing" in finding_ids
    assert "PG-SERVICE-HEALTHCHECK" in report.checked_item_ids


def test_product_gate_passes_service_bundle_with_lifecycle_evidence(tmp_path: Path):
    workspace = make_compiled_workspace(tmp_path, service_skill_spec(), "product-gate-service-pass")
    workspace.resolve_path("package/docs").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("package/docs/service.md").write_text(
        """
# Service Runtime

- startup command: python -m skill_service --port 8765
- required environment: SKILL_SERVICE_HOME
- port: 8765
- healthcheck: curl http://127.0.0.1:8765/health
- smoke test: service readiness returns ok
- shutdown: send SIGTERM or run the stop command
- cleanup: remove temporary files owned by this background process
- process boundary: the user owns local startup and shutdown.
""",
        encoding="utf-8",
    )

    report = ProductGradeGate().evaluate(workspace)

    assert report.product_grade is True
    assert {finding.finding_id for finding in report.findings} == set()
    assert "PG-SERVICE-SHUTDOWN-BOUNDARY" in report.checked_item_ids


def test_product_gate_fails_closed_when_matrix_is_missing(tmp_path: Path):
    workspace = initialize_job_workspace(tmp_path / "runs", "product-gate-missing-matrix")

    report = ProductGradeGate().evaluate(workspace)

    assert report.product_grade is False
    assert report.findings[0].finding_id == "P0-product-acceptance-matrix-missing"
    loaded = ProductGradeReport.read_json_file(workspace.resolve_path(PRODUCT_GRADE_REPORT_REF, must_exist=True))
    assert loaded.to_dict() == report.to_dict()
