from __future__ import annotations

from io import BytesIO
import json
import zipfile

import skillfoundry
from skillfoundry import (
    APPROVAL_APPROVED,
    CONTEXTFORGE_VERIFICATION_RESULT_REF,
    OfflineWorkerMode,
    SkillFoundryAPI,
    initialize_frontdesk_workspace,
    initialize_job_workspace,
    run_offline_goal_harness,
    write_frontdesk_artifact,
    write_frontdesk_v2_contract_artifacts,
)


REQ_TEXT = """# API pytest skill

Build a local SkillFoundry package that exposes the offline factory through a
minimal internal API and lets a reviewer download only approved packages.
"""


def make_api(tmp_path) -> SkillFoundryAPI:
    return SkillFoundryAPI(tmp_path / "runs")


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


def test_post_jobs_creates_registered_job_and_writes_final_report(tmp_path):
    api = make_api(tmp_path)

    response = post_job(api)
    payload = response_json(response)

    assert response.status == 201
    assert payload["job_id"] == "api-ok"
    assert payload["final_status"] == "registered"
    assert payload["report"]["final_status"] == "registered"
    assert payload["package_downloadable"] is True
    assert (tmp_path / "runs" / "api-ok" / "final_report.json").is_file()
    assert (tmp_path / "runs" / ".api_requirements" / "api-ok.md").is_file()


def test_get_jobs_lists_created_jobs(tmp_path):
    api = make_api(tmp_path)
    post_job(api, job_id="api-list")

    response = api.handle("GET", "/jobs")
    payload = response_json(response)

    assert response.status == 200
    assert payload["count"] == 1
    assert payload["jobs"][0]["job_id"] == "api-list"
    assert payload["jobs"][0]["final_status"] == "registered"


def test_get_job_report_returns_final_report(tmp_path):
    api = make_api(tmp_path)
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
    assert payload["status"]["verification"]["status"] == "passed"
    assert payload["raw_context_included"] is False
    assert payload["cache"]["raw_prompt_included"] is False
    assert "Offline Goal Harness Skill" not in body_text


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
    api = make_api(tmp_path)
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
    api = make_api(tmp_path)
    post_job(api, job_id="api-download")

    response = api.handle("GET", "/jobs/api-download/package.zip")

    assert response.status == 200
    assert response.content_type == "application/zip"
    with zipfile.ZipFile(BytesIO(response.body)) as archive:
        names = archive.namelist()
        assert "package/SKILL.md" in names
        assert all(name.startswith("package/") for name in names)


def test_failed_job_package_download_is_denied(tmp_path):
    api = make_api(tmp_path)
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
    api = make_api(tmp_path)
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
    api = make_api(tmp_path)
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


def test_html_ui_renders_links_and_does_not_mark_failed_jobs_as_downloadable(tmp_path):
    api = make_api(tmp_path)
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
