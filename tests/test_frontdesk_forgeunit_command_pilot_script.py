from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


SCRIPT = Path("scripts/run_frontdesk_forgeunit_command_pilot.py")


def test_frontdesk_command_pilot_script_registers_refs_only(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = runs_root / "registry.json"
    worker_dir = tmp_path / "worker"
    private_marker = "PRIVATE_FRONTDESK_COMMAND_PILOT_MESSAGE_SHOULD_NOT_LEAK"
    result = _run_pilot(
        tmp_path,
        "--runs-root",
        str(runs_root),
        "--registry-path",
        str(registry_path),
        "--worker-dir",
        str(worker_dir),
        "--job-id",
        "frontdesk-command-pilot-test",
        "--message",
        f"Build a governed status skill. {private_marker}",
        "--version",
        "frontdesk-command-pilot-test",
        "--created-at",
        "2026-05-23T00:00:00Z",
        "--overwrite",
    )
    payload = json.loads(result.stdout)
    serialized = json.dumps(payload, sort_keys=True)
    workspace = runs_root / "frontdesk-command-pilot-test"

    assert payload["schema_version"] == "skillfoundry.frontdesk_forgeunit_command_pilot.v1"
    assert payload["job_id"] == "frontdesk-command-pilot-test"
    assert payload["status"] == "registered"
    assert payload["frontdesk"]["create_status"] == "await_user_plan_review"
    assert payload["frontdesk"]["plan_review_status"] == "route_to_build"
    assert payload["build_path"]["mode"] == "forgeunit_skillfoundry_vnext"
    assert payload["build_path"]["canonical"] is True
    assert payload["forgeunit_skillfoundry"]["mode"] == "command_bridge"
    assert payload["forgeunit_skillfoundry"]["stage"] == "emit_report"
    assert payload["forgeunit_skillfoundry"]["status"] == "report_emitted"
    assert payload["forgeunit_skillfoundry"]["verification_status"] == "passed"
    assert payload["forgeunit_skillfoundry"]["verification_passed"] is True
    assert payload["forgeunit_skillfoundry"]["registry_approved"] is True
    assert payload["forgeunit_skillfoundry"]["registry_version"] == "frontdesk-command-pilot-test"
    assert payload["forgeunit_skillfoundry"]["command_string_included"] is False
    assert payload["forgeunit_skillfoundry"]["raw_prompt_included"] is False
    assert payload["forgeunit_skillfoundry"]["raw_transcript_included"] is False
    assert payload["forgeunit_skillfoundry"]["raw_worker_input_included"] is False
    assert payload["contextforge_status"]["verification_status"] == "passed"
    assert payload["contextforge_status"]["verification_passed"] is True
    assert payload["contextforge_status"]["registry_approved"] is True
    assert payload["package_downloadable"] is True
    assert payload["refs"]["forgeunit_skillfoundry_summary"] == "contextforge/forgeunit_skillfoundry_summary.json"
    assert payload["refs"]["forgeunit_skillfoundry_product_state"] == (
        "contextforge/forgeunit_skillfoundry_product_state.json"
    )
    assert payload["refs"]["forgeunit_skillfoundry_graph_state"] == (
        "contextforge/forgeunit_skillfoundry_graph_state.json"
    )
    assert payload["refs"]["registry_decision"] == "registry/decision.json"
    assert payload["refs"]["registry_entry"] == "registry/entry.json"
    assert payload["refs"]["final_report"] == "final_report.json"

    assert (worker_dir / "frontdesk_local_success_worker.py").is_file()
    assert (workspace / "package" / "SKILL.md").is_file()
    assert (workspace / "evidence" / "transcript.md").is_file()
    assert (workspace / "evidence" / "manifest.json").is_file()
    assert (workspace / "final_report.json").is_file()
    assert (workspace / "contextforge" / "forgeunit_skillfoundry_summary.json").is_file()
    assert (workspace / "contextforge" / "forgeunit_skillfoundry_product_state.json").is_file()
    assert (workspace / "contextforge" / "forgeunit_skillfoundry_graph_state.json").is_file()

    assert private_marker not in serialized
    assert worker_dir.as_posix() not in serialized
    assert "frontdesk_local_success_worker.py" not in serialized
    assert "local frontdesk command pilot transcript pointer" not in serialized
    assert "ForgeUnit SkillFoundry Composition Skill" not in serialized
    assert "package_content" not in serialized
    assert "raw prompt body" not in serialized
    assert "raw transcript body" not in serialized


def test_frontdesk_command_pilot_script_refuses_existing_workspace_without_overwrite(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = runs_root / "registry.json"
    worker_dir = tmp_path / "worker"
    args = (
        "--runs-root",
        str(runs_root),
        "--registry-path",
        str(registry_path),
        "--worker-dir",
        str(worker_dir),
        "--job-id",
        "frontdesk-command-pilot-existing",
    )
    _run_pilot(tmp_path, *args, "--overwrite")

    result = _run_pilot(tmp_path, *args, expect_success=False)

    assert result.returncode == 2
    assert "workspace already exists" in result.stderr
    assert not result.stdout.strip()


def _run_pilot(tmp_path: Path, *args: str, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if expect_success and result.returncode != 0:
        raise AssertionError(
            "FrontDesk command pilot script failed\n"
            f"returncode={result.returncode}\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}\n"
            f"tmp_path={tmp_path}"
        )
    return result
