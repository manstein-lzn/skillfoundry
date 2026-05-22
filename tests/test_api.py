from __future__ import annotations

from io import BytesIO
import json
import sqlite3
import zipfile

from contextforge import ModelResponse, UsageDraft

import skillfoundry
from skillfoundry.cli import _build_parser
from skillfoundry import (
    APPROVAL_APPROVED,
    CONTEXTFORGE_VERIFICATION_RESULT_REF,
    GRAPH_V2_STATE_REF,
    GOAL_RUNTIME_LEDGER_REF,
    OWNED_LLM_WORKER_OUTPUT_SCHEMA_VERSION,
    OfflineWorkerMode,
    OwnedLLMSkillBuilderWorker,
    SkillFoundryAPI,
    initialize_frontdesk_workspace,
    initialize_job_workspace,
    run_offline_goal_harness,
    validate_v2_graph_state,
    write_frontdesk_artifact,
    write_frontdesk_v2_contract_artifacts,
)
from skillfoundry.schema import sha256_file


REQ_TEXT = """# API pytest skill

Build a local SkillFoundry package that exposes the offline factory through a
minimal internal API and lets a reviewer download only approved packages.
"""

API_OWNED_SKILL = """---
name: api-owned-status-skill
description: API status fixture for owned LLM Goal Harness usage.
---

# API Owned Status Skill
"""


class ScriptedAPIModelClient:
    def invoke(self, messages, model, params, tools=None):
        payload = {
            "schema_version": OWNED_LLM_WORKER_OUTPUT_SCHEMA_VERSION,
            "skill_markdown": API_OWNED_SKILL,
            "reference_files": [],
            "script_files": [],
            "test_files": [],
        }
        return (
            ModelResponse(
                text=json.dumps(payload, sort_keys=True),
                raw_response_artifact_ref=None,
                finish_reason="stop",
                metadata={"scripted_api_status": True},
            ),
            None,
            UsageDraft(
                input_tokens=120,
                cached_input_tokens=90,
                cache_telemetry_status="reported",
                output_tokens=30,
                cost_usd=0.0123,
                latency_ms=456,
                provider_payload={"raw_provider_payload": "must-not-leak"},
            ),
        )


def make_api(tmp_path, *, allow_legacy_offline_jobs: bool = False) -> SkillFoundryAPI:
    return SkillFoundryAPI(tmp_path / "runs", allow_legacy_offline_jobs=allow_legacy_offline_jobs)


def make_legacy_api(tmp_path) -> SkillFoundryAPI:
    return make_api(tmp_path, allow_legacy_offline_jobs=True)


def post_job(api: SkillFoundryAPI, **overrides):
    payload = {
        "job_id": "api-ok",
        "requirement": REQ_TEXT,
    }
    payload.update(overrides)
    return api.handle(
        "POST",
        "/jobs",
        body=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )


def response_json(response):
    return json.loads(response.body.decode("utf-8"))


def test_api_is_exported():
    assert skillfoundry.SkillFoundryAPI is SkillFoundryAPI


def test_post_jobs_legacy_offline_route_is_disabled_by_default(tmp_path):
    api = make_api(tmp_path)

    response = post_job(api)
    payload = response_json(response)

    assert response.status == 403
    assert payload["error"]["code"] == "legacy_offline_jobs_disabled"
    assert "/frontdesk/jobs/{job_id}/build" in payload["error"]["message"]
    assert not (tmp_path / "runs" / "api-ok" / "final_report.json").exists()


def test_post_jobs_legacy_offline_route_can_be_enabled_with_constructor_flag(tmp_path):
    api = make_legacy_api(tmp_path)

    response = post_job(api)
    payload = response_json(response)

    assert response.status == 201
    assert payload["job_id"] == "api-ok"
    assert payload["final_status"] == "registered"
    assert payload["build_path"]["mode"] == "legacy_offline_compatibility"
    assert payload["build_path"]["canonical"] is False
    assert payload["build_path"]["legacy_compatibility"] is True
    assert payload["report"]["final_status"] == "registered"
    assert payload["package_downloadable"] is True
    assert (tmp_path / "runs" / "api-ok" / "final_report.json").is_file()
    assert (tmp_path / "runs" / ".api_requirements" / "api-ok.md").is_file()


def test_post_jobs_legacy_offline_route_can_be_enabled_with_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLFOUNDRY_ALLOW_LEGACY_OFFLINE_JOBS", "1")
    api = SkillFoundryAPI(tmp_path / "runs")

    response = post_job(api, job_id="api-env")
    payload = response_json(response)

    assert response.status == 201
    assert payload["job_id"] == "api-env"
    assert payload["build_path"]["mode"] == "legacy_offline_compatibility"


def test_cli_serve_legacy_flag_preserves_env_default():
    parser = _build_parser()

    default_args = parser.parse_args(["serve", "--runs-root", "runs"])
    enabled_args = parser.parse_args(["serve", "--runs-root", "runs", "--allow-legacy-offline-jobs"])

    assert default_args.allow_legacy_offline_jobs is None
    assert enabled_args.allow_legacy_offline_jobs is True


def test_get_jobs_lists_created_jobs(tmp_path):
    api = make_legacy_api(tmp_path)
    post_job(api, job_id="api-list")

    response = api.handle("GET", "/jobs")
    payload = response_json(response)

    assert response.status == 200
    assert payload["count"] == 1
    assert payload["jobs"][0]["job_id"] == "api-list"
    assert payload["jobs"][0]["final_status"] == "registered"
    assert payload["jobs"][0]["build_path"]["mode"] == "legacy_offline_compatibility"


def test_get_job_report_returns_final_report(tmp_path):
    api = make_legacy_api(tmp_path)
    post_job(api, job_id="api-report")

    response = api.handle("GET", "/jobs/api-report/report")
    payload = response_json(response)

    assert response.status == 200
    assert payload["job_id"] == "api-report"
    assert payload["final_status"] == "registered"
    assert payload["refs"]["verifier_result"]["passed"] is True


def test_get_job_contextforge_status_exposes_v2_refs_without_raw_content(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "api-v2-status")
    result = run_offline_goal_harness(workspace, created_at="2026-05-22T00:00:00Z")
    api = make_api(tmp_path)

    response = api.handle("GET", "/jobs/api-v2-status/contextforge")
    payload = response_json(response)
    body_text = response.body.decode("utf-8")

    assert response.status == 200
    assert payload["schema_version"] == "skillfoundry.api.contextforge_status.v1"
    assert payload["refs"]["goal_contract"]["exists"] is True
    assert payload["refs"]["goal_runtime_result"]["exists"] is True
    assert payload["cache"]["cache_plan_id"] == result.runtime_result["ids"]["cache_plan_id"]
    assert payload["cache"]["ledger_status"] == "available"
    assert payload["cache"]["cache_telemetry_status"] == result.harness_result.compiled_context.cache_plan.cache_telemetry_status
    assert payload["cache"]["expected_cacheable_tokens"] == (
        result.harness_result.compiled_context.cache_plan.expected_cacheable_tokens
    )
    assert payload["worker"]["worker_run_id"] == result.harness_result.worker_run.worker_run_id
    assert payload["worker"]["worker_kind"] == "fake_model"
    assert payload["worker"]["status"] == "completed"
    assert payload["worker"]["model_call_count"] == 0
    assert payload["usage"]["usage_available"] is False
    assert payload["status"]["verification"]["status"] == "passed"
    assert payload["raw_context_included"] is False
    assert payload["cache"]["raw_prompt_included"] is False
    assert "Offline Goal Harness Skill" not in body_text


def test_get_job_contextforge_status_exposes_repair_and_human_review_refs_without_raw_content(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "api-v2-repair-status")
    marker = "RAW_API_REPAIR_MARKER_SHOULD_NOT_LEAK"
    repair_dir = workspace.resolve_path("attempts/002")
    repair_dir.mkdir(parents=True, exist_ok=True)
    contextforge_dir = workspace.resolve_path("contextforge")
    contextforge_dir.mkdir(parents=True, exist_ok=True)
    human_review_dir = workspace.resolve_path("human_review")
    human_review_dir.mkdir(parents=True, exist_ok=True)

    refs = {
        "repair_attempt": "attempts/002/repair_attempt.json",
        "repair_instructions": "attempts/002/repair_instructions.md",
        "repair_runtime_result": "contextforge/repair_goal_runtime_result_002.json",
        "repair_graph_state": "contextforge/repair_goal_harness_state_002.json",
        "human_review_request": "human_review/request.json",
    }
    workspace.resolve_path(refs["repair_attempt"]).write_text(
        json.dumps({"attempt_id": "002", "raw": marker}),
        encoding="utf-8",
    )
    workspace.resolve_path(refs["repair_instructions"]).write_text(marker, encoding="utf-8")
    workspace.resolve_path(refs["repair_runtime_result"]).write_text(
        json.dumps({"status": "failed", "raw": marker}),
        encoding="utf-8",
    )
    workspace.resolve_path(refs["repair_graph_state"]).write_text(
        json.dumps({"status": "failed", "raw": marker}),
        encoding="utf-8",
    )
    workspace.resolve_path(refs["human_review_request"]).write_text(
        json.dumps({"reason": "verification_failed", "raw": marker}),
        encoding="utf-8",
    )
    state = {
        "schema_version": "skillfoundry.graph_v2_state.v1",
        "job_id": workspace.job_id,
        "stage": "human_review",
        "status": "human_review_required",
        "attempt_count": 2,
        "attempt_limit": 2,
        "refs": refs,
        "hashes": {},
        "contextforge": {
            "last_repair_attempt_id": "002",
            "repair_status": "completed",
            "last_repair_goal_run_id": "repair-goal-run",
            "last_repair_worker_run_id": "repair-worker-run",
            "last_repair_context_view_id": "repair-context-view",
            "last_repair_prompt_cache_plan_id": "repair-cache-plan",
            "last_verification_status": "failed",
            "registry_approved": False,
            "worker_self_report_is_not_acceptance": True,
        },
        "human_review_required": True,
        "next_route": "continue",
    }
    validate_v2_graph_state(state)
    workspace.resolve_path(GRAPH_V2_STATE_REF).parent.mkdir(parents=True, exist_ok=True)
    workspace.resolve_path(GRAPH_V2_STATE_REF).write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    api = make_api(tmp_path)

    response = api.handle("GET", f"/jobs/{workspace.job_id}/contextforge")
    payload = response_json(response)
    body_text = response.body.decode("utf-8")

    assert response.status == 200
    assert payload["build_path"]["mode"] == "graph_v2_goal_harness"
    assert payload["status"]["graph_v2"]["last_repair_attempt_id"] == "002"
    assert payload["status"]["graph_v2"]["repair_status"] == "completed"
    assert payload["status"]["graph_v2"]["worker_self_report_is_not_acceptance"] is True
    assert payload["repair_evidence"]["available"] is True
    assert payload["repair_evidence"]["attempt_id"] == "002"
    assert payload["repair_evidence"]["refs"]["repair_attempt"]["exists"] is True
    assert payload["repair_evidence"]["refs"]["repair_runtime_result"]["exists"] is True
    assert payload["repair_evidence"]["raw_transcript_included"] is False
    assert payload["human_review"]["required"] is True
    assert payload["human_review"]["request"]["exists"] is True
    assert payload["human_review"]["raw_prompt_included"] is False
    assert marker not in body_text
    assert "worker_transcript" not in body_text


def test_get_job_html_evidence_view_exposes_refs_without_raw_content(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "api-v2-html-evidence")
    marker = "RAW_API_HTML_EVIDENCE_MARKER_SHOULD_NOT_LEAK"
    repair_dir = workspace.resolve_path("attempts/002")
    repair_dir.mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("contextforge").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("human_review").mkdir(parents=True, exist_ok=True)

    refs = {
        "repair_attempt": "attempts/002/repair_attempt.json",
        "repair_instructions": "attempts/002/repair_instructions.md",
        "repair_runtime_result": "contextforge/repair_goal_runtime_result_002.json",
        "repair_graph_state": "contextforge/repair_goal_harness_state_002.json",
        "human_review_request": "human_review/request.json",
    }
    workspace.resolve_path(refs["repair_attempt"]).write_text(
        json.dumps({"attempt_id": "002", "raw": marker}),
        encoding="utf-8",
    )
    workspace.resolve_path(refs["repair_instructions"]).write_text(marker, encoding="utf-8")
    workspace.resolve_path(refs["repair_runtime_result"]).write_text(
        json.dumps({"status": "failed", "raw": marker}),
        encoding="utf-8",
    )
    workspace.resolve_path(refs["repair_graph_state"]).write_text(
        json.dumps({"status": "failed", "raw": marker}),
        encoding="utf-8",
    )
    workspace.resolve_path(refs["human_review_request"]).write_text(
        json.dumps({"reason": "verification_failed", "raw": marker}),
        encoding="utf-8",
    )
    state = {
        "schema_version": "skillfoundry.graph_v2_state.v1",
        "job_id": workspace.job_id,
        "stage": "human_review",
        "status": "human_review_required",
        "attempt_count": 2,
        "attempt_limit": 2,
        "refs": refs,
        "hashes": {},
        "contextforge": {
            "last_repair_attempt_id": "002",
            "repair_status": "completed",
            "last_repair_goal_run_id": "repair-goal-run",
            "last_repair_worker_run_id": "repair-worker-run",
            "last_repair_context_view_id": "repair-context-view",
            "last_repair_prompt_cache_plan_id": "repair-cache-plan",
            "human_review_reason_code": "verification_failed",
            "last_verification_status": "failed",
            "worker_self_report_is_not_acceptance": True,
        },
        "human_review_required": True,
        "next_route": "continue",
    }
    validate_v2_graph_state(state)
    workspace.resolve_path(GRAPH_V2_STATE_REF).parent.mkdir(parents=True, exist_ok=True)
    workspace.resolve_path(GRAPH_V2_STATE_REF).write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    api = make_api(tmp_path)

    response = api.handle("GET", f"/jobs/{workspace.job_id}", headers={"Accept": "text/html"})
    html = response.body.decode("utf-8")

    assert response.status == 200
    assert response.content_type.startswith("text/html")
    assert "graph_v2_goal_harness" in html
    assert "repair-cache-plan" in html
    assert "human_review/request.json" in html
    assert "/jobs/api-v2-html-evidence/contextforge" in html
    assert "/jobs/api-v2-html-evidence/human-review" in html
    assert marker not in html
    assert "worker_transcript" not in html
    assert "package/SKILL.md" not in html


def test_get_job_html_evidence_view_omits_package_link_when_not_downloadable(tmp_path):
    api = make_legacy_api(tmp_path)
    post_job(
        api,
        job_id="api-html-failed",
        worker_mode=OfflineWorkerMode.ALWAYS_INVALID.value,
        attempt_limit=1,
    )

    response = api.handle("GET", "/jobs/api-html-failed", headers={"Accept": "text/html"})
    html = response.body.decode("utf-8")

    assert response.status == 200
    assert "Download package" not in html
    assert "/jobs/api-html-failed/package.zip" not in html
    assert "not downloadable" in html


def test_human_review_decision_records_artifacts_without_raw_content(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "api-human-review-decision")
    workspace.resolve_path("contextforge").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("human_review").mkdir(parents=True, exist_ok=True)
    marker = "RAW_HUMAN_REVIEW_MARKER_SHOULD_NOT_LEAK"
    workspace.resolve_path("acceptance_criteria.yaml").write_text(
        "criteria:\n- id: AC-MANUAL\n  description: Manual check.\n",
        encoding="utf-8",
    )
    request_ref = "human_review/request.json"
    workspace.resolve_path(request_ref).write_text(
        json.dumps(
            {
                "schema_version": "skillfoundry.human_review_request.v1",
                "request_id": "api-human-review-decision:human-review:2",
                "job_id": workspace.job_id,
                "status": "open",
                "reason_code": "human_acceptance_required",
                "raw": marker,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    state = {
        "schema_version": "skillfoundry.graph_v2_state.v1",
        "job_id": workspace.job_id,
        "stage": "human_review",
        "status": "human_review_required",
        "attempt_count": 2,
        "attempt_limit": 2,
        "refs": {"human_review_request": request_ref},
        "hashes": {"human_review_request": sha256_file(workspace.resolve_path(request_ref, must_exist=True))},
        "contextforge": {
            "last_verification_status": "human_acceptance_required",
            "human_review_request_id": "api-human-review-decision:human-review:2",
            "human_review_request_ref": request_ref,
            "human_review_reason_code": "human_acceptance_required",
        },
        "human_review_required": True,
        "next_route": "continue",
    }
    validate_v2_graph_state(state)
    workspace.resolve_path(GRAPH_V2_STATE_REF).write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    api = make_api(tmp_path)

    response = api.handle(
        "POST",
        f"/jobs/{workspace.job_id}/human-review",
        body={
            "decision": "approve",
            "reviewer_id": "reviewer-001",
            "reviewer_role": "qa_lead",
            "reason": "Manual acceptance reviewed the listed criterion.",
            "covered_criterion_ids": ["AC-MANUAL"],
            "created_at": "2026-05-22T00:00:00Z",
        },
    )
    payload = response_json(response)
    body_text = response.body.decode("utf-8")

    assert response.status == 200
    assert payload["decision"] == "approve"
    assert payload["decision_ref"] == "human_review/decision.json"
    assert payload["manual_acceptance_record"]["ref"] == "qa/manual_acceptance_record.json"
    assert workspace.resolve_path("human_review/decision.json", must_exist=True).is_file()
    manual = json.loads(workspace.resolve_path("qa/manual_acceptance_record.json", must_exist=True).read_text())
    assert manual["decision"] == "approved"
    assert manual["covered_criterion_ids"] == ["AC-MANUAL"]
    assert marker not in body_text

    status_response = api.handle("GET", f"/jobs/{workspace.job_id}/contextforge")
    status_payload = response_json(status_response)
    status_text = status_response.body.decode("utf-8")

    assert status_payload["human_review"]["decision"]["decision"] == "approve"
    assert status_payload["human_review"]["decision"]["manual_acceptance_record"]["ref"] == "qa/manual_acceptance_record.json"
    assert status_payload["human_review"]["raw_payload_included"] is False
    assert marker not in status_text

    human_review_response = api.handle("GET", f"/jobs/{workspace.job_id}/human-review")
    human_review_payload = response_json(human_review_response)
    human_review_text = human_review_response.body.decode("utf-8")

    assert human_review_response.status == 200
    assert human_review_payload["human_review"]["required"] is True
    assert human_review_payload["human_review"]["decision"]["decision"] == "approve"
    assert human_review_payload["human_review"]["decision"]["manual_acceptance_record"]["ref"] == "qa/manual_acceptance_record.json"
    assert marker not in human_review_text


def test_human_review_decision_rejects_stale_request_hash_before_side_effects(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "api-human-review-stale-request")
    workspace.resolve_path("contextforge").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("human_review").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("acceptance_criteria.yaml").write_text(
        "criteria:\n- id: AC-MANUAL\n  description: Manual check.\n",
        encoding="utf-8",
    )
    request_ref = "human_review/request.json"
    workspace.resolve_path(request_ref).write_text(
        json.dumps(
            {
                "schema_version": "skillfoundry.human_review_request.v1",
                "request_id": "api-human-review-stale-request:human-review:1",
                "job_id": workspace.job_id,
                "status": "open",
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    original_request_hash = sha256_file(workspace.resolve_path(request_ref, must_exist=True))
    state = {
        "schema_version": "skillfoundry.graph_v2_state.v1",
        "job_id": workspace.job_id,
        "stage": "human_review",
        "status": "human_review_required",
        "attempt_count": 1,
        "attempt_limit": 1,
        "refs": {"human_review_request": request_ref},
        "hashes": {"human_review_request": original_request_hash},
        "contextforge": {"last_verification_status": "human_acceptance_required"},
        "human_review_required": True,
        "next_route": "continue",
    }
    validate_v2_graph_state(state)
    workspace.resolve_path(GRAPH_V2_STATE_REF).write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    workspace.resolve_path(request_ref, must_exist=True).write_text(
        json.dumps({"schema_version": "skillfoundry.human_review_request.v1", "job_id": workspace.job_id, "tampered": True}),
        encoding="utf-8",
    )
    api = make_api(tmp_path)

    response = api.handle(
        "POST",
        f"/jobs/{workspace.job_id}/human-review",
        body={
            "decision": "approve",
            "reviewer_id": "reviewer-001",
            "reviewer_role": "qa_lead",
            "reason": "Should fail before recording authority.",
            "covered_criterion_ids": ["AC-MANUAL"],
        },
    )
    payload = response_json(response)

    assert response.status == 409
    assert payload["error"]["code"] == "human_review_request_stale"
    assert not workspace.resolve_path("human_review/decision.json").exists()
    assert not (workspace.root / "qa" / "manual_acceptance_record.json").exists()


def test_human_review_decision_rejects_agent_reviewer(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "api-human-review-agent-reject")
    workspace.resolve_path("contextforge").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("human_review").mkdir(parents=True, exist_ok=True)
    request_ref = "human_review/request.json"
    workspace.resolve_path(request_ref).write_text(
        json.dumps({"schema_version": "skillfoundry.human_review_request.v1", "job_id": workspace.job_id}),
        encoding="utf-8",
    )
    state = {
        "schema_version": "skillfoundry.graph_v2_state.v1",
        "job_id": workspace.job_id,
        "stage": "human_review",
        "status": "human_review_required",
        "attempt_count": 1,
        "attempt_limit": 1,
        "refs": {"human_review_request": request_ref},
        "hashes": {"human_review_request": sha256_file(workspace.resolve_path(request_ref, must_exist=True))},
        "contextforge": {"last_verification_status": "review_required"},
        "human_review_required": True,
        "next_route": "continue",
    }
    validate_v2_graph_state(state)
    workspace.resolve_path(GRAPH_V2_STATE_REF).write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    api = make_api(tmp_path)

    response = api.handle(
        "POST",
        f"/jobs/{workspace.job_id}/human-review",
        body={
            "decision": "reject",
            "reviewer_id": "agent-reviewer",
            "reviewer_role": "agent",
            "reason": "Automated reviewers cannot provide human authority.",
        },
    )
    payload = response_json(response)

    assert response.status == 403
    assert payload["error"]["code"] == "human_reviewer_required"
    assert not workspace.resolve_path("human_review/decision.json").exists()


def test_get_job_contextforge_status_rejects_invalid_graph_v2_state_as_canonical(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "api-v2-invalid-graph-state")
    workspace.resolve_path("contextforge").mkdir(parents=True, exist_ok=True)
    graph_state_path = workspace.resolve_path(GRAPH_V2_STATE_REF)
    graph_state_path.write_text("{invalid-json", encoding="utf-8")
    api = make_api(tmp_path)

    response = api.handle("GET", f"/jobs/{workspace.job_id}/contextforge")
    payload = response_json(response)

    assert response.status == 200
    assert payload["refs"]["graph_v2_state"]["exists"] is True
    assert payload["refs"]["graph_v2_state"]["valid_json"] is False
    assert payload["refs"]["graph_v2_state"]["error_code"] == "invalid_json"
    assert payload["build_path"]["mode"] == "workspace_only"
    assert payload["build_path"]["canonical"] is False
    assert payload["build_path"]["graph_v2_state_valid"] is False
    assert payload["status"]["graph_v2"] == {
        "valid": False,
        "error_code": "invalid_graph_v2_state",
    }


def test_get_job_contextforge_status_exposes_owned_llm_usage_without_raw_payload(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "api-v2-owned-status")
    result = run_offline_goal_harness(
        workspace,
        created_at="2026-05-22T00:00:00Z",
        worker_factory=lambda worker_workspace: OwnedLLMSkillBuilderWorker(
            worker_workspace,
            client=ScriptedAPIModelClient(),
            provider="scripted",
            model="api-status-model",
        ),
    )
    api = make_api(tmp_path)

    response = api.handle("GET", "/jobs/api-v2-owned-status/contextforge")
    payload = response_json(response)
    body_text = response.body.decode("utf-8")

    assert response.status == 200
    assert payload["worker"]["worker_run_id"] == result.harness_result.worker_run.worker_run_id
    assert payload["worker"]["worker_kind"] == "llm"
    assert payload["worker"]["model_call_count"] == 1
    assert payload["worker"]["prompt_view_count"] >= 1
    assert payload["model_calls"][0]["provider"] == "scripted"
    assert payload["model_calls"][0]["model"] == "api-status-model"
    assert payload["model_calls"][0]["success"] is True
    assert payload["model_calls"][0]["replay_bundle_ref"].startswith("artifact:")
    assert payload["usage"]["usage_available"] is True
    assert payload["usage"]["provider"] == "scripted"
    assert payload["usage"]["model"] == "api-status-model"
    assert payload["usage"]["input_tokens"] == 120
    assert payload["usage"]["cached_input_tokens"] == 90
    assert payload["usage"]["output_tokens"] == 30
    assert payload["usage"]["cost_usd"] == 0.0123
    assert payload["usage"]["latency_ms"] == 456
    assert payload["usage"]["cache_telemetry_status"] == "reported"
    assert payload["cache"]["raw_prompt_included"] is False
    assert "API Owned Status Skill" not in body_text
    assert "raw_provider_payload" not in body_text
    assert "scripted_api_status" not in body_text


def test_get_job_contextforge_status_corrupt_ledger_degrades_without_verification_fallback(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "api-v2-corrupt-ledger")
    run_offline_goal_harness(workspace, created_at="2026-05-22T00:00:00Z")
    workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF, must_exist=True).write_text("not a sqlite database", encoding="utf-8")
    workspace.resolve_path(CONTEXTFORGE_VERIFICATION_RESULT_REF).write_text("{invalid-json", encoding="utf-8")
    api = make_api(tmp_path)

    response = api.handle("GET", "/jobs/api-v2-corrupt-ledger/contextforge")
    payload = response_json(response)

    assert response.status == 200
    assert payload["cache"]["ledger_status"] == "unavailable"
    assert payload["worker"]["ledger_status"] == "unavailable"
    assert payload["usage"]["ledger_status"] == "unavailable"
    assert payload["model_calls"] == []
    assert payload["status"]["verification"]["status"] == "invalid"
    assert payload["status"]["verification"]["passed"] is False


def test_get_job_contextforge_status_missing_ledger_table_degrades_to_unavailable(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "api-v2-missing-ledger-table")
    run_offline_goal_harness(workspace, created_at="2026-05-22T00:00:00Z")
    ledger_path = workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF, must_exist=True)
    connection = sqlite3.connect(ledger_path)
    try:
        connection.execute("DROP TABLE worker_runs")
        connection.commit()
    finally:
        connection.close()
    api = make_api(tmp_path)

    response = api.handle("GET", "/jobs/api-v2-missing-ledger-table/contextforge")
    payload = response_json(response)

    assert response.status == 200
    assert payload["worker"]["ledger_status"] == "unavailable"
    assert payload["usage"]["ledger_status"] == "unavailable"
    assert payload["model_calls"] == []
    assert payload["status"]["verification"]["status"] == "passed"


def test_get_job_contextforge_status_missing_model_call_uses_allowlisted_shape(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "api-v2-missing-model-call")
    result = run_offline_goal_harness(
        workspace,
        created_at="2026-05-22T00:00:00Z",
        worker_factory=lambda worker_workspace: OwnedLLMSkillBuilderWorker(
            worker_workspace,
            client=ScriptedAPIModelClient(),
            provider="scripted",
            model="api-status-model",
        ),
    )
    worker_payload = result.harness_result.worker_run.to_dict()
    worker_payload["model_call_ids"] = ["missing-model-call"]
    worker_json = json.dumps(worker_payload, sort_keys=True)
    connection = sqlite3.connect(workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF, must_exist=True))
    try:
        connection.execute(
            "UPDATE worker_runs SET payload_json = ?, payload_bytes = ? WHERE id = ?",
            (
                worker_json,
                len(worker_json.encode("utf-8")),
                result.harness_result.worker_run.worker_run_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    api = make_api(tmp_path)

    response = api.handle("GET", "/jobs/api-v2-missing-model-call/contextforge")
    payload = response_json(response)

    assert response.status == 200
    allowed_keys = {
        "model_call_id",
        "prompt_view_id",
        "provider",
        "model",
        "success",
        "usage_id",
        "usage_unavailable_reason",
        "replay_bundle_ref",
        "error_type",
    }
    assert set(payload["model_calls"][0]) <= allowed_keys
    assert payload["model_calls"][0] == {
        "model_call_id": "missing-model-call",
        "prompt_view_id": None,
        "provider": None,
        "model": None,
        "success": False,
        "usage_id": None,
        "usage_unavailable_reason": "model call record referenced by worker run is missing",
        "replay_bundle_ref": None,
        "error_type": "missing_model_call_record",
    }
    assert "status" not in payload["model_calls"][0]


def test_get_job_contextforge_status_includes_frontdesk_v2_governance(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "api-frontdesk-v2-status")
    frontdesk = initialize_frontdesk_workspace(workspace)
    write_frontdesk_artifact(
        frontdesk,
        "risk_report.json",
        {
            "schema_version": "skillfoundry.frontdesk_risk_report.v1",
            "risk_flags": [],
            "redaction_status": "complete",
            "provider_usage": {
                "usage_available": False,
                "usage_unavailable_reason": "Offline fixture does not expose provider usage.",
            },
        },
    )
    write_frontdesk_artifact(frontdesk, "solution_plan.json", {"status": "approved"})
    write_frontdesk_v2_contract_artifacts(frontdesk, created_at="2026-05-22T00:00:00Z")
    api = make_api(tmp_path)

    response = api.handle("GET", "/jobs/api-frontdesk-v2-status/contextforge")
    payload = response_json(response)

    assert response.status == 200
    assert payload["refs"]["frontdesk_v2_goal_contract"]["exists"] is True
    assert payload["refs"]["frontdesk_v2_governance_report"]["exists"] is True
    assert payload["frontdesk_v2"]["governance"]["status"] == "ready_for_freeze"
    assert payload["frontdesk_v2"]["governance"]["provider_usage"]["usage_available"] is False


def test_get_job_contextforge_status_missing_job_uses_api_error_model(tmp_path):
    api = make_api(tmp_path)

    response = api.handle("GET", "/jobs/missing-v2/contextforge")
    payload = response_json(response)

    assert response.status == 404
    assert payload["error"]["code"] == "job_not_found"


def test_get_job_contextforge_status_invalid_verification_artifact_does_not_fallback_to_passed(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "api-v2-invalid-verification")
    run_offline_goal_harness(workspace, created_at="2026-05-22T00:00:00Z")
    workspace.resolve_path(CONTEXTFORGE_VERIFICATION_RESULT_REF).write_text("{invalid-json", encoding="utf-8")
    api = make_api(tmp_path)

    response = api.handle("GET", "/jobs/api-v2-invalid-verification/contextforge")
    payload = response_json(response)

    assert response.status == 200
    assert payload["refs"]["contextforge_verification_result"]["exists"] is True
    assert payload["refs"]["contextforge_verification_result"]["valid_json"] is False
    assert payload["refs"]["contextforge_verification_result"]["error_code"] == "invalid_json"
    assert payload["status"]["verification"]["status"] == "invalid"
    assert payload["status"]["verification"]["passed"] is False


def test_get_job_contextforge_status_directory_verification_artifact_uses_status_model(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "api-v2-directory-verification")
    run_offline_goal_harness(workspace, created_at="2026-05-22T00:00:00Z")
    workspace.resolve_path(CONTEXTFORGE_VERIFICATION_RESULT_REF).mkdir()
    api = make_api(tmp_path)

    response = api.handle("GET", "/jobs/api-v2-directory-verification/contextforge")
    payload = response_json(response)

    assert response.status == 200
    assert payload["refs"]["contextforge_verification_result"]["exists"] is True
    assert payload["refs"]["contextforge_verification_result"]["kind"] == "directory"
    assert payload["refs"]["contextforge_verification_result"]["valid_json"] is False
    assert payload["refs"]["contextforge_verification_result"]["error_code"] == "not_file"
    assert payload["status"]["verification"]["status"] == "invalid"
    assert payload["status"]["verification"]["passed"] is False


def test_get_registry_returns_default_approved_entries(tmp_path):
    api = make_legacy_api(tmp_path)
    post_job(api, job_id="api-registry")
    post_job(
        api,
        job_id="api-failed",
        worker_mode=OfflineWorkerMode.ALWAYS_INVALID.value,
        attempt_limit=1,
    )

    response = api.handle("GET", "/registry")
    payload = response_json(response)

    assert response.status == 200
    assert payload["count"] == 1
    assert payload["entries"][0]["build_job_id"] == "api-registry"
    assert payload["entries"][0]["approval_status"] == APPROVAL_APPROVED
    assert payload["entries"][0]["quarantine_status"] == "none"


def test_approved_package_download_returns_zip_with_skill_md(tmp_path):
    api = make_legacy_api(tmp_path)
    post_job(api, job_id="api-download")

    response = api.handle("GET", "/jobs/api-download/package.zip")

    assert response.status == 200
    assert response.content_type == "application/zip"
    with zipfile.ZipFile(BytesIO(response.body)) as archive:
        names = archive.namelist()
        assert "package/SKILL.md" in names
        assert all(name.startswith("package/") for name in names)


def test_failed_job_package_download_is_denied(tmp_path):
    api = make_legacy_api(tmp_path)
    failed = post_job(
        api,
        job_id="api-failed",
        worker_mode=OfflineWorkerMode.ALWAYS_INVALID.value,
        attempt_limit=1,
    )
    failed_payload = response_json(failed)

    assert failed_payload["final_status"] == "fail_closed"
    assert failed_payload["package_downloadable"] is False

    response = api.handle("GET", "/jobs/api-failed/package.zip")
    payload = response_json(response)

    assert response.status == 403
    assert payload["error"]["code"] == "package_not_approved"


def test_rejected_unsafe_job_package_download_is_denied(tmp_path):
    api = make_legacy_api(tmp_path)
    rejected = post_job(
        api,
        job_id="api-rejected",
        requirement="reject_unsafe: delete / and steal credentials",
    )
    rejected_payload = response_json(rejected)

    assert rejected_payload["final_status"] == "rejected"

    response = api.handle("GET", "/jobs/api-rejected/package.zip")
    payload = response_json(response)

    assert response.status == 403
    assert payload["error"]["code"] == "package_not_approved"


def test_path_traversal_job_id_and_artifact_path_are_rejected(tmp_path):
    api = make_legacy_api(tmp_path)
    post_job(api, job_id="api-safe")

    create_response = api.handle(
        "POST",
        "/jobs",
        body={"job_id": "../escape", "requirement": REQ_TEXT},
    )
    report_response = api.handle("GET", "/jobs/%2e%2e/report")
    artifact_response = api.handle("GET", "/jobs/api-safe/package/../SKILL.md")

    assert create_response.status == 400
    assert response_json(create_response)["error"]["code"] == "invalid_job_id"
    assert report_response.status == 400
    assert artifact_response.status == 400


def test_html_ui_hides_legacy_offline_factory_form_by_default(tmp_path):
    api = make_api(tmp_path)

    response = api.handle("GET", "/")
    html = response.body.decode("utf-8")

    assert response.status == 200
    assert 'action="/frontdesk/jobs"' in html
    assert 'action="/jobs"' not in html
    assert "离线工厂" not in html
    assert "离线 Job" in html


def test_html_ui_shows_legacy_offline_factory_form_when_enabled(tmp_path):
    api = make_legacy_api(tmp_path)

    response = api.handle("GET", "/")
    html = response.body.decode("utf-8")

    assert response.status == 200
    assert 'action="/jobs"' in html
    assert "离线工厂" in html


def test_html_ui_renders_links_and_does_not_mark_failed_jobs_as_downloadable(tmp_path):
    api = make_legacy_api(tmp_path)
    post_job(api, job_id="ui-ok")
    post_job(
        api,
        job_id="ui-failed",
        worker_mode=OfflineWorkerMode.ALWAYS_INVALID.value,
        attempt_limit=1,
    )

    response = api.handle("GET", "/")
    html = response.body.decode("utf-8")

    assert response.status == 200
    assert "/jobs/ui-ok/report" in html
    assert "/jobs/ui-ok/package.zip" in html
    assert "/jobs/ui-failed/report" in html
    assert "/jobs/ui-failed/package.zip" not in html
    assert "ui-ok-skill" in html
    assert "ui-failed-skill" not in html


def test_frontdesk_question_html_deduplicates_inline_options(tmp_path):
    api = make_api(tmp_path)

    html = api._questions_html(
        [
            {
                "text": "Which problem should this skill solve? Choose one: A) Find old answers; B) Clean notes",
                "options": ["A) Find old answers", "B) Clean notes", "C) Other"],
                "reason": "Start from the user's real pain.",
            }
        ],
        readiness="needs_clarification",
        next_action="ask_user",
    )

    assert "Which problem should this skill solve? Choose one" in html
    assert "A) Find old answers; B) Clean notes" not in html
    assert "A. A) Find old answers" not in html
    assert ">Find old answers<" in html


def test_frontdesk_question_html_preserves_rich_inline_options(tmp_path):
    api = make_api(tmp_path)

    html = api._questions_html(
        [
            {
                "text": (
                    "你希望这个 Skill 每天帮你产出的知识库结果是哪一种？ "
                    "A. 每日增量摘要：按日期汇总今天/最近对话中的关键决策、代码经验、待办和灵感； "
                    "B. 项目 wiki：围绕项目沉淀背景、架构、决策和当前进展； "
                    "C. 最佳实践库：提炼可复用经验、踩坑记录和操作手册"
                ),
                "options": ["每日增量摘要", "项目 wiki", "最佳实践库"],
                "reason": "明确产出形态，才能决定 Skill 的整理方式。",
            }
        ],
        readiness="needs_clarification",
        next_action="ask_user",
    )

    assert "你希望这个 Skill 每天帮你产出的知识库结果是哪一种？" in html
    assert "关键决策、代码经验、待办和灵感" in html
    assert "围绕项目沉淀背景、架构、决策和当前进展" in html
    assert ">每日增量摘要：" in html
    assert "A. A." not in html


def test_frontdesk_submit_script_serializes_plan_review_fields(tmp_path):
    api = make_api(tmp_path)
    script = api._submit_feedback_script()

    assert "new FormData(form)" in script
    assert "payload[key] = String(value)" in script
    assert "textarea[name=\\\"message\\\"]" not in script
