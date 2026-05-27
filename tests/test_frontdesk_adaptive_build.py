import json
from pathlib import Path

from forgeunit_skillfoundry import FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
from skillfoundry.api import BUILD_PATH_ADAPTIVE_CODEX, SkillFoundryAPI
from skillfoundry.adaptive_workspace import adaptive_correction_ref, adaptive_observation_ref


def _create_and_approve_frontdesk_job(api: SkillFoundryAPI, job_id: str) -> None:
    created = api.handle(
        "POST",
        "/frontdesk/jobs",
        body={"job_id": job_id, "message": "Build a governed adaptive status skill."},
    ).json()
    assert created["status"] == "await_user_plan_review"
    approved = api.handle(
        "POST",
        f"/frontdesk/jobs/{job_id}/plan-review",
        body={"decision": "approve", "reason": "The governed plan is ready to build."},
    ).json()
    assert approved["status"] == "route_to_build"
    assert approved["state"]["readiness"] == "frozen"


def test_frontdesk_api_opt_in_adaptive_codex_happy_path_reaches_registered_closure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = SkillFoundryAPI(tmp_path / "runs")
    job_id = "frontdesk-adaptive-codex-happy"
    _create_and_approve_frontdesk_job(api, job_id)

    response = api.handle("POST", f"/frontdesk/jobs/{job_id}/build", body={"build_mode": "adaptive_codex"})

    assert response.status == 200
    serialized = response.body.decode("utf-8")
    assert "fake_api_adaptive_codex_exec.py" not in serialized
    payload = response.json()
    assert payload["status"] == "registered"
    assert payload["build_path"]["mode"] == BUILD_PATH_ADAPTIVE_CODEX
    assert payload["build_path"]["canonical"] is True
    assert payload["forgeunit_skillfoundry_summary_ref"] == FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    summary = payload["forgeunit_skillfoundry_summary"]
    assert summary["mode"] == BUILD_PATH_ADAPTIVE_CODEX
    assert summary["verification"]["passed"] is True
    assert summary["registry"]["approved"] is True
    assert summary["adaptive_summary"]["latest_route"] == "closure"
    assert summary["adaptive_summary"]["latest_decision"] == "close"
    assert summary["trust_boundaries"]["command_string_included"] is False

    run_root = tmp_path / "runs" / job_id
    observation = json.loads((run_root / adaptive_observation_ref(1)).read_text(encoding="utf-8"))
    assert observation["failures"] == []
    assert "verifier/verification_result.json" in observation["verifier_evidence"]
    assert "qa/acceptance_coverage_result.json" in observation["verifier_evidence"]
    assert "verifier/bundle_verification_result.json" in observation["verifier_evidence"]
    assert (run_root / "adaptive/attempts/001/codex_worker_input.md").is_file()
    work_unit = json.loads((run_root / "adaptive/attempts/001/work_unit_result.json").read_text(encoding="utf-8"))
    assert work_unit["commands_run"] == ["forgeunit codex command boundary"]
    assert "fake_api_adaptive_codex_exec.py" not in json.dumps(work_unit, sort_keys=True)
    assert (run_root / "package/skillfoundry.bundle.json").is_file()


def test_frontdesk_api_opt_in_adaptive_codex_routes_verifier_failure_to_repair(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = SkillFoundryAPI(tmp_path / "runs")
    job_id = "frontdesk-adaptive-codex-repair"
    _create_and_approve_frontdesk_job(api, job_id)

    response = api.handle(
        "POST",
        f"/frontdesk/jobs/{job_id}/build",
        body={"build_mode": "adaptive_forgeunit", "fake_mode": "repair", "attempt_limit": 3},
    )

    assert response.status == 200
    payload = response.json()
    summary = payload["forgeunit_skillfoundry_summary"]
    assert payload["build_path"]["mode"] == BUILD_PATH_ADAPTIVE_CODEX
    assert summary["mode"] == BUILD_PATH_ADAPTIVE_CODEX
    assert summary["adaptive_summary"]["latest_iteration"] == 2
    assert summary["adaptive_summary"]["latest_route"] == "closure"
    assert summary["registry"]["approved"] is True

    run_root = tmp_path / "runs" / job_id
    first_observation = json.loads((run_root / adaptive_observation_ref(1)).read_text(encoding="utf-8"))
    assert any(failure.startswith("skillfoundry_verifier:") for failure in first_observation["failures"])
    first_correction = json.loads((run_root / adaptive_correction_ref(1)).read_text(encoding="utf-8"))
    assert first_correction["next_route"] == "repair"
    second_correction = json.loads((run_root / adaptive_correction_ref(2)).read_text(encoding="utf-8"))
    assert second_correction["next_route"] == "closure"
    assert "fake_api_adaptive_repair_codex_exec.py" not in response.body.decode("utf-8")

