import json
from pathlib import Path

import pytest

from skillfoundry import (
    PRODUCT_ACCEPTANCE_MATRIX_REF,
    PRODUCT_GRADE_REPORT_REF,
    PRODUCT_REPAIR_PACKET_REF,
    PRODUCT_REVIEWER_REPORT_REF,
    ProductGradeFinding,
    ProductGradeReport,
    ProductRepairPacket,
    ProductRepairPlanner,
    ProductReviewerReport,
    SchemaValidationError,
    initialize_job_workspace,
)


def sample_finding(finding_id: str = "P0-runtime-same-plan-conflict-coverage-missing") -> ProductGradeFinding:
    return ProductGradeFinding(
        finding_id=finding_id,
        severity="blocking",
        title="Same-plan duplicate conflict coverage is missing",
        message="Runtime helper must reject duplicate target paths and titles in one write plan.",
        affected_profiles=["runtime_helper_skill", "local_file_safety_skill"],
        affected_risk_domains=["filesystem_write"],
        required_fix="Detect duplicate target paths and duplicate titles before writing files.",
        required_tests=["duplicate path fixture", "duplicate title fixture", "CLI conflict exit code"],
        evidence_refs=["qa/product_runtime_check_result.json"],
    )


def make_workspace(tmp_path: Path, job_id: str = "product-repair-001"):
    return initialize_job_workspace(tmp_path / "runs", job_id)


def write_product_grade_report(workspace, findings: list[ProductGradeFinding]) -> None:
    workspace.resolve_path("qa").mkdir(parents=True, exist_ok=True)
    ProductGradeReport(
        job_id=workspace.job_id,
        product_grade=not findings,
        package_hash="0" * 64,
        matrix_ref=PRODUCT_ACCEPTANCE_MATRIX_REF,
        findings=findings,
        checked_item_ids=["PG-RUNTIME-SAME-PLAN-DUPLICATE-PATH"],
        evidence_refs=[PRODUCT_ACCEPTANCE_MATRIX_REF],
    ).write_json_file(workspace.resolve_path(PRODUCT_GRADE_REPORT_REF))


def test_product_repair_planner_compiles_product_gate_findings(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    write_product_grade_report(workspace, [sample_finding()])

    packet = ProductRepairPlanner().plan(workspace)

    assert packet.repair_required is True
    assert packet.source_refs == [PRODUCT_GRADE_REPORT_REF]
    assert packet.repair_items[0].finding_id == "product_gate:P0-runtime-same-plan-conflict-coverage-missing"
    assert packet.repair_items[0].source_kind == "product_gate"
    assert packet.repair_items[0].source_ref == PRODUCT_GRADE_REPORT_REF
    assert "duplicate path fixture" in packet.required_tests
    assert packet.trust_boundaries["raw_prompt_included"] is False
    loaded = ProductRepairPacket.read_json_file(workspace.resolve_path(PRODUCT_REPAIR_PACKET_REF, must_exist=True))
    assert loaded.to_dict() == packet.to_dict()


def test_product_repair_planner_namespaces_reviewer_findings(tmp_path: Path):
    workspace = make_workspace(tmp_path, job_id="product-repair-reviewer")
    finding = sample_finding("P0-runtime-intra-plan-conflict")
    write_product_grade_report(workspace, [finding])
    ProductReviewerReport(
        job_id=workspace.job_id,
        reviewer_id="gpt-5.5-xhigh",
        summary_score=62,
        findings=[finding],
        evidence_refs=["qa/reviewer_evidence/runtime_duplicate_conflict.json"],
    ).write_json_file(workspace.resolve_path(PRODUCT_REVIEWER_REPORT_REF))

    packet = ProductRepairPlanner().plan(workspace)

    assert [item.finding_id for item in packet.repair_items] == [
        "product_gate:P0-runtime-intra-plan-conflict",
        "reviewer_report:P0-runtime-intra-plan-conflict",
    ]
    assert packet.source_refs == [PRODUCT_GRADE_REPORT_REF, PRODUCT_REVIEWER_REPORT_REF]
    assert packet.repair_items[1].source_kind == "reviewer_report"
    assert packet.repair_items[1].source_finding_id == "P0-runtime-intra-plan-conflict"


def test_product_repair_planner_fails_closed_without_product_grade_report(tmp_path: Path):
    workspace = make_workspace(tmp_path, job_id="product-repair-missing-report")

    packet = ProductRepairPlanner().plan(workspace)

    assert packet.repair_required is True
    assert packet.repair_items[0].finding_id == "product_gate:P0-product-grade-report-missing"
    assert packet.repair_items[0].source_ref == PRODUCT_GRADE_REPORT_REF
    assert "ProductGradeGate emits qa/product_grade_report.json" in packet.required_tests


def test_product_repair_planner_rejects_raw_reviewer_report_payload(tmp_path: Path):
    workspace = make_workspace(tmp_path, job_id="product-repair-raw-reviewer")
    write_product_grade_report(workspace, [])
    reviewer_path = workspace.resolve_path(PRODUCT_REVIEWER_REPORT_REF)
    reviewer_path.write_text(
        json.dumps(
            {
                "schema_version": "skillfoundry.product_reviewer_report.v1",
                "job_id": workspace.job_id,
                "reviewer_id": "gpt-5.5-xhigh",
                "summary_score": 40,
                "findings": [],
                "raw_transcript": "do not persist raw reviewer conversations",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SchemaValidationError):
        ProductRepairPlanner().plan(workspace)
