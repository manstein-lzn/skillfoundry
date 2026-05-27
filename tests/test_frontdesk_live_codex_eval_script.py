from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from scripts.run_frontdesk_live_codex_eval import (
    Scenario,
    _matched_marker_count,
    _semantic_fidelity_summary,
    _semantic_markers_from_payload,
)


SCRIPT = Path("scripts/run_frontdesk_live_codex_eval.py")


def test_frontdesk_live_codex_eval_fake_mode_runs_scenarios_refs_only(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    scenario_file = tmp_path / "scenarios.json"
    private_marker = "PRIVATE_LIVE_EVAL_SCENARIO_MESSAGE_SHOULD_NOT_LEAK"
    scenario_file.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": "pytest-failure",
                        "message": f"Build a pytest failure analyzer skill. {private_marker}",
                    },
                    {
                        "id": "handoff-brief",
                        "message": "Build a repository handoff brief skill.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = _run_eval(
        tmp_path,
        "--runs-root",
        str(runs_root),
        "--eval-id",
        "frontdesk-live-eval-test",
        "--registry-path",
        "registry.json",
        "--scenario-file",
        str(scenario_file),
        "--version-prefix",
        "frontdesk-live-eval-test",
        "--created-at",
        "2026-05-23T00:00:00Z",
        "--fake-mode",
        "happy",
        "--overwrite",
    )
    payload = json.loads(result.stdout)
    serialized = json.dumps(payload, sort_keys=True)
    eval_root = runs_root / "frontdesk-live-eval-test"

    assert payload["schema_version"] == "skillfoundry.frontdesk_live_codex_eval.v1"
    assert payload["eval_id"] == "frontdesk-live-eval-test"
    assert payload["mode"] == "fake"
    assert payload["build_mode"] == "api_default"
    assert payload["live_codex_requested"] is False
    assert payload["totals"]["total"] == 2
    assert payload["totals"]["registered"] == 2
    assert payload["totals"]["failed"] == 0
    assert payload["totals"]["redaction_failures"] == 0
    assert payload["totals"]["semantic_fidelity_configured"] == 2
    assert payload["totals"]["semantic_fidelity_passed"] == 2
    assert payload["totals"]["semantic_fidelity_failed"] == 0
    assert payload["totals"]["unique_registry_skill_ids"] == 2
    assert payload["failure_taxonomy"] == []
    assert payload["redaction_findings"] == []
    assert payload["trust_boundaries"]["command_string_included"] is False
    assert payload["trust_boundaries"]["raw_frontdesk_conversation_included"] is False
    assert payload["trust_boundaries"]["raw_worker_input_included"] is False
    assert len(payload["scenarios"]) == 2

    for item in payload["scenarios"]:
        workspace = eval_root / item["job_id"]
        assert item["status"] == "registered"
        assert item["build_path"]["mode"] == "forgeunit_skillfoundry_vnext"
        assert item["forgeunit_skillfoundry"]["mode"] == "command_bridge"
        assert item["forgeunit_skillfoundry"]["verification_passed"] is True
        assert item["forgeunit_skillfoundry"]["registry_approved"] is True
        assert item["forgeunit_skillfoundry"]["command_string_included"] is False
        assert item["forgeunit_skillfoundry"]["raw_prompt_included"] is False
        assert item["forgeunit_skillfoundry"]["raw_transcript_included"] is False
        assert item["forgeunit_skillfoundry"]["raw_worker_input_included"] is False
        assert item["semantic_fidelity"]["configured"] is True
        assert item["semantic_fidelity"]["passed"] is True
        assert item["semantic_fidelity"]["source_passed"] is True
        assert item["semantic_fidelity"]["package_checked"] is False
        assert item["semantic_fidelity"]["package_passed"] is True
        assert item["semantic_fidelity"]["required_marker_count"] >= 2
        assert item["semantic_fidelity"]["source_matched_marker_count"] == (
            item["semantic_fidelity"]["required_marker_count"]
        )
        assert item["semantic_fidelity"]["package_matched_marker_count"] is None
        assert item["package_downloadable"] is True
        assert item["refs"]["forgeunit_skillfoundry_summary"] == "contextforge/forgeunit_skillfoundry_summary.json"
        assert item["refs"]["registry_decision"] == "registry/decision.json"
        assert item["refs"]["final_report"] == "final_report.json"
        assert (workspace / "package" / "SKILL.md").is_file()
        assert (workspace / "evidence" / "manifest.json").is_file()
        assert (workspace / "final_report.json").is_file()

    assert (eval_root / "eval_summary.json").is_file()
    assert json.loads((eval_root / "eval_summary.json").read_text(encoding="utf-8")) == payload
    assert private_marker not in serialized
    assert scenario_file.read_text(encoding="utf-8") not in serialized
    assert "frontdesk_eval_fake_codex_exec.py" not in serialized
    assert "deterministic forgeunit skillfoundry transcript pointer" not in serialized
    assert "ForgeUnit SkillFoundry Composition Skill" not in serialized
    assert "pytest-failure" in serialized
    assert "Build a pytest failure analyzer skill" not in serialized
    assert "package_content" not in serialized
    assert "raw prompt body" not in serialized
    assert "raw transcript body" not in serialized


def test_frontdesk_live_codex_eval_fake_mode_can_use_adaptive_codex(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    scenario_file = tmp_path / "scenarios.json"
    scenario_file.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": "adaptive-status",
                        "message": "Build an adaptive status skill.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = _run_eval(
        tmp_path,
        "--runs-root",
        str(runs_root),
        "--eval-id",
        "frontdesk-live-eval-adaptive",
        "--registry-path",
        "registry.json",
        "--scenario-file",
        str(scenario_file),
        "--version-prefix",
        "frontdesk-live-eval-adaptive",
        "--created-at",
        "2026-05-23T00:00:00Z",
        "--fake-mode",
        "happy",
        "--build-mode",
        "adaptive_codex",
        "--attempt-limit",
        "2",
        "--overwrite",
    )

    payload = json.loads(result.stdout)
    eval_root = runs_root / "frontdesk-live-eval-adaptive"
    scenario = payload["scenarios"][0]
    workspace = eval_root / scenario["job_id"]

    assert payload["build_mode"] == "adaptive_codex"
    assert payload["totals"]["registered"] == 1
    assert scenario["status"] == "registered"
    assert scenario["build_path"]["mode"] == "adaptive_codex"
    assert scenario["forgeunit_skillfoundry"]["mode"] == "adaptive_codex"
    assert scenario["forgeunit_skillfoundry"]["verification_passed"] is True
    assert scenario["forgeunit_skillfoundry"]["registry_approved"] is True
    assert (workspace / "adaptive/attempts/001/codex_worker_input.md").is_file()
    assert (workspace / "adaptive/attempts/001/work_unit_result.json").is_file()
    assert (workspace / "adaptive/state_correction_001.json").is_file()
    assert (workspace / "package/skillfoundry.bundle.json").is_file()
    assert "frontdesk_eval_fake_codex_exec.py" not in result.stdout


def test_frontdesk_live_codex_eval_requires_explicit_mode(tmp_path: Path) -> None:
    result = _run_eval(
        tmp_path,
        "--runs-root",
        str(tmp_path / "runs"),
        "--eval-id",
        "frontdesk-live-eval-guard",
        "--limit",
        "1",
        expect_success=False,
    )

    assert result.returncode == 2
    assert "explicit mode required" in result.stderr
    assert not result.stdout.strip()


def test_frontdesk_live_codex_eval_refuses_existing_workspace_without_overwrite(tmp_path: Path) -> None:
    args = (
        "--runs-root",
        str(tmp_path / "runs"),
        "--eval-id",
        "frontdesk-live-eval-existing",
        "--registry-path",
        "registry.json",
        "--limit",
        "1",
        "--fake-mode",
        "happy",
    )
    _run_eval(tmp_path, *args, "--overwrite")

    result = _run_eval(tmp_path, *args, expect_success=False)

    assert result.returncode == 2
    assert "eval workspace already exists" in result.stderr
    assert not result.stdout.strip()


def test_semantic_fidelity_marker_matching_handles_phrase_markers() -> None:
    markers = _semantic_markers_from_payload(
        ["wiki root", "compact evidence", "conflict proposal"],
        "codexarium",
    )

    assert markers == ("wikiroot", "compactevidence", "conflictproposal")
    assert (
        _matched_marker_count(
            "The skill requires an explicit wiki root, compact evidence, and a conflict proposal.",
            markers,
        )
        == 3
    )


def test_semantic_fidelity_summary_normalizes_raw_phrase_markers(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "package").mkdir(parents=True)
    source_text = "Codexarium uses Rust, explicit wiki root, compact evidence, and conflict proposal."
    (workspace / "worker_input.md").write_text(source_text, encoding="utf-8")
    (workspace / "package" / "SKILL.md").write_text(source_text, encoding="utf-8")

    summary = _semantic_fidelity_summary(
        workspace,
        Scenario(
            "codexarium",
            "",
            semantic_markers=("Codexarium", "Rust", "wiki root", "compact evidence", "conflict proposal"),
        ),
        assess_package=True,
    )

    assert summary["passed"] is True
    assert summary["source_matched_marker_count"] == 5
    assert summary["package_matched_marker_count"] == 5


def _run_eval(tmp_path: Path, *args: str, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
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
            "FrontDesk live Codex eval script failed\n"
            f"returncode={result.returncode}\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}\n"
            f"tmp_path={tmp_path}"
        )
    return result
