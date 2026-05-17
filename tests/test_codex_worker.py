from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import skillfoundry
from skillfoundry import (
    APPROVAL_APPROVED,
    CODEX_PILOT_ENV_VAR,
    LOCKED_INPUT_PATHS,
    BuildContract,
    CodexCommandResult,
    CodexWorker,
    LocalSkillRegistry,
    Verifier,
    WorkerAdapter,
    initialize_job_workspace,
)


HASH = "c" * 64


class RecordingCodexRunner:
    def __init__(self, action: Callable[[dict[str, object]], CodexCommandResult] | None = None) -> None:
        self.action = action or (lambda _call: CodexCommandResult(returncode=0, stdout="ok\n"))
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        command,
        *,
        input_text: str,
        cwd: Path,
        timeout_seconds: int,
    ) -> CodexCommandResult:
        call = {
            "command": list(command),
            "input_text": input_text,
            "cwd": Path(cwd),
            "timeout_seconds": timeout_seconds,
        }
        self.calls.append(call)
        return self.action(call)


def make_workspace(tmp_path, *, job_id="codex-001", attempt_limit=2, timeout_seconds=5):
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


def option_value(command: list[str], option: str) -> str:
    return command[command.index(option) + 1]


def option_values(command: list[str], option: str) -> list[str]:
    return [command[index + 1] for index, value in enumerate(command) if value == option]


def write_valid_package(root: Path, *, name: str = "codex-pilot-valid") -> None:
    (root / "package" / "SKILL.md").write_text(valid_skill_markdown(name), encoding="utf-8")


def valid_skill_markdown(name: str) -> str:
    return "\n".join(
        [
            "---",
            f"name: {name}",
            "description: Verifier-valid CodexWorker fake runner package.",
            "---",
            "",
            f"# {name}",
            "",
            "## Overview",
            "",
            "This package is a deterministic CodexWorker pilot fixture for independent verification.",
            "",
            "## When To Use",
            "",
            "- Use when SkillFoundry needs to test CodexWorker output without live Codex.",
            "",
            "## When Not To Use",
            "",
            "- Do not use as evidence that live Codex internals were controlled or replayed.",
            "",
            "## Inputs",
            "",
            "- A locked SkillFoundry worker input manifest and build contract.",
            "",
            "## Outputs",
            "",
            "- A package candidate that must pass the independent Verifier gate.",
            "",
            "## Workflow",
            "",
            "1. Read the locked workspace inputs.",
            "2. Write package files under `package/`.",
            "3. Let Verifier and Registry decide acceptance.",
            "",
            "## Safety",
            "",
            "- Worker self-report is not acceptance evidence.",
            "- Keep all generated files inside the allowed package path.",
            "",
        ]
    )


def test_codex_worker_api_is_exported():
    assert skillfoundry.CodexWorker is CodexWorker
    assert skillfoundry.CodexCommandResult is CodexCommandResult
    assert skillfoundry.CODEX_PILOT_ENV_VAR == "SKILLFOUNDRY_RUN_CODEX_PILOT"


def test_codex_command_assembly_uses_exec_and_workspace_root(tmp_path):
    runner = RecordingCodexRunner()
    worker = CodexWorker(
        command_runner=runner,
        model="gpt-5",
        profile="wp8-pilot",
        config_overrides={
            "features.web_search": "false",
            "model_reasoning_effort": '"low"',
        },
    )
    workspace = make_workspace(tmp_path, job_id="codex-command")

    WorkerAdapter(worker).invoke(workspace, "001")

    command = runner.calls[0]["command"]
    assert command[0] == "codex"
    assert "exec" in command
    assert option_value(command, "--cd") == str(workspace.root.resolve())
    assert option_value(command, "--sandbox") == "workspace-write"
    assert option_value(command, "--ask-for-approval") == "never"
    assert option_value(command, "--model") == "gpt-5"
    assert option_value(command, "--profile") == "wp8-pilot"
    assert "--skip-git-repo-check" in command
    assert "features.web_search=false" in option_values(command, "--config")
    assert 'model_reasoning_effort="low"' in option_values(command, "--config")
    assert command[-1] == "-"


def test_codex_prompt_includes_write_constraints_and_required_package_output(tmp_path):
    runner = RecordingCodexRunner()
    workspace = make_workspace(tmp_path, job_id="codex-prompt")

    WorkerAdapter(CodexWorker(command_runner=runner)).invoke(workspace, "001")

    prompt = runner.calls[0]["input_text"]
    assert "Write only under these paths:" in prompt
    assert "- package/" in prompt
    assert "- attempts/001/" in prompt
    assert "Do not create, modify, delete, move, or chmod any file outside package/" in prompt
    assert "Required package output:" in prompt
    assert "- package/SKILL.md" in prompt
    assert "CodexWorker self-report is not acceptance evidence" in prompt
    assert "Verifier and LocalSkillRegistry remain the final SkillFoundry trust gates" in prompt
    assert "Do not claim ContextForge controls or replays Codex internal" in prompt


def test_successful_fake_codex_runner_passes_verifier_through_worker_adapter(tmp_path):
    def action(call):
        write_valid_package(call["cwd"])
        return CodexCommandResult(returncode=0, stdout="wrote package\n", stderr="diagnostic note\n")

    runner = RecordingCodexRunner(action)
    workspace = make_workspace(tmp_path, job_id="codex-success")

    result = WorkerAdapter(CodexWorker(command_runner=runner)).invoke(workspace, "001")
    paths = assert_attempt_artifacts(workspace, "001")

    assert result.report.status == "completed"
    assert result.report.exit_status == "success"
    assert result.report.artifacts == ["package/SKILL.md"]
    assert result.ready_for_verifier is True
    assert result.accepted is False
    assert result.invocation.usage_available is False
    assert "CLI boundary does not expose reliable provider usage" in result.invocation.usage_unavailable_reason

    transcript = workspace.resolve_path(paths["transcript"], must_exist=True).read_text(encoding="utf-8")
    assert "stdout: wrote package" in transcript
    assert "stderr: diagnostic note" in transcript

    verification = Verifier().verify(workspace, attempt_id="001")
    assert verification.passed is True


def test_successful_fake_codex_runner_can_register_only_after_verifier_passes(tmp_path):
    def action(call):
        write_valid_package(call["cwd"], name="codex-registry")
        return CodexCommandResult(returncode=0, stdout="wrote registry package\n")

    workspace = make_workspace(tmp_path, job_id="codex-registry")
    result = WorkerAdapter(CodexWorker(command_runner=RecordingCodexRunner(action))).invoke(workspace, "001")

    assert result.ready_for_verifier is True
    verification = Verifier().verify(workspace, attempt_id="001")
    assert verification.passed is True

    entry = LocalSkillRegistry(tmp_path / "registry.json").add_verified(workspace, review_status="wp8_test")
    assert entry.approval_status == APPROVAL_APPROVED
    assert entry.worker_invocation_id == result.invocation.invocation_id
    assert entry.package_hash == verification.package_hash


def test_nonzero_codex_exit_writes_failed_report_and_is_not_verifier_ready(tmp_path):
    def action(call):
        write_valid_package(call["cwd"])
        return CodexCommandResult(returncode=17, stdout="partial output\n", stderr="codex failed\n")

    workspace = make_workspace(tmp_path, job_id="codex-nonzero")
    result = WorkerAdapter(CodexWorker(command_runner=RecordingCodexRunner(action))).invoke(workspace, "001")

    assert result.report.status == "failed"
    assert result.report.exit_status == "failure"
    assert result.report.failures == ["codex exec exited with return code 17"]
    assert result.failure_class == "failure"
    assert result.ready_for_verifier is False
    assert result.accepted is False

    verification = Verifier().verify(workspace, attempt_id="001")
    assert verification.passed is False
    assert any("execution_report_success" in failure for failure in verification.failures)


def test_timeout_writes_failed_report_and_records_timeout_classification(tmp_path):
    runner = RecordingCodexRunner(
        lambda _call: CodexCommandResult(
            returncode=-1,
            stdout="partial output\n",
            stderr="still running\n",
            timed_out=True,
        )
    )
    workspace = make_workspace(tmp_path, job_id="codex-timeout", timeout_seconds=1)

    result = WorkerAdapter(CodexWorker(command_runner=runner)).invoke(workspace, "001")

    assert result.failure_class == "timeout"
    assert result.report.status == "failed"
    assert result.report.exit_status == "timeout"
    assert result.invocation.exit_status == "timeout"
    assert result.invocation.duration_ms == 1001
    assert "timeout_seconds=1" in result.report.failures
    assert result.ready_for_verifier is False

    transcript = workspace.resolve_path("attempts/001/worker_transcript.log", must_exist=True).read_text(
        encoding="utf-8"
    )
    assert "codex_timed_out=true" in transcript
    assert "stdout: partial output" in transcript
    assert "stderr: still running" in transcript


def test_missing_package_output_fails_closed(tmp_path):
    workspace = make_workspace(tmp_path, job_id="codex-missing-output")

    result = WorkerAdapter(CodexWorker(command_runner=RecordingCodexRunner())).invoke(workspace, "001")

    assert result.report.status == "failed"
    assert result.report.exit_status == "failure"
    assert result.report.failures == ["missing expected package file: package/SKILL.md"]
    assert result.failure_class == "failure"
    assert result.ready_for_verifier is False
    assert result.accepted is False
    assert not workspace.resolve_path("package/SKILL.md").exists()


def test_disallowed_workspace_write_is_rejected(tmp_path):
    def action(call):
        write_valid_package(call["cwd"])
        (call["cwd"] / "build_contract.yaml").write_text("tampered\n", encoding="utf-8")
        return CodexCommandResult(returncode=0, stdout="tampered locked input\n")

    workspace = make_workspace(tmp_path, job_id="codex-path-reject")

    result = WorkerAdapter(CodexWorker(command_runner=RecordingCodexRunner(action))).invoke(workspace, "001")

    assert result.report.status == "failed"
    assert result.report.exit_status == "rejected"
    assert result.failure_class == "rejected"
    assert result.ready_for_verifier is False
    assert "build_contract.yaml" in result.report.failures[0]


def test_default_codex_worker_requires_opt_in_before_live_cli(monkeypatch, tmp_path):
    monkeypatch.delenv(CODEX_PILOT_ENV_VAR, raising=False)
    workspace = make_workspace(tmp_path, job_id="codex-no-live")

    result = WorkerAdapter(CodexWorker()).invoke(workspace, "001")

    assert result.report.status == "failed"
    assert result.report.exit_status == "not_enabled"
    assert result.report.failures == [f"{CODEX_PILOT_ENV_VAR}=1 is required for live Codex CLI invocation"]
    assert result.ready_for_verifier is False
    assert_attempt_artifacts(workspace, "001")


def test_worker_adapter_with_codex_worker_writes_standard_attempt_artifacts(tmp_path):
    def action(call):
        write_valid_package(call["cwd"], name="codex-artifacts")
        return CodexCommandResult(returncode=0, stdout="done\n")

    workspace = make_workspace(tmp_path, job_id="codex-artifacts")

    result = WorkerAdapter(CodexWorker(command_runner=RecordingCodexRunner(action))).invoke(workspace, "001")
    paths = assert_attempt_artifacts(workspace, "001")

    assert result.ready_for_verifier is True
    assert read_json(workspace, paths["input_manifest"])["worker_type"] == "codex:exec"
    assert read_json(workspace, paths["execution_report"])["exit_status"] == "success"
    assert "package/SKILL.md" in workspace.resolve_path(paths["diff"], must_exist=True).read_text(encoding="utf-8")
    assert "codex_command=" in workspace.resolve_path(paths["transcript"], must_exist=True).read_text(
        encoding="utf-8"
    )
