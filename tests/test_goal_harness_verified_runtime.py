from __future__ import annotations

import json
from pathlib import Path

from contextforge import ContextLedger
import pytest

import skillfoundry
from skillfoundry import (
    AcceptanceCriteriaSet,
    AcceptanceCriterion,
    APPROVAL_APPROVED,
    CONTEXTFORGE_VERIFICATION_RESULT_REF,
    GOAL_RUNTIME_RESULT_REF,
    GOAL_RUNTIME_STATE_REF,
    LocalSkillRegistry,
    VERIFIED_GOAL_RUNTIME_RESULT_REF,
    run_verified_offline_goal_harness,
)
from skillfoundry.workspace import initialize_job_workspace


CREATED_AT = "2026-05-22T00:00:00Z"


def _criterion() -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id="AC-V2-001",
        description="The generated package includes a readable SKILL.md file.",
        source_requirement="Build a verified Skill package through the v2 Goal Harness path.",
        source_turn_ids=["turn-001"],
        requirement_id="REQ-V2-001",
        test_method="static",
        pass_condition="Verifier check package_skill_md_present passes.",
        failure_examples=["package/SKILL.md is missing."],
        required_evidence=[],
        evidence_kind="verifier_check",
        priority="must",
        risk_tags=[],
        data_sensitivity="internal",
        coverage_status="planned",
        verifier_check_id="package_skill_md_present",
    )


def test_verified_offline_goal_harness_promotes_through_verifier_coverage_bridge_and_registry(
    tmp_path: Path,
) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "verified-v2")
    AcceptanceCriteriaSet(criteria=[_criterion()], job_id=workspace.job_id).write_yaml_file(
        workspace.resolve_path("acceptance_criteria.yaml")
    )
    registry_path = tmp_path / "registry.json"

    result = run_verified_offline_goal_harness(
        workspace,
        registry_path=registry_path,
        created_at=CREATED_AT,
    )

    assert result.verifier_result.passed is True
    assert result.acceptance_coverage_result.passed is True
    assert result.contextforge_verification_result.passed is True
    assert result.contextforge_verification_result.status == "passed"
    assert (
        result.goal_harness.runtime_result["ids"]["verification_result_id"]
        == result.contextforge_verification_result.verification_result_id
    )
    assert result.goal_harness.runtime_result["status"]["verification"] == "passed"
    assert result.goal_harness.runtime_result["status"]["goal_run"] == "completed"
    assert result.goal_harness.runtime_result["verification_mode"] == "verified"
    assert result.registry_entry.approval_status == APPROVAL_APPROVED
    assert result.final_report["final_status"] == "registered"
    assert result.verified_runtime_result["status"]["registry_approved"] is True
    assert result.verified_runtime_result["trust_boundaries"] == {
        "worker_self_report_is_not_acceptance": True,
        "registry_requires_contextforge_verification": True,
        "verifier_is_quality_fact_source": True,
        "acceptance_coverage_required": True,
    }

    for ref in (
        "package/SKILL.md",
        "attempts/001/input_manifest.json",
        "attempts/001/execution_report.json",
        "attempts/001/worker_transcript.log",
        "attempts/001/output_diff.patch",
        "verifier/verification_result.json",
        "qa/acceptance_coverage_plan.json",
        "qa/acceptance_coverage_result.json",
        CONTEXTFORGE_VERIFICATION_RESULT_REF,
        VERIFIED_GOAL_RUNTIME_RESULT_REF,
        "final_report.json",
    ):
        assert workspace.resolve_path(ref, must_exist=True).is_file()

    entry_report = LocalSkillRegistry(registry_path).verify_entry(result.registry_entry)
    assert entry_report.valid is True
    assert entry_report.failures == []

    execution_report = json.loads(
        workspace.resolve_path("attempts/001/execution_report.json", must_exist=True).read_text()
    )
    input_manifest = json.loads(workspace.resolve_path("attempts/001/input_manifest.json", must_exist=True).read_text())
    assert execution_report["status"] == "completed"
    assert execution_report["exit_status"] == "success"
    assert input_manifest["invocation_id"] == execution_report["invocation_id"]
    assert input_manifest["worker_type"] == "contextforge:fake_model"

    ledger = ContextLedger.connect(workspace.resolve_path("contextforge/ledger.sqlite3", must_exist=True))
    try:
        assert ledger.get_worker_run(result.goal_harness.harness_result.worker_run.worker_run_id)
        assert ledger.get_verification_result(result.contextforge_verification_result.verification_result_id)
        goal_record = ledger.get_goal_run_record(result.goal_harness.goal_run.goal_run_id)
        assert goal_record is not None
        assert goal_record.verification_result_id == result.contextforge_verification_result.verification_result_id
        assert goal_record.status == "completed"
    finally:
        ledger.close()


def test_verified_offline_goal_harness_fails_closed_before_runtime_without_acceptance_criteria(
    tmp_path: Path,
) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "missing-criteria")
    registry_path = tmp_path / "registry.json"

    with pytest.raises(ValueError, match="acceptance_criteria.yaml"):
        run_verified_offline_goal_harness(
            workspace,
            registry_path=registry_path,
            created_at=CREATED_AT,
        )

    assert not (workspace.root / GOAL_RUNTIME_RESULT_REF).exists()
    assert not (workspace.root / GOAL_RUNTIME_STATE_REF).exists()
    assert not (workspace.root / CONTEXTFORGE_VERIFICATION_RESULT_REF).exists()
    assert not (workspace.root / VERIFIED_GOAL_RUNTIME_RESULT_REF).exists()


def test_verified_goal_harness_runtime_symbols_are_exported() -> None:
    assert skillfoundry.run_verified_offline_goal_harness is run_verified_offline_goal_harness
    assert skillfoundry.VERIFIED_GOAL_RUNTIME_RESULT_REF == VERIFIED_GOAL_RUNTIME_RESULT_REF
