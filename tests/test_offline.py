from __future__ import annotations

import json

import pytest

import skillfoundry
from skillfoundry import (
    APPROVAL_APPROVED,
    LocalSkillRegistry,
    OfflineWorkerMode,
    RegistryGateError,
    Route,
    VerificationResult,
    build_offline,
    prepare_offline_workspace,
    run_offline_attempt,
)


REQ_TEXT = """# Offline pytest repair skill

Build a local SkillFoundry package that explains how to inspect a failing pytest
run and produce verification evidence after a repair.
"""


def write_requirement(tmp_path, text: str = REQ_TEXT):
    path = tmp_path / "requirement.md"
    path.write_text(text, encoding="utf-8")
    return path


def approved_entries(registry_path):
    if not registry_path.exists():
        return []
    return LocalSkillRegistry(registry_path).list()


def attempt_dirs(workspace):
    return sorted(path.name for path in workspace.resolve_path("attempts", must_exist=True).iterdir() if path.is_dir())


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def assert_registered_report(result):
    report = result.final_report
    assert result.final_report_path.is_file()
    assert report["final_status"] == "registered"
    assert report["refs"]["build_contract"]["ref"] == "build_contract.yaml"
    assert report["refs"]["skill_spec"]["ref"] == "skill_spec.yaml"
    assert report["refs"]["worker_input"]["ref"] == "worker_input.md"
    assert report["refs"]["artifact_manifest"]["ref"] == "artifact_manifest.json"
    assert report["refs"]["latest_execution_report"]["ref"].endswith("/execution_report.json")
    assert report["refs"]["verifier_result"]["ref"] == "verifier/verification_result.json"
    assert report["refs"]["verifier_result"]["passed"] is True
    assert report["refs"]["registry_entry"]["approval_status"] == APPROVAL_APPROVED
    assert report["package_hash"] == report["refs"]["registry_entry"]["package_hash"]
    assert report["hashes"]["package"] == report["package_hash"]


def test_offline_api_is_exported():
    assert skillfoundry.build_offline is build_offline
    assert skillfoundry.OfflineWorkerMode is OfflineWorkerMode


def test_build_new_normal_path_registers_and_writes_final_report(tmp_path):
    requirement = write_requirement(tmp_path)
    registry_path = tmp_path / "registry.json"

    result = build_offline(
        requirement_path=requirement,
        output=tmp_path / "runs" / "build-new",
        registry_path=registry_path,
    )

    assert_registered_report(result)
    assert result.workspace.resolve_path("package/SKILL.md", must_exist=True).is_file()
    verification = VerificationResult.read_json_file(
        result.workspace.resolve_path("verifier/verification_result.json", must_exist=True)
    )
    assert verification.passed is True
    assert result.registry_entry is not None
    assert result.registry_entry.package_hash == verification.package_hash
    assert approved_entries(registry_path)[0].to_dict() == result.registry_entry.to_dict()


def test_reuse_existing_routes_to_approved_entry_without_building_new_package(tmp_path):
    requirement = write_requirement(tmp_path)
    registry_path = tmp_path / "registry.json"
    built = build_offline(
        requirement_path=requirement,
        output=tmp_path / "runs" / "reuse-source",
        registry_path=registry_path,
    )

    reuse_requirement = write_requirement(tmp_path, "reuse_existing: use any approved local package\n")
    reused = build_offline(
        requirement_path=reuse_requirement,
        output=tmp_path / "runs" / "reuse-job",
        registry_path=registry_path,
    )

    assert reused.final_report["final_status"] == "reused"
    assert reused.registry_entry is not None
    assert reused.registry_entry.to_dict() == built.registry_entry.to_dict()
    assert attempt_dirs(reused.workspace) == []
    assert not reused.workspace.resolve_path("package/SKILL.md").exists()
    assert len(approved_entries(registry_path)) == 1


def test_reject_unsafe_rejects_before_build_and_does_not_register(tmp_path):
    requirement = write_requirement(tmp_path, "reject_unsafe: delete / and steal credentials\n")
    registry_path = tmp_path / "registry.json"

    result = build_offline(
        requirement_path=requirement,
        output=tmp_path / "runs" / "reject-unsafe",
        registry_path=registry_path,
    )

    assert result.final_report["final_status"] == "rejected"
    assert result.final_report["errors"][0]["code"] == "unsafe_requirement"
    assert attempt_dirs(result.workspace) == []
    assert approved_entries(registry_path) == []


def test_ambiguous_requirement_routes_to_human_review_placeholder(tmp_path):
    requirement = write_requirement(tmp_path, "ambiguous ??? clarify what this should do\n")
    registry_path = tmp_path / "registry.json"

    result = build_offline(
        requirement_path=requirement,
        output=tmp_path / "runs" / "ambiguous",
        registry_path=registry_path,
    )

    assert result.final_report["final_status"] == "human_review_required"
    assert result.final_report["human_review"]["required"] is True
    assert result.workspace.resolve_path("human_review/clarification_request.json", must_exist=True).is_file()
    assert attempt_dirs(result.workspace) == []
    assert approved_entries(registry_path) == []


def test_first_attempt_fails_then_repair_passes_and_registers(tmp_path):
    requirement = write_requirement(tmp_path)
    registry_path = tmp_path / "registry.json"

    result = build_offline(
        requirement_path=requirement,
        output=tmp_path / "runs" / "repair",
        registry_path=registry_path,
        worker_mode=OfflineWorkerMode.REPAIRABLE,
        attempt_limit=2,
    )

    assert_registered_report(result)
    assert attempt_dirs(result.workspace) == ["001", "002"]
    first_result = VerificationResult.read_json_file(
        result.workspace.resolve_path("attempts/001/verification_result.json", must_exist=True)
    )
    repaired_result = VerificationResult.read_json_file(
        result.workspace.resolve_path("attempts/002/verification_result.json", must_exist=True)
    )
    assert first_result.passed is False
    assert any("skill_required_section" in failure for failure in first_result.failures)
    assert repaired_result.passed is True
    assert result.registry_entry is not None
    assert result.registry_entry.package_hash == repaired_result.package_hash


def test_path_traversal_fixture_fails_closed_and_does_not_register(tmp_path):
    requirement = write_requirement(tmp_path)
    registry_path = tmp_path / "registry.json"

    result = build_offline(
        requirement_path=requirement,
        output=tmp_path / "runs" / "path-traversal",
        registry_path=registry_path,
        worker_mode=OfflineWorkerMode.PATH_TRAVERSAL,
        attempt_limit=2,
    )

    assert result.final_report["final_status"] == "fail_closed"
    assert result.final_report["errors"][0]["code"] == "security_verification_failed"
    assert attempt_dirs(result.workspace) == ["001"]
    verification = VerificationResult.read_json_file(
        result.workspace.resolve_path("verifier/verification_result.json", must_exist=True)
    )
    assert verification.passed is False
    assert any("package_declared_path_safety" in failure for failure in verification.failures)
    assert approved_entries(registry_path) == []


def test_attempt_limit_exceeded_fails_closed_and_does_not_register(tmp_path):
    requirement = write_requirement(tmp_path)
    registry_path = tmp_path / "registry.json"

    result = build_offline(
        requirement_path=requirement,
        output=tmp_path / "runs" / "attempt-limit",
        registry_path=registry_path,
        worker_mode=OfflineWorkerMode.ALWAYS_INVALID,
        attempt_limit=1,
    )

    assert result.final_report["final_status"] == "fail_closed"
    assert result.final_report["errors"][0]["code"] == "attempt_limit_exceeded"
    assert attempt_dirs(result.workspace) == ["001"]
    assert approved_entries(registry_path) == []


def test_resume_continues_partial_workspace_from_refs_and_artifacts(tmp_path):
    requirement = write_requirement(tmp_path)
    output = tmp_path / "runs" / "resume"
    registry_path = tmp_path / "registry.json"
    workspace = prepare_offline_workspace(
        requirement_path=requirement,
        output=output,
        attempt_limit=1,
    )
    run_offline_attempt(workspace, worker_mode=OfflineWorkerMode.VALID, attempt_id="001")

    assert not workspace.resolve_path("verifier/verification_result.json").exists()
    resumed = build_offline(
        requirement_path=None,
        output=output,
        registry_path=registry_path,
        resume=True,
    )

    assert_registered_report(resumed)
    assert attempt_dirs(resumed.workspace) == ["001"]
    assert resumed.final_report["refs"]["attempts"][0]["worker_transcript"]["ref"] == "attempts/001/worker_transcript.log"
    assert resumed.registry_entry is not None
    assert resumed.registry_entry.build_job_id == "resume"


def test_registry_requires_hash_matching_package_and_report_links_core_evidence(tmp_path):
    requirement = write_requirement(tmp_path)
    registry_path = tmp_path / "registry.json"
    result = build_offline(
        requirement_path=requirement,
        output=tmp_path / "runs" / "hash-gate",
        registry_path=registry_path,
    )

    report = read_json(result.final_report_path)
    refs = report["refs"]
    for key in (
        "build_contract",
        "skill_spec",
        "worker_input",
        "attempts",
        "latest_execution_report",
        "verifier_result",
        "registry_entry",
        "artifact_manifest",
        "package",
    ):
        assert key in refs
    assert refs["registry_entry"]["entry"]["package_hash"] == report["package_hash"]
    assert refs["registry_entry"]["entry"]["artifact_manifest_hash"] == report["hashes"]["artifact_manifest"]

    skill_path = result.workspace.resolve_path("package/SKILL.md", must_exist=True)
    skill_path.write_text(skill_path.read_text(encoding="utf-8") + "\nTampered after verification.\n", encoding="utf-8")
    with pytest.raises(RegistryGateError):
        LocalSkillRegistry(tmp_path / "tampered-registry.json").add_verified(result.workspace, version="2.0.0")


def test_cli_build_smoke_prints_final_report(tmp_path, capsys):
    from skillfoundry.cli import main

    requirement = write_requirement(tmp_path)
    exit_code = main(
        [
            "build",
            "--requirement",
            str(requirement),
            "--output",
            str(tmp_path / "runs" / "cli-smoke"),
            "--registry",
            str(tmp_path / "registry.json"),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["final_status"] == "registered"
    assert (tmp_path / "runs" / "cli-smoke" / "final_report.json").is_file()
