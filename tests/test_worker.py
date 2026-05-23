import json

import pytest

import skillfoundry
from skillfoundry import (
    LOCKED_INPUT_PATHS,
    BuildContract,
    WorkerInvocation,
    initialize_job_workspace,
    sha256_file,
)
import skillfoundry.worker as worker_module
from skillfoundry.worker import FakeWorker, FakeWorkerMode, WorkerAdapter, WorkerAttemptLimitError


HASH = "a" * 64


def make_workspace(tmp_path, *, job_id="worker-001", attempt_limit=2, timeout_seconds=5):
    workspace_root = tmp_path / "runs" / job_id
    contract = BuildContract(
        job_id=job_id,
        skill_spec_ref="skill_spec.yaml",
        verification_spec_ref="verification_spec.yaml",
        workspace_root=str(workspace_root),
        allowed_write_paths=["package", "attempts"],
        blocked_paths=[".."],
        timeout_seconds=timeout_seconds,
        attempt_limit=attempt_limit,
        required_artifacts=list(LOCKED_INPUT_PATHS),
        locked_input_hashes={
            "skill_spec.yaml": HASH,
            "verification_spec.yaml": HASH,
            "worker_input.md": HASH,
        },
    )
    return initialize_job_workspace(tmp_path / "runs", job_id, build_contract=contract)


def read_json(workspace, relative_path):
    return json.loads(workspace.resolve_path(relative_path, must_exist=True).read_text(encoding="utf-8"))


def assert_attempt_artifacts(workspace, attempt_id):
    paths = {
        "input_manifest": f"attempts/{attempt_id}/input_manifest.json",
        "execution_report": f"attempts/{attempt_id}/execution_report.json",
        "diff": f"attempts/{attempt_id}/output_diff.patch",
        "transcript": f"attempts/{attempt_id}/worker_transcript.log",
    }
    for path in paths.values():
        assert workspace.resolve_path(path, must_exist=True).is_file()
    return paths


def test_legacy_worker_api_is_module_scoped():
    assert worker_module.WorkerAdapter is WorkerAdapter
    assert worker_module.FakeWorker is FakeWorker
    assert worker_module.FakeWorkerMode is FakeWorkerMode
    assert not hasattr(skillfoundry, "WorkerAdapter")
    assert not hasattr(skillfoundry, "FakeWorker")
    assert not hasattr(skillfoundry, "FakeWorkerMode")


def test_fake_worker_minimal_success_creates_package_and_attempt_artifacts(tmp_path):
    workspace = make_workspace(tmp_path)
    result = WorkerAdapter(FakeWorker(FakeWorkerMode.MINIMAL_SUCCESS)).invoke(workspace, "001")
    paths = assert_attempt_artifacts(workspace, "001")

    skill_md = workspace.resolve_path("package/SKILL.md", must_exist=True)
    assert "minimal-success" in skill_md.read_text(encoding="utf-8")

    report = read_json(workspace, paths["execution_report"])
    assert report["status"] == "completed"
    assert report["exit_status"] == "success"
    assert report["artifacts"] == ["package/SKILL.md"]

    assert isinstance(result.invocation, WorkerInvocation)
    assert result.invocation.exit_status == "success"
    assert result.invocation.transcript_ref == paths["transcript"]
    assert result.invocation.execution_report_ref == paths["execution_report"]
    assert result.invocation.diff_ref == paths["diff"]
    assert result.invocation.input_manifest_hash == sha256_file(workspace.resolve_path(paths["input_manifest"]))
    assert len(result.invocation.workspace_hash_before) == 64
    assert len(result.invocation.workspace_hash_after) == 64
    assert result.invocation.workspace_hash_before != result.invocation.workspace_hash_after
    assert result.invocation.duration_ms >= 0
    assert result.invocation.usage_available is False
    assert result.invocation.usage_unavailable_reason == "FakeWorker does not call model providers."
    assert result.ready_for_verifier is True
    assert result.accepted is False

    manifest = read_json(workspace, paths["input_manifest"])
    assert manifest["writable_paths"] == ["package", "attempts/001"]
    assert manifest["env_allowlist"] == []
    assert manifest["timeout_seconds"] == 5

    diff = workspace.resolve_path(paths["diff"], must_exist=True).read_text(encoding="utf-8")
    assert "package/SKILL.md" in diff
    assert "worker_transcript.log" in diff


def test_fake_worker_intentional_failure_records_failure_without_acceptance(tmp_path):
    workspace = make_workspace(tmp_path)
    result = WorkerAdapter(FakeWorker(FakeWorkerMode.INTENTIONAL_FAILURE)).invoke(workspace, "001")

    assert workspace.resolve_path("package/SKILL.md", must_exist=True).is_file()
    assert result.report.status == "failed"
    assert result.report.exit_status == "failure"
    assert result.report.failures == ["intentional failure fixture"]
    assert result.failure_class == "failure"
    assert result.ready_for_verifier is False
    assert result.accepted is False


def test_fake_worker_repair_success_can_repair_after_failed_attempt(tmp_path):
    workspace = make_workspace(tmp_path, attempt_limit=2)
    failed = WorkerAdapter(FakeWorker(FakeWorkerMode.INTENTIONAL_FAILURE)).invoke(workspace, "001")
    repaired = WorkerAdapter(FakeWorker(FakeWorkerMode.REPAIR_SUCCESS)).invoke(
        workspace,
        "002",
        previous_attempt_id="001",
    )

    assert failed.report.status == "failed"
    assert repaired.report.status == "completed"
    assert repaired.invocation.exit_status == "success"
    assert repaired.ready_for_verifier is True
    assert repaired.accepted is False

    skill_md = workspace.resolve_path("package/SKILL.md", must_exist=True).read_text(encoding="utf-8")
    assert "repair-success" in skill_md

    manifest = read_json(workspace, "attempts/002/input_manifest.json")
    assert manifest["previous_attempt_id"] == "001"
    transcript = workspace.resolve_path("attempts/002/worker_transcript.log", must_exist=True).read_text(
        encoding="utf-8"
    )
    assert "previous attempt 001" in transcript


def test_fake_worker_path_escape_is_rejected_without_outside_write(tmp_path):
    workspace = make_workspace(tmp_path)
    outside = workspace.root.parent / "outside-job.txt"

    result = WorkerAdapter(FakeWorker(FakeWorkerMode.PATH_ESCAPE)).invoke(workspace, "001")

    assert not outside.exists()
    assert result.failure_class == "path_escape"
    assert result.report.status == "failed"
    assert result.invocation.exit_status == "rejected"
    assert result.ready_for_verifier is False
    assert result.accepted is False
    assert "outside allowed" in result.report.failures[0] or "unsafe segment" in result.report.failures[0]


def test_worker_context_does_not_expose_raw_workspace_for_bypass(tmp_path):
    class WorkspaceBypassWorker:
        @property
        def worker_type(self):
            return "fake:workspace-bypass"

        def run(self, context):
            context.workspace.resolve_path("build_contract.yaml").write_text("tampered", encoding="utf-8")

    workspace = make_workspace(tmp_path)
    result = WorkerAdapter(WorkspaceBypassWorker()).invoke(workspace, "001")

    assert result.failure_class == "worker_exception"
    assert result.ready_for_verifier is False
    assert result.accepted is False
    workspace.check_locked_inputs()


def test_fake_worker_missing_report_is_fail_closed_not_pass_equivalent(tmp_path):
    workspace = make_workspace(tmp_path)
    result = WorkerAdapter(FakeWorker(FakeWorkerMode.MISSING_REPORT)).invoke(workspace, "001")

    assert workspace.resolve_path("package/SKILL.md", must_exist=True).is_file()
    assert result.failure_class == "missing_execution_report"
    assert result.report.status == "failed"
    assert result.report.exit_status == "failure"
    assert "missing execution_report.json" in result.report.failures
    assert result.ready_for_verifier is False
    assert result.accepted is False

    persisted_report = read_json(workspace, "attempts/001/execution_report.json")
    assert persisted_report["status"] == "failed"
    assert "did not produce execution_report.json" in persisted_report["summary"]


def test_worker_attempt_limit_is_enforced_before_attempt_directory(tmp_path):
    workspace = make_workspace(tmp_path, attempt_limit=1)

    with pytest.raises(WorkerAttemptLimitError):
        WorkerAdapter(FakeWorker(FakeWorkerMode.MINIMAL_SUCCESS)).invoke(workspace, "002")

    assert not (workspace.root / "attempts" / "002").exists()


def test_fake_worker_simulated_timeout_is_deterministic_failure(tmp_path):
    workspace = make_workspace(tmp_path, timeout_seconds=1)
    result = WorkerAdapter(FakeWorker(FakeWorkerMode.SIMULATED_TIMEOUT)).invoke(workspace, "001")

    assert result.failure_class == "timeout"
    assert result.report.status == "failed"
    assert result.report.exit_status == "timeout"
    assert result.invocation.exit_status == "timeout"
    assert result.invocation.duration_ms == 1001
    assert "timeout_seconds=1" in result.report.failures
    assert result.ready_for_verifier is False
    assert result.accepted is False
    assert_attempt_artifacts(workspace, "001")
