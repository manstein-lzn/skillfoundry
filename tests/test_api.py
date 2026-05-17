from __future__ import annotations

from io import BytesIO
import json
import zipfile

import skillfoundry
from skillfoundry import APPROVAL_APPROVED, OfflineWorkerMode, SkillFoundryAPI


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
