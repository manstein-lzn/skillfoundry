import pytest

from skillfoundry import (
    DELIVERY_PROFILE_CONTRACT_REF,
    PRODUCT_ACCEPTANCE_MATRIX_REF,
    PRODUCT_GRADE_REPORT_REF,
    PRODUCT_REPAIR_PACKET_REF,
    PRODUCT_REVIEWER_REPORT_REF,
    DeliveryProfileContract,
    ProductAcceptanceItem,
    ProductAcceptanceMatrix,
    ProductGradeFinding,
    ProductGradeReport,
    ProductRepairItem,
    ProductRepairPacket,
    ProductReviewerReport,
    RiskProfile,
    SchemaValidationError,
    sha256_json,
)


def sample_item() -> ProductAcceptanceItem:
    return ProductAcceptanceItem(
        item_id="PG-RUNTIME-SAME-PLAN-DUPLICATE-PATH",
        requirement="Detect duplicate target paths inside one write plan.",
        profile="local_file_safety_skill",
        risk_domain="filesystem_write",
        check_kind="runtime_fixture_check",
        severity="blocking",
        required_evidence=["duplicate path fixture"],
        source_rule="runtime_helper_local_file_safety_mvp",
    )


def sample_finding() -> ProductGradeFinding:
    return ProductGradeFinding(
        finding_id="P0-runtime-same-plan-conflict-coverage-missing",
        severity="blocking",
        title="Same-plan duplicate conflict coverage is missing",
        message="Duplicate target path/title coverage is required.",
        affected_profiles=["runtime_helper_skill", "local_file_safety_skill"],
        affected_risk_domains=["filesystem_write"],
        required_fix="Add same-plan duplicate path/title conflict detection.",
        required_tests=["duplicate path fixture", "duplicate title fixture"],
        evidence_refs=[],
    )


def test_product_contract_constants_are_stable():
    assert DELIVERY_PROFILE_CONTRACT_REF == "product_contract/delivery_profile.json"
    assert PRODUCT_ACCEPTANCE_MATRIX_REF == "product_contract/product_acceptance_matrix.json"
    assert PRODUCT_GRADE_REPORT_REF == "qa/product_grade_report.json"
    assert PRODUCT_REVIEWER_REPORT_REF == "qa/product_reviewer_report.json"
    assert PRODUCT_REPAIR_PACKET_REF == "qa/product_repair_packet.json"


def test_delivery_and_risk_contracts_round_trip():
    delivery = DeliveryProfileContract(
        job_id="product-contract-001",
        profiles=["codex_skill", "runtime_helper_skill", "local_file_safety_skill"],
        source_refs=["skill_spec.yaml", "acceptance_criteria.yaml"],
        profile_reasons={"runtime_helper_skill": {"signals": ["runtime_helper"]}},
    )
    risk = RiskProfile(
        job_id="product-contract-001",
        risk_domains=["filesystem_write", "runtime_execution", "distribution_package"],
        source_refs=["skill_spec.yaml"],
        risk_reasons={"filesystem_write": {"profiles": ["local_file_safety_skill"]}},
    )

    assert DeliveryProfileContract.from_json(delivery.to_json()).to_dict() == delivery.to_dict()
    assert RiskProfile.from_json(risk.to_json()).to_dict() == risk.to_dict()


def test_product_acceptance_matrix_round_trip_and_hash_is_deterministic():
    matrix = ProductAcceptanceMatrix(job_id="product-contract-001", items=[sample_item()])

    loaded = ProductAcceptanceMatrix.from_json(matrix.to_json())

    assert loaded.to_dict() == matrix.to_dict()
    assert sha256_json(matrix) == sha256_json(loaded)


def test_product_grade_report_and_repair_packet_round_trip():
    finding = sample_finding()
    report = ProductGradeReport(
        job_id="product-contract-001",
        product_grade=False,
        package_hash="0" * 64,
        matrix_ref=PRODUCT_ACCEPTANCE_MATRIX_REF,
        findings=[finding],
        checked_item_ids=["PG-RUNTIME-SAME-PLAN-DUPLICATE-PATH"],
        evidence_refs=[PRODUCT_ACCEPTANCE_MATRIX_REF],
    )
    repair = ProductRepairPacket(
        job_id="product-contract-001",
        repair_required=True,
        source_report_ref=PRODUCT_GRADE_REPORT_REF,
        findings=[finding],
        repair_instructions=["Add duplicate path/title conflict handling."],
        required_tests=["duplicate path fixture"],
        repair_items=[
            ProductRepairItem(
                finding_id="product_gate:P0-runtime-same-plan-conflict-coverage-missing",
                severity="blocking",
                title=finding.title,
                affected_profiles=finding.affected_profiles,
                affected_risk_domains=finding.affected_risk_domains,
                required_fix=finding.required_fix,
                required_tests=finding.required_tests,
                evidence_refs=finding.evidence_refs,
                source_kind="product_gate",
                source_ref=PRODUCT_GRADE_REPORT_REF,
                source_finding_id=finding.finding_id,
            )
        ],
        source_refs=[PRODUCT_GRADE_REPORT_REF],
    )

    assert ProductGradeReport.from_json(report.to_json()).to_dict() == report.to_dict()
    assert ProductRepairPacket.from_json(repair.to_json()).to_dict() == repair.to_dict()


def test_product_reviewer_report_round_trip():
    report = ProductReviewerReport(
        job_id="product-contract-001",
        reviewer_id="gpt-5.5-xhigh",
        summary_score=66,
        findings=[sample_finding()],
        evidence_refs=["qa/reviewer_evidence/runtime_duplicate_conflict.json"],
    )

    assert ProductReviewerReport.from_json(report.to_json()).to_dict() == report.to_dict()


def test_product_contract_unknown_fields_fail():
    payload = ProductAcceptanceMatrix(job_id="product-contract-001", items=[sample_item()]).to_dict()
    payload["unexpected"] = True

    with pytest.raises(SchemaValidationError):
        ProductAcceptanceMatrix.from_dict(payload)


def test_product_contract_rejects_unknown_profiles_and_risks():
    with pytest.raises(SchemaValidationError):
        DeliveryProfileContract(
            job_id="product-contract-001",
            profiles=["codex_skill", "invented_profile"],
            source_refs=["skill_spec.yaml"],
        ).to_dict()

    with pytest.raises(SchemaValidationError):
        RiskProfile(
            job_id="product-contract-001",
            risk_domains=["made_up_risk"],
            source_refs=["skill_spec.yaml"],
        ).to_dict()


def test_product_contract_rejects_raw_prompt_fields_in_metadata():
    item = sample_item()
    item.metadata = {"nested": {"raw_prompt": "do not persist this"}}

    with pytest.raises(SchemaValidationError):
        item.to_dict()


def test_product_reviewer_report_rejects_raw_transcript_fields():
    payload = ProductReviewerReport(
        job_id="product-contract-001",
        reviewer_id="gpt-5.5-xhigh",
        findings=[sample_finding()],
    ).to_dict()
    payload["findings"][0]["metadata"] = {"messages": [{"role": "reviewer"}]}

    with pytest.raises(SchemaValidationError):
        ProductReviewerReport.from_dict(payload)
