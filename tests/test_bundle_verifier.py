import json
from pathlib import Path

from skillfoundry import Verifier
from skillfoundry.bundle import BUNDLE_MANIFEST_REF, CapabilityBundleManifest
from skillfoundry.bundle_verifier import (
    BUNDLE_MANIFEST_STATUSES,
    BUNDLE_VERIFICATION_RESULT_REF,
    BUNDLE_VERIFIER_VERSION,
    BundleVerificationResult,
    BundleVerifier,
)
from skillfoundry.workspace import JobWorkspace, initialize_job_workspace


VALID_SKILL = """---
name: bundle-verifier-skill
description: Bundle verifier fixture.
---

# Bundle Verifier Skill

## Overview

Bundle verifier fixture.

## When To Use

- Use for deterministic bundle verifier tests.

## When Not To Use

- Do not use for live package generation.

## Inputs

- Local fixture inputs.

## Outputs

- Local fixture outputs.

## Workflow

1. Read local files.

## Safety

- Do not execute untrusted code.
"""


def make_workspace(tmp_path: Path, job_id: str = "bundle-verifier-001") -> JobWorkspace:
    workspace = initialize_job_workspace(tmp_path / "runs", job_id)
    workspace.resolve_path("package/SKILL.md").write_text(VALID_SKILL, encoding="utf-8")
    return workspace


def write_manifest(workspace: JobWorkspace, manifest: CapabilityBundleManifest) -> None:
    manifest.write_json_file(workspace.resolve_path(BUNDLE_MANIFEST_REF))


def check_by_name(result: BundleVerificationResult, name: str):
    return [check for check in result.checks if check["name"] == name]


def test_bundle_verifier_missing_manifest_is_compatible_by_default(tmp_path: Path):
    workspace = make_workspace(tmp_path)

    result = BundleVerifier().verify(workspace)

    assert result.verifier_version == BUNDLE_VERIFIER_VERSION
    assert "missing" in BUNDLE_MANIFEST_STATUSES
    assert result.manifest_present is False
    assert result.manifest_status == "missing"
    assert result.passed is True
    assert check_by_name(result, "bundle_manifest_present")[0]["severity"] == "warning"
    assert workspace.resolve_path(BUNDLE_VERIFICATION_RESULT_REF, must_exist=True).is_file()


def test_bundle_verifier_can_require_manifest(tmp_path: Path):
    workspace = make_workspace(tmp_path)

    result = BundleVerifier(require_manifest=True).verify(workspace)

    assert result.passed is False
    assert result.manifest_present is False
    assert result.manifest_status == "missing"
    assert result.failures == ["bundle_manifest_present: bundle manifest is required but not present"]


def test_bundle_verifier_valid_prompt_only_manifest_passes(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    write_manifest(
        workspace,
        CapabilityBundleManifest(
            bundle_id="prompt-bundle",
            bundle_type="prompt_only",
            entrypoint="SKILL.md",
        ),
    )

    result = BundleVerifier().verify(workspace)

    assert result.manifest_present is True
    assert result.manifest_status == "valid"
    assert result.passed is True
    assert check_by_name(result, "bundle_manifest_valid")[0]["passed"] is True
    assert check_by_name(result, "bundle_entrypoint_exists")[0]["passed"] is True
    assert check_by_name(result, "bundle_prompt_only_skill_md")[0]["passed"] is True
    assert result.package_hash != "0" * 64


def test_bundle_verifier_invalid_manifest_fails(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    workspace.resolve_path(BUNDLE_MANIFEST_REF).write_text(
        json.dumps(
            {
                "schema_version": "skillfoundry.bundle.v1",
                "bundle_id": "bad",
                "bundle_type": "prompt_only",
                "entrypoint": "../SKILL.md",
            }
        ),
        encoding="utf-8",
    )

    result = BundleVerifier().verify(workspace)

    assert result.passed is False
    assert result.manifest_present is True
    assert result.manifest_status == "invalid"
    assert any("bundle_manifest_valid" in failure for failure in result.failures)


def test_bundle_verifier_forbidden_raw_manifest_field_fails(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    workspace.resolve_path(BUNDLE_MANIFEST_REF).write_text(
        json.dumps(
            {
                "schema_version": "skillfoundry.bundle.v1",
                "bundle_id": "bad",
                "bundle_type": "prompt_only",
                "entrypoint": "SKILL.md",
                "verification": {"nested": {"raw_prompt": "secret prompt body"}},
            }
        ),
        encoding="utf-8",
    )

    result = BundleVerifier().verify(workspace)

    assert result.passed is False
    assert result.manifest_present is True
    assert result.manifest_status == "invalid"
    assert any("raw_prompt" in failure for failure in result.failures)


def test_bundle_verifier_missing_declared_refs_fail(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    write_manifest(
        workspace,
        CapabilityBundleManifest(
            bundle_id="code-bundle",
            bundle_type="code_runtime",
            entrypoint="SKILL.md",
            runtime_assets=["runtime/cli.py"],
            data_assets=["data/runtime_kb.jsonl"],
            references=["references/guide.md"],
            verification={"commands": ["python runtime/cli.py --help"]},
        ),
    )

    result = BundleVerifier().verify(workspace)

    assert result.passed is False
    failures = "\n".join(result.failures)
    assert "package/runtime/cli.py is missing" in failures
    assert "package/data/runtime_kb.jsonl is missing" in failures
    assert "package/references/guide.md is missing" in failures


def test_bundle_verifier_code_runtime_records_commands_without_executing(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    workspace.resolve_path("package/runtime").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("package/runtime/cli.py").write_text("raise SystemExit('should not run')\n", encoding="utf-8")
    write_manifest(
        workspace,
        CapabilityBundleManifest(
            bundle_id="code-bundle",
            bundle_type="code_runtime",
            entrypoint="SKILL.md",
            runtime_assets=["runtime/cli.py"],
            verification={"commands": ["python runtime/cli.py --help"]},
        ),
    )

    result = BundleVerifier().verify(workspace)

    assert result.passed is True
    command_checks = check_by_name(result, "bundle_code_runtime_verification_commands_declared")
    assert command_checks[0]["passed"] is True
    assert command_checks[0]["severity"] == "info"


def test_existing_verifier_fails_when_present_bundle_manifest_is_invalid(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    workspace.resolve_path(BUNDLE_MANIFEST_REF).write_text(
        json.dumps(
            {
                "schema_version": "skillfoundry.bundle.v1",
                "bundle_id": "bad",
                "bundle_type": "not-real",
                "entrypoint": "SKILL.md",
            }
        ),
        encoding="utf-8",
    )

    result = Verifier().verify(workspace)

    assert result.passed is False
    assert any(check["name"] == "bundle_manifest_valid" and check["passed"] is False for check in result.checks)
    assert BUNDLE_VERIFICATION_RESULT_REF in result.evidence_refs
