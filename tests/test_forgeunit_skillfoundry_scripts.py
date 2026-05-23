from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from forgeunit_skillfoundry import (
    FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF,
    FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF,
    FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF,
    EVIDENCE_SUMMARY_SCHEMA_VERSION,
)
from skillfoundry.forgeunit_adapter import FORGEUNIT_REPAIR_PACKET_REF
from skillfoundry.registry import LocalSkillRegistry


SCRIPT = Path("scripts/run_forgeunit_skill_factory.py")


def test_cli_runner_happy_fake_mode_registers_refs_only(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    result = _run_cli(
        tmp_path,
        "--runs-root",
        str(runs_root),
        "--job-id",
        "cli-happy-001",
        "--registry",
        str(registry_path),
        "--fake-mode",
        "happy",
        "--version",
        "cli-happy",
        "--created-at",
        "2026-05-23T00:00:00Z",
        "--worker-input",
        "private cli happy request must stay file-only",
    )
    payload = json.loads(result.stdout)
    serialized = json.dumps(payload)
    workspace = runs_root / "cli-happy-001"
    entry = LocalSkillRegistry(registry_path).get("cli-happy-001-skill", "cli-happy")
    registry_report = LocalSkillRegistry(registry_path).verify_entry(entry)

    assert payload["schema_version"] == EVIDENCE_SUMMARY_SCHEMA_VERSION
    assert payload["job_id"] == "cli-happy-001"
    assert payload["mode"] == "command_bridge"
    assert payload["status"] == "report_emitted"
    assert payload["verification"]["status"] == "passed"
    assert payload["verification"]["passed"] is True
    assert payload["registry"]["approved"] is True
    assert payload["refs"]["forgeunit_skillfoundry_graph_state"] == FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF
    assert payload["refs"]["forgeunit_skillfoundry_product_state"] == FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF
    assert payload["refs"]["forgeunit_skillfoundry_summary"] == FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    assert payload["trust_boundaries"]["command_string_included"] is False
    assert registry_report.valid is True
    assert (workspace / FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF).is_file()
    assert (workspace / FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF).is_file()
    assert (workspace / FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF).is_file()
    assert "private cli happy request" not in serialized
    assert "fake_cli_codex_exec.py" not in serialized
    assert "ForgeUnit SkillFoundry Composition Skill" not in serialized
    assert "deterministic forgeunit skillfoundry transcript" not in serialized
    assert "raw prompt body" not in serialized
    assert "raw transcript body" not in serialized
    assert "package_content" not in serialized


def test_cli_runner_repair_fake_mode_registers_refs_only(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    result = _run_cli(
        tmp_path,
        "--runs-root",
        str(runs_root),
        "--job-id",
        "cli-repair-001",
        "--registry",
        str(registry_path),
        "--fake-mode",
        "repair",
        "--version",
        "cli-repair",
        "--created-at",
        "2026-05-23T00:00:00Z",
        "--worker-input",
        "private cli repair request must stay file-only",
    )
    payload = json.loads(result.stdout)
    serialized = json.dumps(payload)
    workspace = runs_root / "cli-repair-001"
    repair_packet = json.loads((workspace / FORGEUNIT_REPAIR_PACKET_REF).read_text())
    entry = LocalSkillRegistry(registry_path).get("cli-repair-001-skill", "cli-repair")
    registry_report = LocalSkillRegistry(registry_path).verify_entry(entry)

    assert payload["mode"] == "repair_command_bridge"
    assert payload["status"] == "report_emitted"
    assert payload["verification"]["status"] == "passed"
    assert payload["verification"]["passed"] is True
    assert payload["registry"]["approved"] is True
    assert payload["refs"]["forgeunit_repair_packet"] == FORGEUNIT_REPAIR_PACKET_REF
    assert payload["refs"]["forgeunit_skillfoundry_graph_state"] == FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF
    assert payload["refs"]["forgeunit_skillfoundry_product_state"] == FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF
    assert payload["refs"]["forgeunit_skillfoundry_summary"] == FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    assert payload["trust_boundaries"]["command_string_included"] is False
    assert repair_packet["failed_attempt_id"] == "001"
    assert repair_packet["repair_attempt_id"] == "002"
    assert registry_report.valid is True
    assert payload["attempts"][0]["attempt_id"] == "001"
    assert payload["attempts"][1]["attempt_id"] == "002"
    assert (workspace / "attempts/001/verification_result.json").is_file()
    assert (workspace / "attempts/002/verification_result.json").is_file()
    assert (workspace / FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF).is_file()
    assert "private cli repair request" not in serialized
    assert "fake_cli_bad_codex_exec.py" not in serialized
    assert "fake_cli_repair_codex_exec.py" not in serialized
    assert "ForgeUnit SkillFoundry Composition Skill" not in serialized
    assert "ForgeUnit SkillFoundry Invalid Fixture" not in serialized
    assert "deterministic forgeunit skillfoundry transcript" not in serialized
    assert "raw prompt body" not in serialized
    assert "raw transcript body" not in serialized
    assert "package_content" not in serialized


def test_cli_runner_requires_command_without_fake_mode(tmp_path: Path) -> None:
    result = _run_cli(
        tmp_path,
        "--runs-root",
        str(tmp_path / "runs"),
        "--job-id",
        "cli-invalid-001",
        "--registry",
        str(tmp_path / "registry.json"),
        expect_success=False,
    )

    assert result.returncode != 0
    assert "--command is required unless --fake-mode is happy or repair" in result.stderr
    assert not result.stdout.strip()


def _run_cli(tmp_path: Path, *args: str, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
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
            "CLI runner failed\n"
            f"returncode={result.returncode}\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}\n"
            f"tmp_path={tmp_path}"
        )
    return result
