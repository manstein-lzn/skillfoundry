from __future__ import annotations

import json

import pytest

from skillfoundry import (
    LocalSkillRegistry,
    SkillSpec,
    Verifier,
    initialize_job_workspace,
    sha256_file,
)
import skillfoundry.feedback as feedback_module
from skillfoundry.feedback import (
    FeedbackRecord,
    FeedbackRepairPlan,
    FeedbackVersionGateError,
    SkillVersionManager,
)
from skillfoundry.qa import QALab
from skillfoundry.worker import WorkerAdapter, WorkerExecutionOutcome


GOOD_SKILL_MD = """---
name: feedback-skill
description: Deterministic feedback/versioning fixture.
references:
  - references/guide.md
scripts:
  - scripts/helper.py
---

# Feedback Skill

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


REPAIRED_SKILL_MD = GOOD_SKILL_MD.replace(
    "This package gives deterministic pytest repair triage with local evidence only.",
    "This repaired package gives deterministic pytest repair triage with explicit failed-case handling.",
)


WEAK_SKILL_MD = """---
name: feedback-weak-skill
description: Structurally valid but behaviorally weak fixture.
references:
  - references/guide.md
scripts:
  - scripts/helper.py
---

# Feedback Weak Skill

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


SAFE_SCRIPT = """def helper() -> str:
    return "ok"
"""


class FeedbackFixtureWorker:
    def __init__(self, skill_md: str = GOOD_SKILL_MD) -> None:
        self.skill_md = skill_md

    @property
    def worker_type(self) -> str:
        return "test:feedback-fixture"

    def run(self, context):
        context.write_text("package/SKILL.md", self.skill_md)
        context.write_text("package/references/guide.md", "# Feedback Guide\n\nLocal deterministic guide.\n")
        context.write_text("package/scripts/helper.py", SAFE_SCRIPT)
        return WorkerExecutionOutcome(
            status="completed",
            exit_status="success",
            summary="Feedback fixture worker wrote a package candidate.",
            artifacts=[
                "package/SKILL.md",
                "package/references/guide.md",
                "package/scripts/helper.py",
            ],
            transcript_lines=["wrote feedback fixture package"],
            usage_unavailable_reason="Feedback fixture worker does not call model providers.",
        )


def feedback_skill_spec(skill_id: str = "feedback-skill") -> SkillSpec:
    return SkillSpec(
        skill_id=skill_id,
        title="Deterministic pytest repair triage",
        description="Feedback/versioning fixture SkillSpec with concrete trigger and contract expectations.",
        trigger_scenarios=["A developer asks for deterministic pytest failure triage."],
        non_trigger_scenarios=["The request requires deployment, live providers, or network debugging."],
        required_inputs=["A pytest failure log and repository path."],
        expected_outputs=["A concise repair plan and verification command list."],
        constraints=["No network calls.", "No live provider calls."],
        acceptance_criteria=["Report concrete workflow, safety, and IO contract evidence."],
        reference_materials=[],
        security_notes=["Helper scripts must remain under package/scripts."],
    )


def make_workspace(tmp_path, *, job_id: str, skill_md: str = GOOD_SKILL_MD):
    workspace = initialize_job_workspace(
        tmp_path / "runs",
        job_id,
        skill_spec=feedback_skill_spec(),
        overwrite=True,
    )
    WorkerAdapter(FeedbackFixtureWorker(skill_md)).invoke(workspace, "001")
    return workspace


def make_verified_workspace(tmp_path, *, job_id: str, skill_md: str = GOOD_SKILL_MD):
    workspace = make_workspace(tmp_path, job_id=job_id, skill_md=skill_md)
    verification = Verifier().verify(workspace)
    assert verification.passed is True
    return workspace, verification


def make_source(tmp_path):
    registry_path = tmp_path / "registry.json"
    workspace, _verification = make_verified_workspace(tmp_path, job_id="feedback-source")
    registry = LocalSkillRegistry(registry_path)
    entry = registry.add_verified(workspace, version="1.0.0")
    return registry_path, workspace, entry


def make_feedback(source_entry) -> FeedbackRecord:
    return FeedbackRecord(
        feedback_id="fb-001",
        skill_id=source_entry.skill_id,
        source_version=source_entry.version,
        source_build_job_id=source_entry.build_job_id,
        reporter="internal-tester",
        channel="api",
        severity="high",
        rating=1,
        summary="The skill misses the concrete pytest repair failure case.",
        failed_usage_case="Triage a deterministic pytest assertion failure after a local code change.",
        expected_behavior="Identify the failing assertion and propose a local repair with verification commands.",
        actual_behavior="Returned generic advice without mapping the assertion to source or tests.",
        evidence_refs=["usage/failure-001.json", "transcripts/session-001.log"],
        created_at="2026-05-17T00:00:00Z",
    )


def make_plan(tmp_path, *, suggested_new_version: str = "1.1.0", repair_job_id: str = "feedback-repair"):
    registry_path, source_workspace, source_entry = make_source(tmp_path)
    manager = SkillVersionManager(registry_path, runs_root=tmp_path / "runs")
    feedback = make_feedback(source_entry)
    plan = manager.plan_repair_from_feedback(
        feedback,
        source_entry,
        suggested_new_version=suggested_new_version,
        target_repair_job_id=repair_job_id,
    )
    return manager, source_workspace, source_entry, feedback, plan


def make_repaired_workspace(
    tmp_path,
    plan: FeedbackRepairPlan,
    *,
    skill_md: str = REPAIRED_SKILL_MD,
    qa: bool = True,
):
    workspace, verification = make_verified_workspace(tmp_path, job_id=plan.target_repair_job_id, skill_md=skill_md)
    qa_result = QALab().evaluate(workspace) if qa else None
    return workspace, verification, qa_result


def test_feedback_api_is_module_scoped():
    assert feedback_module.FeedbackRecord is FeedbackRecord
    assert feedback_module.FeedbackRepairPlan is FeedbackRepairPlan
    assert feedback_module.SkillVersionManager is SkillVersionManager


def test_feedback_record_json_round_trip(tmp_path):
    _registry_path, _workspace, source_entry = make_source(tmp_path)
    feedback = make_feedback(source_entry)
    path = tmp_path / "feedback.json"

    feedback.write_json_file(path)
    loaded = FeedbackRecord.read_json_file(path)

    assert loaded.to_dict() == feedback.to_dict()
    assert json.loads(path.read_text(encoding="utf-8"))["failed_usage_case"] == feedback.failed_usage_case


def test_feedback_creates_durable_repair_version_plan(tmp_path):
    manager, _source_workspace, source_entry, feedback, plan = make_plan(tmp_path)

    repair_dir = manager.runs_root / plan.target_repair_job_id
    plan_path = repair_dir / "feedback_repair_plan.json"
    feedback_path = repair_dir / "feedback_record.json"
    loaded = FeedbackRepairPlan.read_json_file(plan_path)

    assert plan_path.is_file()
    assert feedback_path.is_file()
    assert loaded.to_dict() == plan.to_dict()
    assert plan.feedback_id == feedback.feedback_id
    assert plan.source_registry_entry_ref == f"{source_entry.skill_id}@{source_entry.version}"
    assert plan.source_package_hash == source_entry.package_hash
    assert plan.suggested_new_version == "1.1.0"
    assert plan.target_repair_job_id == "feedback-repair"
    assert plan.feedback_hash == sha256_file(feedback_path)
    assert "LocalSkillRegistry.add_verified" in plan.required_gates


def test_repaired_version_registration_requires_verifier_and_qa_pass(tmp_path):
    manager, _source_workspace, source_entry, feedback, plan = make_plan(tmp_path)
    workspace, verification = make_verified_workspace(
        tmp_path,
        job_id=plan.target_repair_job_id,
        skill_md=REPAIRED_SKILL_MD,
    )
    assert verification.passed is True

    with pytest.raises(FeedbackVersionGateError) as missing_qa:
        manager.register_repaired_version(workspace, feedback, source_entry, version="1.1.0", plan=plan)
    assert any("qa_lab" in failure for failure in missing_qa.value.failures)

    qa_result = QALab().evaluate(workspace)
    assert qa_result.passed is True

    result = manager.register_repaired_version(workspace, feedback, source_entry, version="1.1.0", plan=plan)

    assert result.registry_entry.version == "1.1.0"
    assert result.registry_entry.skill_id == source_entry.skill_id
    assert result.registry_entry.package_hash == verification.package_hash
    assert result.version_change_report_path.is_file()
    assert result.version_change_report["gates"]["verifier"]["passed"] is True
    assert result.version_change_report["gates"]["qa_lab"]["passed"] is True


def test_repaired_version_provenance_links_feedback_plan_gates_and_registry_entry(tmp_path):
    manager, _source_workspace, source_entry, feedback, plan = make_plan(tmp_path)
    workspace, verification, qa_result = make_repaired_workspace(tmp_path, plan)
    assert qa_result is not None and qa_result.passed is True

    result = manager.register_repaired_version(workspace, feedback, source_entry, version="1.1.0", plan=plan)
    entry = LocalSkillRegistry(manager.registry_path).get(source_entry.skill_id, "1.1.0")
    provenance = entry.provenance["feedback_versioning"]

    assert result.registry_entry.to_dict() == entry.to_dict()
    assert provenance["source"]["version"] == source_entry.version
    assert provenance["source"]["package_hash"] == source_entry.package_hash
    assert provenance["feedback_record"]["feedback_id"] == feedback.feedback_id
    assert provenance["repair_plan"]["plan_id"] == plan.plan_id
    assert provenance["repair_job"]["job_id"] == workspace.job_id
    assert provenance["gates"]["verifier"]["result_id"] == verification.result_id
    assert provenance["gates"]["verifier"]["ref"] == "verifier/verification_result.json"
    assert provenance["gates"]["qa_lab"]["ref"] == "qa/quality_report.json"
    assert provenance["gates"]["qa_lab"]["passed"] is True
    assert provenance["gates"]["registry"]["method"] == "LocalSkillRegistry.add_verified"
    assert provenance["new_registry_entry"]["version"] == "1.1.0"
    assert provenance["new_registry_entry"]["package_hash"] == entry.package_hash
    assert LocalSkillRegistry(manager.registry_path).verify(entry.skill_id, entry.version).valid is True


def test_qa_failed_repaired_version_cannot_register_even_when_verifier_passes(tmp_path):
    manager, _source_workspace, source_entry, feedback, plan = make_plan(tmp_path)
    workspace, verification = make_verified_workspace(
        tmp_path,
        job_id=plan.target_repair_job_id,
        skill_md=WEAK_SKILL_MD,
    )
    assert verification.passed is True
    qa_result = QALab().evaluate(workspace)
    assert qa_result.passed is False

    with pytest.raises(FeedbackVersionGateError) as exc_info:
        manager.register_repaired_version(workspace, feedback, source_entry, version="1.1.0", plan=plan)

    assert any("qa_lab.passed" in failure for failure in exc_info.value.failures)
    versions = [entry.version for entry in LocalSkillRegistry(manager.registry_path).list(include_quarantined=True)]
    assert versions == ["1.0.0"]


def test_quarantine_helper_excludes_old_version_from_default_reuse_candidates(tmp_path):
    manager, _source_workspace, source_entry, _feedback, _plan = make_plan(tmp_path)

    quarantined = manager.quarantine_version(
        source_entry.skill_id,
        source_entry.version,
        "feedback repair superseded it",
    )

    registry = LocalSkillRegistry(manager.registry_path)
    assert quarantined.quarantine_status == "quarantined"
    assert registry.reuse_candidates() == []
    assert registry.list() == []
    assert [entry.version for entry in registry.list(status="quarantined")] == ["1.0.0"]


def test_rollback_event_is_recorded_without_modifying_package_content(tmp_path):
    manager, source_workspace, source_entry, feedback, plan = make_plan(tmp_path)
    repaired_workspace, _verification, qa_result = make_repaired_workspace(tmp_path, plan)
    assert qa_result is not None and qa_result.passed is True
    new_entry = manager.register_repaired_version(
        repaired_workspace,
        feedback,
        source_entry,
        version="1.1.0",
        plan=plan,
    ).registry_entry

    source_skill_path = source_workspace.resolve_path("package/SKILL.md", must_exist=True)
    repaired_skill_path = repaired_workspace.resolve_path("package/SKILL.md", must_exist=True)
    source_hash_before = sha256_file(source_skill_path)
    repaired_hash_before = sha256_file(repaired_skill_path)

    event, event_path = manager.record_rollback(
        restored_entry=source_entry,
        rolled_back_from_entry=new_entry,
        reason="new version produced a regression in internal usage",
        workspace=repaired_workspace,
    )

    assert event_path.is_file()
    assert event["event"] == "rollback_preferred_version_restored"
    assert event["preferred_version"] == source_entry.version
    assert event["package_mutation"] is False
    assert sha256_file(source_skill_path) == source_hash_before
    assert sha256_file(repaired_skill_path) == repaired_hash_before
