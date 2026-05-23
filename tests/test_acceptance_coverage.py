from __future__ import annotations

import json

import pytest

import skillfoundry
from skillfoundry import (
    ACCEPTANCE_COVERAGE_PLAN_REF,
    ACCEPTANCE_COVERAGE_RESULT_REF,
    AcceptanceCriteriaPlanner,
    AcceptanceCoverageEvaluator,
    AcceptanceCriteriaSet,
    AcceptanceCriterion,
    LocalSkillRegistry,
    QALab,
    RegistryGateError,
    SkillSpec,
    Verifier,
    initialize_job_workspace,
    sha256_file,
)
from skillfoundry.worker import WorkerAdapter, WorkerExecutionOutcome


GOOD_SKILL_MD = """---
name: acceptance-good-skill
description: Deterministic acceptance coverage fixture.
references:
  - references/guide.md
scripts:
  - scripts/helper.py
---

# Acceptance Good Skill

## Overview

This package gives deterministic pytest repair triage with local evidence only.

## When To Use

- Use when a developer asks for deterministic pytest failure triage in a local repository.

## When Not To Use

- Do not use when the request requires deployment, live providers, or network debugging.

## Inputs

- A pytest failure log, repository path, and locked worker input manifest.

## Outputs

- A concise repair plan, changed-file summary, and verification command list.

## Workflow

1. Read the pytest failure log and repository path from the locked input manifest.
2. Compare the failing assertion with nearby source code and tests.
3. Return a repair plan with exact verification commands.

## Safety

- Do not run network commands or live providers during triage.
- Keep helper scripts under package/scripts.
"""


WEAK_SKILL_MD = """---
name: acceptance-weak-skill
description: Structurally valid but behaviorally weak fixture.
references:
  - references/guide.md
scripts:
  - scripts/helper.py
---

# Acceptance Weak Skill

## Overview

This package has every required verifier section but avoids useful specifics.

## When To Use

- Use when needed.

## When Not To Use

- Do not use otherwise.

## Inputs

- Any input.

## Outputs

- Useful output.

## Workflow

Do it.

## Safety

Be safe.
"""


class AcceptanceFixtureWorker:
    def __init__(self, skill_md: str = GOOD_SKILL_MD) -> None:
        self.skill_md = skill_md

    @property
    def worker_type(self) -> str:
        return "test:acceptance-fixture"

    def run(self, context):
        context.write_text("package/SKILL.md", self.skill_md)
        context.write_text("package/references/guide.md", "# Guide\n\nLocal deterministic guide.\n")
        context.write_text("package/scripts/helper.py", "def helper() -> str:\n    return 'ok'\n")
        return WorkerExecutionOutcome(
            status="completed",
            exit_status="success",
            summary="Acceptance fixture worker wrote a package candidate.",
            artifacts=[
                "package/SKILL.md",
                "package/references/guide.md",
                "package/scripts/helper.py",
            ],
            transcript_lines=["wrote acceptance fixture package"],
            usage_unavailable_reason="Acceptance fixture worker does not call model providers.",
        )


def skill_spec(job_id: str) -> SkillSpec:
    return SkillSpec(
        skill_id=f"{job_id}-skill",
        title="Deterministic pytest repair triage",
        description="Acceptance coverage fixture SkillSpec.",
        trigger_scenarios=["A developer asks for deterministic pytest failure triage."],
        non_trigger_scenarios=["The request requires deployment, live providers, or network debugging."],
        required_inputs=["A pytest failure log and repository path."],
        expected_outputs=["A concise repair plan and verification command list."],
        constraints=["No network calls.", "No live provider calls."],
        acceptance_criteria=["Report concrete workflow, safety, and IO contract evidence."],
        reference_materials=[],
        security_notes=["Helper scripts must remain under package/scripts."],
    )


def criterion(criterion_id: str, **overrides) -> AcceptanceCriterion:
    payload = {
        "id": criterion_id,
        "description": f"{criterion_id} is deterministically covered.",
        "source_requirement": "Build a deterministic local skill.",
        "source_turn_ids": ["turn-001"],
        "requirement_id": f"REQ-{criterion_id}",
        "test_method": "static",
        "pass_condition": "The mapped deterministic evidence passes.",
        "failure_examples": ["Evidence is missing."],
        "required_evidence": [],
        "evidence_kind": "verifier_check",
        "priority": "must",
        "risk_tags": [],
        "data_sensitivity": "internal",
        "coverage_status": "planned",
        "verifier_check_id": "package_skill_md_present",
    }
    payload.update(overrides)
    return AcceptanceCriterion(**payload)


def write_criteria(workspace, criteria: list[AcceptanceCriterion]) -> None:
    AcceptanceCriteriaSet(criteria=criteria, job_id=workspace.job_id).write_yaml_file(
        workspace.resolve_path("acceptance_criteria.yaml")
    )


def make_workspace(
    tmp_path,
    *,
    job_id: str,
    skill_md: str = GOOD_SKILL_MD,
    criteria: list[AcceptanceCriterion] | None = None,
):
    workspace = initialize_job_workspace(
        tmp_path / "runs",
        job_id,
        skill_spec=skill_spec(job_id),
    )
    if criteria is not None:
        write_criteria(workspace, criteria)
    WorkerAdapter(AcceptanceFixtureWorker(skill_md)).invoke(workspace, "001")
    return workspace


def make_verified_qa_workspace(
    tmp_path,
    *,
    job_id: str,
    skill_md: str = GOOD_SKILL_MD,
    criteria: list[AcceptanceCriterion] | None = None,
):
    workspace = make_workspace(tmp_path, job_id=job_id, skill_md=skill_md, criteria=criteria)
    verification = Verifier().verify(workspace)
    assert verification.passed is True
    qa_result = QALab().evaluate(workspace)
    return workspace, verification, qa_result


def plan_and_evaluate(workspace):
    plan = AcceptanceCriteriaPlanner().plan(workspace)
    result = AcceptanceCoverageEvaluator().evaluate(workspace, plan=plan)
    return plan, result


def read_json(workspace, ref: str):
    return json.loads(workspace.resolve_path(ref, must_exist=True).read_text(encoding="utf-8"))


def write_manual_acceptance_record(workspace, criterion_ids: list[str], *, decision: str = "approved") -> None:
    payload = {
        "schema_version": "skillfoundry.manual_acceptance_record.v1",
        "reviewer_id": "qa-reviewer-001",
        "reviewer_role": "qa_lead",
        "decision": decision,
        "reason": "Manual acceptance reviewed the listed must criteria.",
        "covered_criterion_ids": criterion_ids,
        "source_hash": sha256_file(workspace.resolve_path("acceptance_criteria.yaml", must_exist=True)),
        "created_at": "2026-05-21T00:00:00Z",
    }
    path = workspace.resolve_path("qa/manual_acceptance_record.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def result_item(result, criterion_id: str):
    return next(item for item in result.items if item.criterion_id == criterion_id)


def test_acceptance_coverage_api_is_exported():
    assert skillfoundry.AcceptanceCriteriaPlanner is AcceptanceCriteriaPlanner
    assert skillfoundry.AcceptanceCoverageEvaluator is AcceptanceCoverageEvaluator
    assert skillfoundry.ACCEPTANCE_COVERAGE_PLAN_REF == ACCEPTANCE_COVERAGE_PLAN_REF
    assert skillfoundry.ACCEPTANCE_COVERAGE_RESULT_REF == ACCEPTANCE_COVERAGE_RESULT_REF


def test_planner_maps_every_criterion_to_one_plan_item(tmp_path):
    workspace = make_workspace(
        tmp_path,
        job_id="acceptance-plan",
        criteria=[
            criterion("AC-VERIFIER", verifier_check_id="package_skill_md_present"),
            criterion(
                "AC-FIXTURE",
                test_method="fixture",
                evidence_kind="file",
                verifier_check_id=None,
                fixture_ref="qa/fixtures/input.md",
            ),
            criterion(
                "AC-EVIDENCE",
                evidence_kind="file",
                verifier_check_id=None,
                required_evidence=["qa/evidence/output.md"],
            ),
            criterion(
                "AC-QA",
                evidence_kind="qa_report",
                verifier_check_id=None,
                required_evidence=["workflow_actionability"],
            ),
            criterion(
                "AC-MANUAL",
                test_method="manual_check",
                evidence_kind="human_note",
                verifier_check_id=None,
                manual_authority="qa-lead",
            ),
            criterion(
                "AC-UNCOVERED",
                verifier_check_id=None,
                coverage_status="uncovered",
                unverifiable_reason="fixture not available",
            ),
        ],
    )

    plan = AcceptanceCriteriaPlanner().plan(workspace)
    payload = read_json(workspace, ACCEPTANCE_COVERAGE_PLAN_REF)

    assert payload["schema_version"] == skillfoundry.ACCEPTANCE_COVERAGE_PLAN_VERSION
    assert {item.criterion_id for item in plan.items} == {
        "AC-VERIFIER",
        "AC-FIXTURE",
        "AC-EVIDENCE",
        "AC-QA",
        "AC-MANUAL",
        "AC-UNCOVERED",
    }
    assert {item["criterion_id"] for item in payload["items"]} == {item.criterion_id for item in plan.items}
    assert len(plan.items) == 6


def test_good_skill_with_qa_and_verifier_evidence_passes_must_criteria(tmp_path):
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-good",
        criteria=[
            criterion("AC-VERIFIER", verifier_check_id="package_skill_md_present"),
            criterion(
                "AC-QA",
                evidence_kind="qa_report",
                verifier_check_id=None,
                required_evidence=["workflow_actionability"],
            ),
        ],
    )

    _plan, result = plan_and_evaluate(workspace)
    payload = read_json(workspace, ACCEPTANCE_COVERAGE_RESULT_REF)

    assert result.passed is True
    assert payload["passed"] is True
    assert payload["must_total"] == 2
    assert payload["must_passed"] == 2
    assert all(item.status == "covered/pass" for item in result.items)


def test_bad_skill_fails_mapped_must_criterion(tmp_path):
    workspace, _verification, qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-bad",
        skill_md=WEAK_SKILL_MD,
        criteria=[
            criterion(
                "AC-QA-WORKFLOW",
                evidence_kind="qa_report",
                verifier_check_id=None,
                required_evidence=["workflow_actionability"],
            )
        ],
    )
    assert qa.passed is False

    _plan, result = plan_and_evaluate(workspace)

    assert result.passed is False
    assert result.must_failed == 1
    item = result_item(result, "AC-QA-WORKFLOW")
    assert item.status == "covered/fail"
    assert item.passed is False


def test_uncovered_must_criterion_fails_overall(tmp_path):
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-uncovered",
        criteria=[
            criterion(
                "AC-UNCOVERED",
                verifier_check_id=None,
                coverage_status="uncovered",
                unverifiable_reason="no deterministic artifact exists",
            )
        ],
    )

    _plan, result = plan_and_evaluate(workspace)

    assert result.passed is False
    assert result_item(result, "AC-UNCOVERED").status == "uncovered"


def test_manual_only_must_criterion_requires_manual_authority_metadata(tmp_path):
    missing_authority, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-manual-missing",
        criteria=[
            criterion(
                "AC-MANUAL",
                test_method="manual_check",
                evidence_kind="human_note",
                verifier_check_id=None,
            )
        ],
    )
    _plan, missing_result = plan_and_evaluate(missing_authority)

    assert missing_result.passed is False
    assert result_item(missing_result, "AC-MANUAL").status == "uncovered"

    with_authority, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-manual-present",
        criteria=[
            criterion(
                "AC-MANUAL",
                test_method="manual_check",
                evidence_kind="human_note",
                verifier_check_id=None,
                manual_authority="human-qa-lead",
            )
        ],
    )
    _plan, present_result = plan_and_evaluate(with_authority)

    assert present_result.passed is False
    assert result_item(present_result, "AC-MANUAL").status == "uncovered"

    write_manual_acceptance_record(with_authority, ["AC-MANUAL"])
    _plan, approved_result = plan_and_evaluate(with_authority)

    assert approved_result.passed is True
    assert approved_result.must_manual_only == 1
    assert result_item(approved_result, "AC-MANUAL").status == "manual_only"
    assert result_item(approved_result, "AC-MANUAL").evidence_refs == ["qa/manual_acceptance_record.json"]


def test_llm_only_must_criterion_cannot_be_registry_approved(tmp_path):
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-llm-only",
        criteria=[
            criterion(
                "AC-LLM",
                test_method="llm_judge",
                evidence_kind="model_judge",
                verifier_check_id=None,
                required_evidence=["model_judge"],
            )
        ],
    )
    _plan, result = plan_and_evaluate(workspace)
    assert result.passed is False

    registry = LocalSkillRegistry(tmp_path / "registry.json")
    with pytest.raises(RegistryGateError) as exc_info:
        registry.add_verified(workspace, version="1.0.0")

    assert any("acceptance_coverage_result.passed" in failure for failure in exc_info.value.failures)


def test_qa_lab_report_includes_acceptance_coverage_summary_when_result_exists(tmp_path):
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-qa-summary",
        criteria=[criterion("AC-VERIFIER", verifier_check_id="package_skill_md_present")],
    )
    _plan, coverage = plan_and_evaluate(workspace)

    qa_result = QALab().evaluate(workspace)
    report = read_json(workspace, "qa/quality_report.json")

    assert qa_result.report["acceptance_coverage"]["result_id"] == coverage.result_id
    assert report["acceptance_coverage"]["passed"] is True
    assert report["acceptance_coverage"]["ref"] == ACCEPTANCE_COVERAGE_RESULT_REF
    assert report["acceptance_coverage"]["sha256"] == sha256_file(
        workspace.resolve_path(ACCEPTANCE_COVERAGE_RESULT_REF, must_exist=True)
    )


def test_registry_rejects_missing_or_failed_coverage_result_when_acceptance_exists(tmp_path):
    missing = make_workspace(
        tmp_path,
        job_id="acceptance-registry-missing",
        criteria=[criterion("AC-VERIFIER", verifier_check_id="package_skill_md_present")],
    )
    Verifier().verify(missing)
    QALab().evaluate(missing)
    registry = LocalSkillRegistry(tmp_path / "registry-missing.json")

    with pytest.raises(RegistryGateError) as missing_exc:
        registry.add_verified(missing, version="1.0.0")
    assert any("acceptance_coverage_result" in failure for failure in missing_exc.value.failures)

    failed, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-registry-failed",
        criteria=[
            criterion(
                "AC-UNCOVERED",
                verifier_check_id=None,
                coverage_status="uncovered",
                unverifiable_reason="no deterministic artifact exists",
            )
        ],
    )
    _plan, failed_result = plan_and_evaluate(failed)
    assert failed_result.passed is False

    with pytest.raises(RegistryGateError) as failed_exc:
        LocalSkillRegistry(tmp_path / "registry-failed.json").add_verified(failed, version="1.0.0")
    assert any("acceptance_coverage_result.passed" in failure for failure in failed_exc.value.failures)


def test_registry_accepts_passed_coverage_result_and_stores_hash_provenance(tmp_path):
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-registry-pass",
        criteria=[criterion("AC-VERIFIER", verifier_check_id="package_skill_md_present")],
    )
    _plan, coverage = plan_and_evaluate(workspace)
    registry = LocalSkillRegistry(tmp_path / "registry-pass.json")

    entry = registry.add_verified(workspace, version="1.0.0")
    provenance = entry.provenance["acceptance_coverage_result"]

    assert coverage.passed is True
    assert provenance["ref"] == ACCEPTANCE_COVERAGE_RESULT_REF
    assert provenance["passed"] is True
    assert provenance["result_id"] == coverage.result_id
    assert provenance["sha256"] == sha256_file(workspace.resolve_path(ACCEPTANCE_COVERAGE_RESULT_REF, must_exist=True))
    assert registry.verify_entry(entry).valid is True


def test_registry_verifies_manual_acceptance_record_for_manual_only_must_criteria(tmp_path):
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-registry-manual",
        criteria=[
            criterion(
                "AC-MANUAL",
                test_method="manual_check",
                evidence_kind="human_note",
                verifier_check_id=None,
                manual_authority="human-qa-lead",
            )
        ],
    )
    write_manual_acceptance_record(workspace, ["AC-MANUAL"])
    _plan, coverage = plan_and_evaluate(workspace)
    assert coverage.passed is True

    registry = LocalSkillRegistry(tmp_path / "registry-manual.json")
    entry = registry.add_verified(workspace, version="1.0.0")
    provenance = entry.provenance["acceptance_coverage_result"]["provenance"]["manual_acceptance_record"]
    assert provenance["ref"] == "qa/manual_acceptance_record.json"
    assert provenance["sha256"] == sha256_file(workspace.resolve_path("qa/manual_acceptance_record.json", must_exist=True))
    assert registry.verify_entry(entry).valid is True

    record_path = workspace.resolve_path("qa/manual_acceptance_record.json", must_exist=True)
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    payload["decision"] = "rejected"
    record_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    report = registry.verify_entry(entry)

    assert report.valid is False
    assert any("manual_acceptance_record_hash" in failure for failure in report.failures)
    assert any("manual_acceptance_record.decision" in failure for failure in report.failures)


def test_registry_verify_fails_after_acceptance_coverage_result_tampering(tmp_path):
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-registry-tamper",
        criteria=[criterion("AC-VERIFIER", verifier_check_id="package_skill_md_present")],
    )
    _plan, _coverage = plan_and_evaluate(workspace)
    registry = LocalSkillRegistry(tmp_path / "registry-tamper.json")
    entry = registry.add_verified(workspace, version="1.0.0")

    result_path = workspace.resolve_path(ACCEPTANCE_COVERAGE_RESULT_REF, must_exist=True)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["passed"] = False
    result_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    report = registry.verify_entry(entry)

    assert report.valid is False
    assert any("acceptance_coverage_result_hash" in failure for failure in report.failures)
    assert any("acceptance_coverage_result.passed" in failure for failure in report.failures)
