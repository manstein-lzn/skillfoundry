from dataclasses import replace
from pathlib import Path

import pytest

from skillfoundry import (
    LOCKED_INPUT_PATHS,
    LockedInputTamperError,
    PathSecurityError,
    assert_under_root,
    initialize_job_workspace,
    validate_relative_path,
)


def test_workspace_initializer_creates_standard_layout(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "demo-001")

    expected_dirs = [
        "attempts",
        "package",
        "package/references",
        "package/scripts",
        "package/tests",
        "verifier",
    ]
    expected_files = [
        "build_contract.yaml",
        "skill_spec.yaml",
        "verification_spec.yaml",
        "worker_input.md",
        "artifact_manifest.json",
        "resume_brief.md",
    ]
    for relative_path in expected_dirs:
        assert workspace.resolve_path(relative_path, must_exist=True).is_dir()
    for relative_path in expected_files:
        assert workspace.resolve_path(relative_path, must_exist=True).is_file()


def test_artifact_manifest_covers_locked_inputs(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "demo-001")
    manifest = workspace.read_manifest()

    locked_paths = {record.path for record in manifest.locked_records()}
    assert locked_paths == set(LOCKED_INPUT_PATHS)
    workspace.check_locked_inputs()


def test_locked_input_tamper_is_detected(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "demo-001")
    worker_input = workspace.resolve_path("worker_input.md", must_exist=True)
    worker_input.write_text(worker_input.read_text(encoding="utf-8") + "\nTampered.\n", encoding="utf-8")

    with pytest.raises(LockedInputTamperError):
        workspace.check_locked_inputs()


def test_missing_locked_manifest_record_is_detected(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "demo-001")
    manifest = workspace.read_manifest()
    manifest.artifacts = [record for record in manifest.artifacts if record.path != "worker_input.md"]
    workspace.write_manifest(manifest)

    with pytest.raises(LockedInputTamperError):
        workspace.check_locked_inputs()


def test_duplicate_locked_manifest_record_is_detected(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "demo-001")
    manifest = workspace.read_manifest()
    duplicated = replace(manifest.locked_records()[0], artifact_id="demo-001:duplicate-build-contract")
    manifest.artifacts.append(duplicated)
    workspace.write_manifest(manifest)

    with pytest.raises(LockedInputTamperError):
        workspace.check_locked_inputs()


def test_outside_resolved_path_is_rejected(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "demo-001")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(PathSecurityError):
        assert_under_root(workspace.root, outside)


@pytest.mark.parametrize("bad_path", ["/tmp/escape", "C:\\escape\\file.txt"])
def test_absolute_paths_are_rejected(bad_path):
    with pytest.raises(PathSecurityError):
        validate_relative_path(bad_path)


@pytest.mark.parametrize("bad_path", ["../escape", "package/../escape", "./package", "package//SKILL.md"])
def test_dotdot_and_dot_paths_are_rejected(tmp_path, bad_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "demo-001")
    with pytest.raises(PathSecurityError):
        workspace.resolve_path(bad_path)


def test_symlink_escape_is_rejected(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "demo-001")
    outside = tmp_path / "outside"
    outside.mkdir()
    escape_link = workspace.root / "package" / "escape"
    try:
        escape_link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(PathSecurityError):
        workspace.resolve_path("package/escape/file.txt")


def test_safe_package_path_resolves_under_workspace(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "demo-001")
    target = workspace.resolve_path("package/SKILL.md")

    assert target == Path(workspace.root).resolve() / "package" / "SKILL.md"
