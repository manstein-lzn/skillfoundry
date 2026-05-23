from __future__ import annotations

import pytest

import skillfoundry
from skillfoundry import (
    VerificationResult,
    Verifier,
    initialize_job_workspace,
)
from skillfoundry.worker import WorkerAdapter, WorkerExecutionOutcome


VALID_SKILL_MD = """---
name: valid-verifier-skill
description: Deterministic verifier fixture.
references:
  - references/guide.md
scripts:
  - scripts/helper.py
---

# Valid Verifier Skill

## Overview

This fixture describes a complete local Codex Skill package.

## When To Use

- Use when the verifier needs a deterministic passing package.

## When Not To Use

- Do not use when the workspace has unsafe paths or missing locked inputs.

## Inputs

- A SkillFoundry build contract and worker input manifest.

## Outputs

- A machine-readable verification result and a reusable Skill package.

## Workflow

1. Read the locked inputs.
2. Inspect the package contents.
3. Return deterministic evidence.

## Safety

- Do not execute untrusted package scripts during verification.
"""


MISSING_SAFETY_SKILL_MD = VALID_SKILL_MD.replace(
    "\n## Safety\n\n- Do not execute untrusted package scripts during verification.\n",
    "",
)


UNSAFE_PATH_SKILL_MD = VALID_SKILL_MD.replace(
    "scripts:\n  - scripts/helper.py",
    "scripts:\n  - scripts/../escape.sh",
)

MALFORMED_FRONTMATTER_SKILL_MD = VALID_SKILL_MD.replace(
    "references:\n  - references/guide.md\nscripts:\n  - scripts/helper.py",
    "references: [unterminated",
)


INVALID_SKILL_MD = """# Invalid Builder Self Report Fixture

The worker says success, but this package is structurally incomplete.
"""


class FixtureSkillWorker:
    def __init__(self, skill_md: str, *, smoke_fail: bool = False) -> None:
        self.skill_md = skill_md
        self.smoke_fail = smoke_fail

    @property
    def worker_type(self) -> str:
        return "test:verifier-fixture"

    def run(self, context):
        context.write_text("package/SKILL.md", self.skill_md)
        context.write_text("package/references/guide.md", "# Guide\n\nReference fixture.\n")
        context.write_text("package/scripts/helper.py", "# helper fixture; never executed by verifier\n")
        if self.smoke_fail:
            context.write_text("package/tests/smoke.fail", "fail deterministic smoke\n")
        artifacts = [
            "package/SKILL.md",
            "package/references/guide.md",
            "package/scripts/helper.py",
        ]
        if self.smoke_fail:
            artifacts.append("package/tests/smoke.fail")
        return WorkerExecutionOutcome(
            status="completed",
            exit_status="success",
            summary="Fixture worker reported success; verifier must still inspect package.",
            artifacts=artifacts,
            transcript_lines=["wrote verifier fixture package"],
            usage_unavailable_reason="Fixture worker does not call model providers.",
        )


def make_workspace(tmp_path, *, skill_md: str = VALID_SKILL_MD, smoke_fail: bool = False):
    workspace = initialize_job_workspace(tmp_path / "runs", "verifier-001")
    WorkerAdapter(FixtureSkillWorker(skill_md, smoke_fail=smoke_fail)).invoke(workspace, "001")
    return workspace


def check_by_name(result: VerificationResult, name: str):
    return [check for check in result.checks if check["name"] == name]


def assert_failed_check(result: VerificationResult, name: str) -> None:
    checks = check_by_name(result, name)
    assert checks, f"missing check {name}"
    assert any(check["passed"] is False and check["severity"] == "error" for check in checks)


def test_verifier_api_is_exported():
    assert skillfoundry.Verifier is Verifier
    assert isinstance(skillfoundry.DEFAULT_REQUIRED_SKILL_SECTIONS, tuple)
    assert skillfoundry.VERIFIER_VERSION == "skillfoundry.verifier.wp4.v1"


def test_valid_package_passes_writes_result_and_round_trips(tmp_path):
    workspace = make_workspace(tmp_path)
    result = Verifier().verify(workspace)

    assert result.passed is True
    assert result.failures == []
    assert result.package_hash != "0" * 64
    assert result.verification_spec_hash != "0" * 64
    assert workspace.resolve_path("verifier/static_report.json", must_exist=True).is_file()
    assert workspace.resolve_path("verifier/sandbox.log", must_exist=True).is_file()

    result_path = workspace.resolve_path("verifier/verification_result.json", must_exist=True)
    loaded = VerificationResult.read_json_file(result_path)
    assert loaded.to_dict() == result.to_dict()

    second_result = Verifier().verify(workspace)
    assert second_result.to_dict() == result.to_dict()


def test_missing_skill_md_fails(tmp_path):
    workspace = make_workspace(tmp_path)
    workspace.resolve_path("package/SKILL.md", must_exist=True).unlink()

    result = Verifier().verify(workspace)

    assert result.passed is False
    assert_failed_check(result, "package_skill_md_present")
    assert_failed_check(result, "skill_required_section")
    assert workspace.resolve_path("verifier/verification_result.json", must_exist=True).is_file()


def test_missing_required_skill_section_fails(tmp_path):
    workspace = make_workspace(tmp_path, skill_md=MISSING_SAFETY_SKILL_MD)

    result = Verifier().verify(workspace)

    assert result.passed is False
    assert_failed_check(result, "skill_required_section")
    assert any("Safety" in failure for failure in result.failures)


def test_path_traversal_declared_script_path_fails(tmp_path):
    workspace = make_workspace(tmp_path, skill_md=UNSAFE_PATH_SKILL_MD)

    result = Verifier().verify(workspace)

    assert result.passed is False
    assert_failed_check(result, "package_declared_path_safety")
    assert any("unsafe segment" in failure or "escape" in failure for failure in result.failures)


def test_malformed_frontmatter_fails_closed(tmp_path):
    workspace = make_workspace(tmp_path, skill_md=MALFORMED_FRONTMATTER_SKILL_MD)

    result = Verifier().verify(workspace)

    assert result.passed is False
    assert_failed_check(result, "skill_frontmatter_parse")


def test_symlink_escape_in_package_fails_when_supported(tmp_path):
    workspace = make_workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace.root / "package" / "references" / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    result = Verifier().verify(workspace)

    assert result.passed is False
    assert_failed_check(result, "package_path_confinement")


def test_locked_input_mismatch_fails(tmp_path):
    workspace = make_workspace(tmp_path)
    worker_input = workspace.resolve_path("worker_input.md", must_exist=True)
    worker_input.write_text(worker_input.read_text(encoding="utf-8") + "\ntamper\n", encoding="utf-8")

    result = Verifier().verify(workspace)

    assert result.passed is False
    assert_failed_check(result, "locked_input_integrity")


def test_expected_package_hash_mismatch_fails(tmp_path):
    workspace = make_workspace(tmp_path)

    result = Verifier(expected_package_hash="f" * 64).verify(workspace)

    assert result.passed is False
    assert_failed_check(result, "expected_package_hash")


def test_missing_artifact_manifest_fails(tmp_path):
    workspace = make_workspace(tmp_path)
    workspace.resolve_path("artifact_manifest.json", must_exist=True).unlink()

    result = Verifier().verify(workspace)

    assert result.passed is False
    assert_failed_check(result, "artifact_manifest_present")
    assert_failed_check(result, "locked_input_integrity")
    assert workspace.resolve_path("verifier/verification_result.json", must_exist=True).is_file()


def test_builder_self_report_success_cannot_pass_invalid_package(tmp_path):
    workspace = make_workspace(tmp_path, skill_md=INVALID_SKILL_MD)

    result = Verifier().verify(workspace)

    assert result.passed is False
    assert check_by_name(result, "execution_report_success")[0]["passed"] is True
    assert_failed_check(result, "skill_required_section")


def test_llm_judge_pass_signal_cannot_override_static_failure(tmp_path):
    workspace = make_workspace(tmp_path, skill_md=INVALID_SKILL_MD)

    result = Verifier(llm_judge_passed=True).verify(workspace)

    assert result.passed is False
    llm_checks = check_by_name(result, "llm_judge_signal")
    assert llm_checks == [
        {
            "name": "llm_judge_signal",
            "passed": True,
            "severity": "info",
            "message": "LLM judge signal is advisory only and cannot override primary verifier gates",
            "evidence_ref": "verifier/llm_judge_signal.json",
        }
    ]
    assert workspace.resolve_path("verifier/llm_judge_signal.json", must_exist=True).is_file()


def test_sandbox_smoke_failure_causes_verification_fail(tmp_path):
    workspace = make_workspace(tmp_path, smoke_fail=True)

    result = Verifier().verify(workspace)

    assert result.passed is False
    assert_failed_check(result, "sandbox_smoke")
    sandbox_log = workspace.resolve_path("verifier/sandbox.log", must_exist=True).read_text(encoding="utf-8")
    assert "No package scripts were executed." in sandbox_log
