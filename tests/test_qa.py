from __future__ import annotations

import json

from skillfoundry import (
    SkillSpec,
    Verifier,
    initialize_job_workspace,
)
import skillfoundry.qa as qa_module
from skillfoundry.qa import HARD_CHECK_NAMES, QA_REPORT_VERSION, QALab
from skillfoundry.worker import WorkerAdapter, WorkerExecutionOutcome


GOOD_SKILL_MD = """---
name: qa-strong-skill
description: Deterministic QA Lab passing fixture.
references:
  - references/guide.md
scripts:
  - scripts/helper.py
---

# QA Strong Skill

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
name: qa-weak-skill
description: Structurally valid but behaviorally weak QA fixture.
references:
  - references/guide.md
scripts:
  - scripts/helper.py
---

# QA Weak Skill

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


UNSAFE_SCRIPT = """import subprocess

subprocess.run(["curl", "https://example.com"], check=False)
"""


class QAFixtureWorker:
    def __init__(self, skill_md: str, *, script_text: str = SAFE_SCRIPT) -> None:
        self.skill_md = skill_md
        self.script_text = script_text

    @property
    def worker_type(self) -> str:
        return "test:qa-fixture"

    def run(self, context):
        context.write_text("package/SKILL.md", self.skill_md)
        context.write_text("package/references/guide.md", "# QA Guide\n\nLocal deterministic guide.\n")
        context.write_text("package/scripts/helper.py", self.script_text)
        return WorkerExecutionOutcome(
            status="completed",
            exit_status="success",
            summary="QA fixture worker wrote a package candidate.",
            artifacts=[
                "package/SKILL.md",
                "package/references/guide.md",
                "package/scripts/helper.py",
            ],
            transcript_lines=["wrote QA fixture package"],
            usage_unavailable_reason="QA fixture worker does not call model providers.",
        )


def qa_skill_spec(job_id: str) -> SkillSpec:
    return SkillSpec(
        skill_id=f"{job_id}-skill",
        title="Deterministic pytest repair triage",
        description="QA Lab fixture SkillSpec with concrete trigger and contract expectations.",
        trigger_scenarios=["A developer asks for deterministic pytest failure triage."],
        non_trigger_scenarios=["The request requires deployment, live providers, or network debugging."],
        required_inputs=["A pytest failure log and repository path."],
        expected_outputs=["A concise repair plan and verification command list."],
        constraints=["No network calls.", "No live provider calls."],
        acceptance_criteria=["Report concrete workflow, safety, and IO contract evidence."],
        reference_materials=[],
        security_notes=["Helper scripts must remain under package/scripts."],
    )


def make_workspace(
    tmp_path,
    *,
    job_id: str,
    skill_md: str = GOOD_SKILL_MD,
    script_text: str = SAFE_SCRIPT,
):
    workspace = initialize_job_workspace(
        tmp_path / "runs",
        job_id,
        skill_spec=qa_skill_spec(job_id),
    )
    WorkerAdapter(QAFixtureWorker(skill_md, script_text=script_text)).invoke(workspace, "001")
    return workspace


def make_verified_workspace(
    tmp_path,
    *,
    job_id: str,
    skill_md: str = GOOD_SKILL_MD,
    script_text: str = SAFE_SCRIPT,
):
    workspace = make_workspace(tmp_path, job_id=job_id, skill_md=skill_md, script_text=script_text)
    verification = Verifier().verify(workspace)
    assert verification.passed is True
    return workspace, verification


def read_report(result):
    return json.loads(result.report_path.read_text(encoding="utf-8"))


def check_by_name(report, name: str):
    return [check for check in report["checks"] if check["name"] == name]


def failed_check_names(report) -> set[str]:
    return {check["name"] for check in report["checks"] if check["passed"] is False}


def test_qa_lab_api_is_module_scoped():
    assert qa_module.QALab is QALab
    assert qa_module.QA_REPORT_VERSION == QA_REPORT_VERSION


def test_good_verifier_passed_package_passes_qa_lab_and_writes_report(tmp_path):
    workspace, verification = make_verified_workspace(tmp_path, job_id="qa-good")

    result = QALab().evaluate(workspace)
    report = read_report(result)

    assert result.passed is True
    assert report == result.report
    assert report["schema_version"] == QA_REPORT_VERSION
    assert report["job_id"] == "qa-good"
    assert report["passed"] is True
    assert report["hard_gate_passed"] is True
    assert report["quality_score"] == 100.0
    assert report["package_hash"] == verification.package_hash
    assert report["verifier_result_ref"] == "verifier/verification_result.json"
    assert report["verifier_result_hash"]
    assert report["verifier_result"]["passed"] is True
    assert result.report_path == workspace.resolve_path("qa/quality_report.json", must_exist=True)
    assert {check["name"] for check in report["checks"]} == set(HARD_CHECK_NAMES)
    assert all(check["passed"] is True for check in report["checks"])


def test_structurally_valid_but_behaviorally_weak_package_fails_deterministic_checks(tmp_path):
    workspace, verification = make_verified_workspace(tmp_path, job_id="qa-weak", skill_md=WEAK_SKILL_MD)
    assert verification.passed is True

    result = QALab().evaluate(workspace)
    report = read_report(result)

    assert result.passed is False
    assert "verifier_passed" not in failed_check_names(report)
    assert {
        "trigger_fixture_coverage",
        "non_trigger_fixture_coverage",
        "io_contract_coverage",
        "workflow_actionability",
        "safety_actionability",
    }.issubset(failed_check_names(report))
    assert report["quality_score"] < 100.0


def test_trigger_and_non_trigger_fixture_results_are_present(tmp_path):
    workspace, _verification = make_verified_workspace(tmp_path, job_id="qa-fixtures")

    report = read_report(QALab().evaluate(workspace))

    assert report["trigger_fixture_results"]
    assert report["non_trigger_fixture_results"]
    assert report["trigger_fixture_results"][0]["source_ref"] == "skill_spec.yaml"
    assert report["non_trigger_fixture_results"][0]["source_ref"] == "skill_spec.yaml"
    assert all(item["passed"] is True for item in report["trigger_fixture_results"])
    assert all(item["passed"] is True for item in report["non_trigger_fixture_results"])


def test_input_output_contract_results_are_present(tmp_path):
    workspace, _verification = make_verified_workspace(tmp_path, job_id="qa-contracts")

    report = read_report(QALab().evaluate(workspace))

    assert report["input_contract_results"]
    assert report["output_contract_results"]
    assert report["input_output_contract_results"]["required_inputs"] == report["input_contract_results"]
    assert report["input_output_contract_results"]["expected_outputs"] == report["output_contract_results"]
    assert all(item["passed"] is True for item in report["input_contract_results"])
    assert all(item["passed"] is True for item in report["output_contract_results"])


def test_script_smoke_passes_safe_scripts_and_fails_unsafe_script_content(tmp_path):
    safe_workspace, _verification = make_verified_workspace(tmp_path, job_id="qa-safe-script")
    safe_report = read_report(QALab().evaluate(safe_workspace))

    assert check_by_name(safe_report, "script_smoke")[0]["passed"] is True
    assert safe_report["script_smoke_results"]["passed"] is True
    assert safe_report["script_smoke_results"]["scripts"][0]["package_ref"] == "package/scripts/helper.py"

    unsafe_workspace, unsafe_verification = make_verified_workspace(
        tmp_path,
        job_id="qa-unsafe-script",
        script_text=UNSAFE_SCRIPT,
    )
    assert unsafe_verification.passed is True
    unsafe_report = read_report(QALab().evaluate(unsafe_workspace))

    assert unsafe_report["passed"] is False
    assert check_by_name(unsafe_report, "script_smoke")[0]["passed"] is False
    script_result = unsafe_report["script_smoke_results"]["scripts"][0]
    assert script_result["passed"] is False
    assert "subprocess" in script_result["unsafe_matches"]
    assert "repair.script_safety" in unsafe_report["failure_taxonomy"]["repair_classes"]


def test_positive_judge_signal_cannot_override_failed_hard_checks(tmp_path):
    class PositiveJudge:
        def evaluate(self, workspace, evidence):
            assert workspace.job_id == "qa-judge"
            assert evidence["failed_hard_checks"]
            return {"passed": True, "score": 1.0, "summary": "Auxiliary positive fixture."}

    workspace, _verification = make_verified_workspace(tmp_path, job_id="qa-judge", skill_md=WEAK_SKILL_MD)

    result = QALab(judge=PositiveJudge()).evaluate(workspace)
    report = read_report(result)

    assert result.passed is False
    assert report["hard_gate_passed"] is False
    assert report["judge_signal"]["present"] is True
    assert report["judge_signal"]["auxiliary"] is True
    assert report["judge_signal"]["passed"] is True
    assert report["judge_signal"]["overrode_hard_checks"] is False
    assert workspace.resolve_path("qa/judge_signal.json", must_exist=True).is_file()


def test_judge_signal_uses_compact_governed_evidence_without_raw_logs(tmp_path):
    captured = {}

    class CapturingJudge:
        def evaluate(self, workspace, evidence):
            captured.update(evidence)
            return {"passed": True, "score": 1.0, "summary": "Auxiliary positive fixture."}

    workspace, _verification = make_verified_workspace(tmp_path, job_id="qa-governed-judge", skill_md=WEAK_SKILL_MD)

    report = read_report(QALab(judge=CapturingJudge()).evaluate(workspace))
    judge_payload = json.loads(workspace.resolve_path("qa/judge_signal.json", must_exist=True).read_text(encoding="utf-8"))

    assert report["judge_signal"]["present"] is True
    assert captured["schema_version"] == "skillfoundry.qa.judge_evidence.v1"
    assert "failed_hard_checks" in captured
    assert "hard_checks" in captured
    assert "raw_logs" not in captured
    assert "raw_worker_transcript" not in captured
    assert "skill_text" not in captured
    assert "package_content" not in captured
    assert judge_payload["governed_evidence"]["failed_hard_checks"] == captured["failed_hard_checks"]


def test_failure_taxonomy_includes_repair_driving_classes_for_failed_checks(tmp_path):
    workspace, _verification = make_verified_workspace(tmp_path, job_id="qa-taxonomy", skill_md=WEAK_SKILL_MD)

    report = read_report(QALab().evaluate(workspace))
    taxonomy = report["failure_taxonomy"]

    assert taxonomy["failed_checks"]
    assert {
        "repair.trigger_fixture_authoring",
        "repair.non_trigger_fixture_authoring",
        "repair.io_contract_authoring",
        "repair.workflow_steps",
        "repair.safety_constraints",
    }.issubset(set(taxonomy["repair_classes"]))
    for failed in taxonomy["failed_checks"]:
        assert failed["check_name"] in failed_check_names(report)
        assert failed["failure_class"]
        assert str(failed["repair_class"]).startswith("repair.")
        assert failed["repair_hint"]
