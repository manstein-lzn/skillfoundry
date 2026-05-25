from __future__ import annotations

import json

import pytest

import skillfoundry
from skillfoundry import (
    APPROVAL_APPROVED,
    PRODUCT_GRADE_REPORT_REF,
    PRODUCT_REPAIR_PACKET_REF,
    QUARANTINE_QUARANTINED,
    REGISTRY_STATUS_CANDIDATE_REGISTERED,
    REGISTRY_STATUS_PRODUCT_GRADE_REGISTERED,
    AcceptanceCoverageEvaluator,
    AcceptanceCriteriaPlanner,
    DuplicatePolicy,
    LocalSkillRegistry,
    ProductGradeReport,
    ProductRepairPacket,
    RegistryDuplicateError,
    RegistryEntry,
    RegistryGateError,
    VerificationResult,
    Verifier,
    bridge_skillfoundry_verification_result,
    build_goal_contract,
    build_verification_gate,
    initialize_job_workspace,
)
from skillfoundry.frontdesk_schema import AcceptanceCriteriaSet, AcceptanceCriterion
from skillfoundry.schema import sha256_file
from skillfoundry.verification_bridge import CONTEXTFORGE_VERIFICATION_RESULT_REF
from skillfoundry.worker import WorkerAdapter, WorkerExecutionOutcome


VALID_REGISTRY_SKILL_MD = """---
name: valid-registry-skill
description: Deterministic registry fixture.
references:
  - references/guide.md
scripts:
  - scripts/helper.py
---

# Valid Registry Skill

## Overview

This fixture describes a complete local Codex Skill package for registry tests.

## When To Use

- Use when the registry needs a deterministic passing package.

## When Not To Use

- Do not use when independent verifier evidence is missing or failing.

## Inputs

- A SkillFoundry build contract and worker input manifest.

## Outputs

- A verifier-approved Skill package and a traceable registry entry.

## Workflow

1. Read the locked inputs.
2. Build a package in the allowed package directory.
3. Let the independent verifier decide approval.

## Safety

- Do not treat worker self-report as acceptance evidence.
"""


INVALID_SELF_REPORT_SKILL_MD = """# Invalid Builder Self Report Fixture

The worker says success, but this package is structurally incomplete.
"""


class RegistryFixtureWorker:
    def __init__(self, skill_md: str = VALID_REGISTRY_SKILL_MD) -> None:
        self.skill_md = skill_md

    @property
    def worker_type(self) -> str:
        return "test:registry-fixture"

    def run(self, context):
        context.write_text("package/SKILL.md", self.skill_md)
        context.write_text("package/references/guide.md", "# Guide\n\nReference fixture.\n")
        context.write_text("package/scripts/helper.py", "# helper fixture; never executed by verifier\n")
        return WorkerExecutionOutcome(
            status="completed",
            exit_status="success",
            summary="Fixture worker reported success; registry must still require verifier evidence.",
            artifacts=[
                "package/SKILL.md",
                "package/references/guide.md",
                "package/scripts/helper.py",
            ],
            transcript_lines=["wrote registry fixture package"],
            usage_unavailable_reason="Fixture worker does not call model providers.",
        )


def make_workspace(tmp_path, *, job_id: str = "registry-001", skill_md: str = VALID_REGISTRY_SKILL_MD):
    workspace = initialize_job_workspace(tmp_path / "runs", job_id)
    WorkerAdapter(RegistryFixtureWorker(skill_md)).invoke(workspace, "001")
    return workspace


def make_verified_workspace(
    tmp_path,
    *,
    job_id: str = "registry-001",
    skill_md: str = VALID_REGISTRY_SKILL_MD,
):
    workspace = make_workspace(tmp_path, job_id=job_id, skill_md=skill_md)
    result = Verifier().verify(workspace)
    return workspace, result


def criterion(criterion_id: str = "AC-REGISTRY-CF") -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id=criterion_id,
        description="Registry ContextForge evidence is covered by verifier output.",
        source_requirement="Register only independently verified packages.",
        source_turn_ids=["turn-001"],
        requirement_id=f"REQ-{criterion_id}",
        test_method="static",
        pass_condition="The mapped verifier check passes.",
        failure_examples=["Verifier evidence is missing."],
        required_evidence=[],
        evidence_kind="verifier_check",
        priority="must",
        risk_tags=[],
        data_sensitivity="internal",
        coverage_status="planned",
        verifier_check_id="package_skill_md_present",
    )


def write_contextforge_verified_evidence(workspace):
    write_acceptance_coverage_evidence(workspace)
    goal = build_goal_contract(workspace)
    gate = build_verification_gate(workspace, goal.goal_id)
    contextforge_result = bridge_skillfoundry_verification_result(
        workspace,
        gate,
        expected_gate_hash=gate.gate_hash,
    )
    assert contextforge_result.passed is True
    return contextforge_result


def write_acceptance_coverage_evidence(workspace):
    AcceptanceCriteriaSet(criteria=[criterion()], job_id=workspace.job_id).write_yaml_file(
        workspace.resolve_path("acceptance_criteria.yaml")
    )
    plan = AcceptanceCriteriaPlanner().plan(workspace)
    coverage = AcceptanceCoverageEvaluator().evaluate(workspace, plan=plan)
    assert coverage.passed is True
    return coverage


def write_fake_contextforge_result(workspace, *, status: str = "passed", passed: bool = True) -> None:
    coverage_path = workspace.root / "qa" / "acceptance_coverage_result.json"
    payload = {
        "schema": "contextforge.verification_result.v0.1",
        "version": "0.1",
        "verification_result_id": f"fake-cf-{workspace.job_id}",
        "verification_gate_id": "fake-gate",
        "goal_id": "fake-goal",
        "goal_run_id": None,
        "status": status,
        "validator_results": [],
        "passed": passed,
        "created_at": "2026-05-22T00:00:00Z",
        "metadata": {
            "job_id": workspace.job_id,
            "skillfoundry_verification_result_hash": sha256_file(
                workspace.resolve_path("verifier/verification_result.json", must_exist=True)
            ),
            "acceptance_coverage_result_hash": (
                sha256_file(coverage_path)
                if coverage_path.exists()
                else None
            ),
            "current_package_hash": VerificationResult.read_json_file(
                workspace.resolve_path("verifier/verification_result.json", must_exist=True)
            ).package_hash,
        },
    }
    path = workspace.root / "contextforge" / "verification_result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_product_grade_report(workspace, *, product_grade: bool = True) -> ProductGradeReport:
    workspace.resolve_path("qa").mkdir(parents=True, exist_ok=True)
    verification_result = VerificationResult.read_json_file(
        workspace.resolve_path("verifier/verification_result.json", must_exist=True)
    )
    report = ProductGradeReport(
        job_id=workspace.job_id,
        product_grade=product_grade,
        package_hash=verification_result.package_hash,
        matrix_ref="product_contract/product_acceptance_matrix.json",
        findings=[],
        checked_item_ids=["PG-RUNTIME-SAME-PLAN-DUPLICATE-PATH"],
        evidence_refs=[],
    )
    report.write_json_file(workspace.resolve_path(PRODUCT_GRADE_REPORT_REF))
    ProductRepairPacket(
        job_id=workspace.job_id,
        repair_required=not product_grade,
        source_report_ref=PRODUCT_GRADE_REPORT_REF,
        findings=[],
        repair_instructions=[] if product_grade else ["Repair product-grade findings."],
        required_tests=[] if product_grade else ["runtime matrix checks"],
    ).write_json_file(workspace.resolve_path(PRODUCT_REPAIR_PACKET_REF))
    return report


def test_registry_api_is_exported():
    assert skillfoundry.LocalSkillRegistry is LocalSkillRegistry
    assert skillfoundry.DuplicatePolicy is DuplicatePolicy
    assert skillfoundry.RegistryGateError is RegistryGateError


def test_verifier_passed_package_registers_and_registry_entry_round_trips(tmp_path):
    workspace, result = make_verified_workspace(tmp_path)
    registry = LocalSkillRegistry(tmp_path / "registry.json")
    package_hash_before = result.package_hash
    skill_path = workspace.resolve_path("package/SKILL.md", must_exist=True)
    skill_file_hash_before = sha256_file(skill_path)

    entry = registry.add_verified(workspace, version="1.0.0")

    assert entry.skill_id == "registry-001-skill"
    assert entry.version == "1.0.0"
    assert entry.package_hash == package_hash_before
    assert entry.approval_status == APPROVAL_APPROVED
    assert entry.quarantine_status == "none"
    assert sha256_file(skill_path) == skill_file_hash_before
    assert RegistryEntry.from_json(entry.to_json()).to_dict() == entry.to_dict()
    assert registry.get(entry.skill_id, entry.version).to_dict() == entry.to_dict()
    assert [item.to_dict() for item in registry.list()] == [entry.to_dict()]

    report = registry.verify(entry.skill_id, entry.version)
    assert report.valid is True
    assert report.failures == []


def test_verifier_failed_package_cannot_register(tmp_path):
    workspace, result = make_verified_workspace(tmp_path, skill_md=INVALID_SELF_REPORT_SKILL_MD)
    assert result.passed is False

    registry = LocalSkillRegistry(tmp_path / "registry.json")
    with pytest.raises(RegistryGateError) as exc_info:
        registry.add_verified(workspace, version="1.0.0")

    assert any("verification_result.passed" in failure for failure in exc_info.value.failures)
    assert not (tmp_path / "registry.json").exists()


def test_builder_self_report_alone_cannot_register(tmp_path):
    workspace = make_workspace(tmp_path)

    registry = LocalSkillRegistry(tmp_path / "registry.json")
    with pytest.raises(RegistryGateError) as exc_info:
        registry.add_verified(workspace, version="1.0.0")

    assert any("verification_result" in failure for failure in exc_info.value.failures)
    assert not (tmp_path / "registry.json").exists()


def test_tampered_package_after_verification_cannot_register(tmp_path):
    workspace, result = make_verified_workspace(tmp_path)
    skill_path = workspace.resolve_path("package/SKILL.md", must_exist=True)
    skill_path.write_text(skill_path.read_text(encoding="utf-8") + "\nTamper after verification.\n", encoding="utf-8")

    registry = LocalSkillRegistry(tmp_path / "registry.json")
    with pytest.raises(RegistryGateError) as exc_info:
        registry.add_verified(workspace, version="1.0.0")

    assert any("package_hash" in failure for failure in exc_info.value.failures)


def test_tampered_package_after_registration_fails_registry_verify(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path)
    registry = LocalSkillRegistry(tmp_path / "registry.json")
    entry = registry.add_verified(workspace, version="1.0.0")

    skill_path = workspace.resolve_path("package/SKILL.md", must_exist=True)
    skill_path.write_text(skill_path.read_text(encoding="utf-8") + "\nTamper after registration.\n", encoding="utf-8")

    report = registry.verify_entry(entry)

    assert report.valid is False
    assert any("package_hash" in failure for failure in report.failures)


def test_tampered_verification_result_fails_registry_verify(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path)
    registry = LocalSkillRegistry(tmp_path / "registry.json")
    entry = registry.add_verified(workspace, version="1.0.0")

    result_path = workspace.resolve_path("verifier/verification_result.json", must_exist=True)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["created_at"] = "2099-01-01T00:00:00Z"
    result_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    report = registry.verify_entry(entry)

    assert report.valid is False
    assert any("verification_result_hash" in failure for failure in report.failures)


def test_verification_result_must_reference_execution_report(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path)
    result_path = workspace.resolve_path("verifier/verification_result.json", must_exist=True)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["evidence_refs"] = [ref for ref in payload["evidence_refs"] if not ref.startswith("attempts/")]
    result_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    registry = LocalSkillRegistry(tmp_path / "registry.json")
    with pytest.raises(RegistryGateError) as exc_info:
        registry.add_verified(workspace, version="1.0.0")

    assert any("execution report ref" in failure for failure in exc_info.value.failures)


def test_missing_artifact_manifest_fails_registration(tmp_path):
    workspace, result = make_verified_workspace(tmp_path)
    assert result.passed is True
    workspace.resolve_path("artifact_manifest.json", must_exist=True).unlink()

    registry = LocalSkillRegistry(tmp_path / "registry.json")
    with pytest.raises(RegistryGateError) as exc_info:
        registry.add_verified(workspace, version="1.0.0")

    assert any("artifact_manifest" in failure for failure in exc_info.value.failures)


def test_approved_entry_traces_to_required_wp6_evidence(tmp_path):
    workspace, result = make_verified_workspace(tmp_path)
    registry = LocalSkillRegistry(tmp_path / "registry.json")

    entry = registry.add_verified(workspace, version="1.0.0")
    provenance = entry.provenance

    assert entry.build_job_id == workspace.job_id
    assert provenance["build_job_id"] == workspace.job_id
    assert provenance["package"]["ref"] == "package"
    assert provenance["package"]["sha256"] == entry.package_hash
    assert provenance["worker_invocation"]["invocation_id"] == entry.worker_invocation_id
    assert provenance["worker_invocation"]["input_manifest_ref"] == "attempts/001/input_manifest.json"
    assert provenance["execution_report"]["ref"] == "attempts/001/execution_report.json"
    assert provenance["verification_spec"]["ref"] == "verification_spec.yaml"
    assert provenance["verification_spec"]["sha256"] == entry.verification_spec_hash
    assert provenance["verification_result"]["ref"] == "verifier/verification_result.json"
    assert provenance["verification_result"]["result_id"] == result.result_id
    assert provenance["verification_result"]["sha256"] == entry.verification_result_hash
    assert provenance["artifact_manifest"]["ref"] == "artifact_manifest.json"
    assert provenance["artifact_manifest"]["sha256"] == entry.artifact_manifest_hash
    assert provenance["verifier"]["version"] == entry.verifier_version


def test_add_verified_records_candidate_registered_status(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path, job_id="registry-candidate")
    registry = LocalSkillRegistry(tmp_path / "registry-candidate.json")

    entry = registry.add_verified(workspace, version="1.0.0")

    assert entry.approval_status == APPROVAL_APPROVED
    assert entry.provenance["registry_status"] == REGISTRY_STATUS_CANDIDATE_REGISTERED
    assert entry.provenance["product_grade_required"] is False
    assert registry.list(registry_status=REGISTRY_STATUS_CANDIDATE_REGISTERED) == [entry]
    assert registry.product_grade_entries() == []


def test_add_product_grade_requires_passing_product_grade_report(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path, job_id="registry-product-grade")
    registry = LocalSkillRegistry(tmp_path / "registry-product-grade.json")

    with pytest.raises(RegistryGateError) as missing_exc:
        registry.add_product_grade(workspace, version="1.0.0")
    assert any("product_grade_report" in failure for failure in missing_exc.value.failures)

    failed_report = write_product_grade_report(workspace, product_grade=False)
    with pytest.raises(RegistryGateError) as failed_exc:
        registry.add_product_grade(workspace, version="1.0.0")
    assert failed_report.product_grade is False
    assert any("ProductGradeGate did not pass" in failure for failure in failed_exc.value.failures)

    passed_report = write_product_grade_report(workspace, product_grade=True)
    entry = registry.add_product_grade(workspace, version="1.0.0")

    assert entry.provenance["registry_status"] == REGISTRY_STATUS_PRODUCT_GRADE_REGISTERED
    assert entry.provenance["product_grade_required"] is True
    assert entry.provenance["product_grade_report"]["ref"] == PRODUCT_GRADE_REPORT_REF
    assert entry.provenance["product_grade_report"]["product_grade"] is True
    assert entry.provenance["product_grade_report"]["gate_version"] == passed_report.gate_version
    assert registry.product_grade_entries() == [entry]
    assert registry.verify_entry(entry).valid is True


def test_product_grade_registry_verify_fails_after_report_tampering(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path, job_id="registry-product-grade-tamper")
    write_product_grade_report(workspace, product_grade=True)
    registry = LocalSkillRegistry(tmp_path / "registry-product-grade-tamper.json")
    entry = registry.add_product_grade(workspace, version="1.0.0")

    report_path = workspace.resolve_path(PRODUCT_GRADE_REPORT_REF, must_exist=True)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["product_grade"] = False
    report_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    report = registry.verify_entry(entry)

    assert report.valid is False
    assert any("product_grade_report_hash" in failure for failure in report.failures)


def test_contextforge_verified_workspace_registers_with_v2_provenance(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path, job_id="registry-cf-pass")
    contextforge_result = write_contextforge_verified_evidence(workspace)
    registry = LocalSkillRegistry(tmp_path / "registry-cf-pass.json")

    entry = registry.add_verified(workspace, version="1.0.0", require_contextforge_verification=True)
    provenance = entry.provenance["contextforge_verification_result"]

    assert provenance["ref"] == CONTEXTFORGE_VERIFICATION_RESULT_REF
    assert provenance["verification_result_id"] == contextforge_result.verification_result_id
    assert provenance["status"] == "passed"
    assert provenance["passed"] is True
    assert provenance["sha256"] == sha256_file(
        workspace.resolve_path(CONTEXTFORGE_VERIFICATION_RESULT_REF, must_exist=True)
    )
    assert provenance["skillfoundry_verification_result_hash"] == entry.verification_result_hash
    assert provenance["current_package_hash"] == entry.package_hash
    assert registry.verify_entry(entry).valid is True


def test_registry_can_require_contextforge_verification_result(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path, job_id="registry-cf-required")
    registry = LocalSkillRegistry(tmp_path / "registry-cf-required.json")

    with pytest.raises(RegistryGateError) as exc_info:
        registry.add_verified(workspace, version="1.0.0", require_contextforge_verification=True)

    assert any("contextforge_verification_result" in failure for failure in exc_info.value.failures)


def test_failed_contextforge_verification_blocks_v2_registration(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path, job_id="registry-cf-failed")
    write_contextforge_verified_evidence(workspace)
    path = workspace.resolve_path(CONTEXTFORGE_VERIFICATION_RESULT_REF, must_exist=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = "failed"
    payload["passed"] = False
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    registry = LocalSkillRegistry(tmp_path / "registry-cf-failed.json")

    with pytest.raises(RegistryGateError) as exc_info:
        registry.add_verified(workspace, version="1.0.0", require_contextforge_verification=True)

    assert any("contextforge_verification_result.status" in failure for failure in exc_info.value.failures)


def test_fabricated_contextforge_pass_without_bridge_evidence_blocks_v2_registration(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path, job_id="registry-cf-fabricated")
    write_acceptance_coverage_evidence(workspace)
    write_fake_contextforge_result(workspace, status="passed", passed=True)
    registry = LocalSkillRegistry(tmp_path / "registry-cf-fabricated.json")

    with pytest.raises(RegistryGateError) as exc_info:
        registry.add_verified(workspace, version="1.0.0", require_contextforge_verification=True)

    assert any("metadata.bridge" in failure for failure in exc_info.value.failures)
    assert any("missing passed bridge validator" in failure for failure in exc_info.value.failures)


def test_default_registry_ignores_invalid_contextforge_result_when_not_required(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path, job_id="registry-cf-default-compat")
    write_fake_contextforge_result(workspace, status="failed", passed=False)
    registry = LocalSkillRegistry(tmp_path / "registry-cf-default-compat.json")

    entry = registry.add_verified(workspace, version="1.0.0")

    assert "contextforge_verification_result" not in entry.provenance
    assert registry.verify_entry(entry).valid is True


def test_registry_verify_fails_after_contextforge_result_tampering(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path, job_id="registry-cf-tamper")
    write_contextforge_verified_evidence(workspace)
    registry = LocalSkillRegistry(tmp_path / "registry-cf-tamper.json")
    entry = registry.add_verified(workspace, version="1.0.0", require_contextforge_verification=True)
    path = workspace.resolve_path(CONTEXTFORGE_VERIFICATION_RESULT_REF, must_exist=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["created_at"] = "2099-01-01T00:00:00Z"
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    report = registry.verify_entry(entry)

    assert report.valid is False
    assert any("contextforge_verification_result_hash" in failure for failure in report.failures)


def test_quarantined_entry_is_excluded_from_default_list_and_reuse_candidates(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path)
    registry = LocalSkillRegistry(tmp_path / "registry.json")
    entry = registry.add_verified(workspace, version="1.0.0")

    quarantined = registry.quarantine(entry.skill_id, entry.version, "manual safety hold")

    assert quarantined.quarantine_status == QUARANTINE_QUARANTINED
    assert registry.list() == []
    assert registry.reuse_candidates() == []
    assert [item.to_dict() for item in registry.list(status=QUARANTINE_QUARANTINED)] == [quarantined.to_dict()]
    assert [item.to_dict() for item in registry.list(status=APPROVAL_APPROVED, include_quarantined=True)] == [
        quarantined.to_dict()
    ]


def test_duplicate_version_policy_rejects_by_default(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path)
    registry = LocalSkillRegistry(tmp_path / "registry.json")
    assert registry.duplicate_policy is DuplicatePolicy.REJECT

    registry.add_verified(workspace, version="1.0.0")
    with pytest.raises(RegistryDuplicateError):
        registry.add_verified(workspace, version="1.0.0")


def test_duplicate_version_policy_can_be_idempotent(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path)
    registry = LocalSkillRegistry(tmp_path / "registry.json", duplicate_policy=DuplicatePolicy.IDEMPOTENT)

    first = registry.add_verified(workspace, version="1.0.0")
    second = registry.add_verified(workspace, version="1.0.0")

    assert second.to_dict() == first.to_dict()
    assert [item.to_dict() for item in registry.list()] == [first.to_dict()]


def test_tampered_verification_result_payload_cannot_be_reused_as_pass_evidence(tmp_path):
    workspace, _result = make_verified_workspace(tmp_path)
    result_path = workspace.resolve_path("verifier/verification_result.json", must_exist=True)
    result = VerificationResult.read_json_file(result_path)
    payload = result.to_dict()
    payload["passed"] = True
    payload["failures"] = ["tampered verifier result should fail"]
    result_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    registry = LocalSkillRegistry(tmp_path / "registry.json")
    with pytest.raises(RegistryGateError) as exc_info:
        registry.add_verified(workspace, version="1.0.0")

    assert any("verification_result.failures" in failure for failure in exc_info.value.failures)
