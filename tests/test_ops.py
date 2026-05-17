from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json

import skillfoundry
from skillfoundry import (
    LocalSkillRegistry,
    OfflineWorkerMode,
    QALab,
    SkillFoundryOps,
    build_offline,
    sha256_file,
)


REQ_TEXT = """# WP12 ops fixture

Build a local SkillFoundry package for WP12 operations hardening tests.
"""


def write_requirement(tmp_path, name: str = "requirement", text: str = REQ_TEXT):
    path = tmp_path / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_ops_api_is_exported():
    assert skillfoundry.SkillFoundryOps is SkillFoundryOps


def test_multi_job_concurrent_builds_are_isolated_and_registered(tmp_path):
    ops = SkillFoundryOps(tmp_path / "runs")
    jobs = [
        {"job_id": "ops-job-a", "requirement": REQ_TEXT, "version": "1.0.0"},
        {"job_id": "ops-job-b", "requirement": REQ_TEXT, "version": "1.0.0"},
        {"job_id": "ops-job-c", "requirement": REQ_TEXT, "version": "1.0.0"},
    ]

    report = ops.build_jobs_concurrently(jobs, max_workers=3)

    assert report["requested"] == 3
    assert report["completed"] == 3
    assert report["failed"] == 0
    registry_entries = LocalSkillRegistry(tmp_path / "runs" / "registry.json").list(
        status="all",
        include_quarantined=True,
    )
    assert {entry.build_job_id for entry in registry_entries} == {"ops-job-a", "ops-job-b", "ops-job-c"}
    assert len({entry.package_path for entry in registry_entries}) == 3

    for job in report["jobs"]:
        job_id = str(job["job_id"])
        workspace = tmp_path / "runs" / job_id
        final_report = read_json(workspace / "final_report.json")
        skill_text = (workspace / "package" / "SKILL.md").read_text(encoding="utf-8")
        assert final_report["job_id"] == job_id
        assert final_report["final_status"] == "registered"
        assert f"{job_id}-skill" not in skill_text
        assert (workspace / "artifact_manifest.json").is_file()
        other_job_ids = {"ops-job-a", "ops-job-b", "ops-job-c"} - {job_id}
        assert all(not (workspace / other).exists() for other in other_job_ids)


def test_concurrent_registry_additions_do_not_corrupt_json(tmp_path):
    registry_path = tmp_path / "registry.json"
    workspaces = []
    for index in range(8):
        result = build_offline(
            requirement_path=write_requirement(tmp_path, f"req-{index}"),
            output=tmp_path / "runs" / f"registry-concurrent-{index}",
            registry_path=registry_path,
            version="0.0.0",
        )
        workspaces.append(result.workspace)
    registry_path.unlink()

    def add(index_and_workspace):
        index, workspace = index_and_workspace
        return LocalSkillRegistry(registry_path).add_verified(
            workspace,
            version=f"1.0.{index}",
            review_status="wp12_concurrency_test",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        entries = list(executor.map(add, enumerate(workspaces)))

    payload = read_json(registry_path)
    assert isinstance(payload["entries"], list)
    assert len(payload["entries"]) == 8
    loaded = LocalSkillRegistry(registry_path).list(status="all", include_quarantined=True)
    assert {entry.version for entry in loaded} == {entry.version for entry in entries}
    assert {entry.build_job_id for entry in loaded} == {f"registry-concurrent-{index}" for index in range(8)}


def test_cleanup_dry_run_reports_planned_removals_without_deleting(tmp_path):
    result = build_offline(
        requirement_path=write_requirement(tmp_path),
        output=tmp_path / "runs" / "cleanup-dry-run",
        registry_path=tmp_path / "runs" / "registry.json",
    )
    transient = result.workspace.root / "attempts" / "001" / "scratch.tmp"
    transient.write_text("transient\n", encoding="utf-8")
    cache_dir = result.workspace.root / "attempts" / "001" / "__pycache__"
    cache_dir.mkdir()
    cached = cache_dir / "helper.pyc"
    cached.write_bytes(b"pyc")

    report = SkillFoundryOps(tmp_path / "runs").cleanup_artifacts(dry_run=True)

    planned = {item["path"] for item in report["planned_removals"]}
    assert "cleanup-dry-run/attempts/001/scratch.tmp" in planned
    assert "cleanup-dry-run/attempts/001/__pycache__" in planned
    assert report["dry_run"] is True
    assert report["removed_count"] == 0
    assert transient.exists()
    assert cached.exists()


def test_cleanup_apply_preserves_provenance_artifacts_and_approved_package(tmp_path):
    result = build_offline(
        requirement_path=write_requirement(tmp_path),
        output=tmp_path / "runs" / "cleanup-apply",
        registry_path=tmp_path / "runs" / "registry.json",
    )
    workspace = result.workspace.root
    transient = workspace / "attempts" / "001" / "scratch.tmp"
    transient.write_text("transient\n", encoding="utf-8")
    critical_paths = [
        workspace / "build_contract.yaml",
        workspace / "skill_spec.yaml",
        workspace / "verification_spec.yaml",
        workspace / "worker_input.md",
        workspace / "artifact_manifest.json",
        workspace / "final_report.json",
        workspace / "verifier" / "verification_result.json",
        workspace / "attempts" / "001" / "input_manifest.json",
        workspace / "attempts" / "001" / "execution_report.json",
        workspace / "attempts" / "001" / "worker_transcript.log",
        workspace / "attempts" / "001" / "output_diff.patch",
        workspace / "attempts" / "001" / "verification_result.json",
        workspace / "package" / "SKILL.md",
    ]
    hashes_before = {path: sha256_file(path) for path in critical_paths}

    report = SkillFoundryOps(tmp_path / "runs").cleanup_artifacts(dry_run=False)

    removed = {item["path"] for item in report["removed"]}
    assert "cleanup-apply/attempts/001/scratch.tmp" in removed
    assert not transient.exists()
    for path, digest in hashes_before.items():
        assert path.exists()
        assert sha256_file(path) == digest
    assert LocalSkillRegistry(tmp_path / "runs" / "registry.json").verify(
        result.registry_entry.skill_id,
        result.registry_entry.version,
    ).valid


def test_observability_report_includes_jobs_registry_qa_usage_and_failure_summaries(tmp_path):
    registry_path = tmp_path / "runs" / "registry.json"
    good = build_offline(
        requirement_path=write_requirement(tmp_path, "good"),
        output=tmp_path / "runs" / "obs-good",
        registry_path=registry_path,
    )
    qa_result = QALab().evaluate(good.workspace)
    assert qa_result.passed is True

    failed = build_offline(
        requirement_path=write_requirement(tmp_path, "failed"),
        output=tmp_path / "runs" / "obs-failed",
        registry_path=registry_path,
        worker_mode=OfflineWorkerMode.ALWAYS_INVALID,
        attempt_limit=1,
    )
    assert failed.final_report["final_status"] == "fail_closed"

    report = SkillFoundryOps(tmp_path / "runs").observability_report()

    assert report["jobs"]["count"] == 2
    assert report["jobs"]["statuses"]["registered"] == 1
    assert report["jobs"]["statuses"]["fail_closed"] == 1
    assert report["registry"]["approved"] == 1
    assert report["registry"]["total"] == 1
    assert report["qa"]["passed"] == 1
    assert report["qa"]["missing"] == 1
    assert report["verifier"]["passed"] == 1
    assert report["verifier"]["failed"] == 1
    assert report["attempts"]["total"] == 2
    assert report["failures"]["failed_job_count"] == 1
    assert "attempt_limit_exceeded" in report["failures"]["classes"]
    assert report["durations"]["available"] is True
    assert report["usage"]["attempts_with_usage_unavailable"] == 2
    assert "Offline deterministic worker does not call model providers." in report["usage"]["unavailable_reasons"]


def test_health_readiness_check_returns_machine_readable_pass_fail_checks(tmp_path):
    ops = SkillFoundryOps(tmp_path / "runs")

    report = ops.health_check()

    assert report["ready"] is True
    check_names = {check["name"] for check in report["checks"]}
    assert {
        "runs_root_exists",
        "runs_root_writable",
        "registry_path_controlled",
        "registry_parseable",
        "workspace_path_sanity",
        "import_readiness",
        "cli_readiness",
        "test_command_documented",
    }.issubset(check_names)
    for check in report["checks"]:
        assert isinstance(check["passed"], bool)
        assert check["severity"] in {"error", "warning", "info"}
        assert isinstance(check["message"], str)
