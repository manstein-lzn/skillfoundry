#!/usr/bin/env python3
"""Manual ForgeUnit command bridge wrapper for real Codex exec pilots.

This script is intentionally thin. ForgeUnit invokes it as the explicit
``command=`` for the codex_exec adapter. It then invokes a Codex-compatible
command, validates the expected package/evidence boundary, and writes the
ForgeUnit worker_result when the command did not write one itself.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Any, Mapping


DEFAULT_CODEX_COMMAND = "codex exec"
PACKAGE_REF = "package/SKILL.md"
TRANSCRIPT_REF = "evidence/transcript.md"
MANIFEST_REF = "evidence/manifest.json"
CHANGED_FILES = [PACKAGE_REF, TRANSCRIPT_REF, MANIFEST_REF]


class WorkerBoundaryError(RuntimeError):
    """Raised when the command bridge cannot produce a valid ForgeUnit boundary."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Codex exec command inside a ForgeUnit boundary.")
    parser.add_argument(
        "--codex-command",
        default=None,
        help="Explicit Codex-compatible shell command. Defaults to FORGEUNIT_CODEX_COMMAND or 'codex exec'.",
    )
    parser.add_argument("--timeout", type=int, default=900, help="Codex command timeout in seconds.")
    args = parser.parse_args(argv)

    try:
        env = _required_env()
        command = args.codex_command or os.environ.get("FORGEUNIT_CODEX_COMMAND") or DEFAULT_CODEX_COMMAND
        _run_boundary(env=env, command=command, timeout_seconds=args.timeout)
    except WorkerBoundaryError as exc:
        print(f"forgeunit codex exec worker failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _required_env() -> dict[str, str]:
    required = {
        "FORGEUNIT_TASK_DIR": os.environ.get("FORGEUNIT_TASK_DIR"),
        "FORGEUNIT_RUN_DIR": os.environ.get("FORGEUNIT_RUN_DIR"),
        "FORGEUNIT_UNIT": os.environ.get("FORGEUNIT_UNIT"),
        "FORGEUNIT_WORKER_RESULT": os.environ.get("FORGEUNIT_WORKER_RESULT"),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise WorkerBoundaryError("missing required ForgeUnit env var(s): " + ", ".join(sorted(missing)))
    return {key: str(value) for key, value in required.items() if value is not None}


def _run_boundary(*, env: Mapping[str, str], command: str, timeout_seconds: int) -> None:
    task_dir = Path(env["FORGEUNIT_TASK_DIR"]).resolve()
    run_dir = Path(env["FORGEUNIT_RUN_DIR"]).resolve()
    worker_result_path = Path(env["FORGEUNIT_WORKER_RESULT"]).resolve()
    unit_id = env["FORGEUNIT_UNIT"]
    if not task_dir.exists() or not task_dir.is_dir():
        raise WorkerBoundaryError(f"FORGEUNIT_TASK_DIR does not exist or is not a directory: {task_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    worker_result_path.parent.mkdir(parents=True, exist_ok=True)
    (task_dir / "package").mkdir(parents=True, exist_ok=True)
    (task_dir / "evidence").mkdir(parents=True, exist_ok=True)

    prompt_text = _read_prompt_from_boundary()
    augmented_prompt = _augment_prompt(prompt_text=prompt_text, unit_id=unit_id, worker_result_path=worker_result_path)
    _check_command_available(command)
    result = _invoke_codex_command(
        command=command,
        cwd=task_dir,
        prompt=augmented_prompt,
        timeout_seconds=timeout_seconds,
    )
    _write_wrapper_diagnostics(run_dir=run_dir, command=command, result=result)
    if result.returncode != 0:
        raise WorkerBoundaryError(
            f"codex exec command failed with exit code {result.returncode}; "
            f"see {run_dir / 'workers' / 'forgeunit_codex_exec_worker_result.json'}"
        )

    package_path = _require_file(task_dir, PACKAGE_REF, "codex exec completed but package/SKILL.md was not produced")
    transcript_path = _ensure_transcript(task_dir=task_dir, unit_id=unit_id)
    manifest_path = _ensure_manifest(task_dir=task_dir, unit_id=unit_id, command_returncode=result.returncode)
    _validate_changed_files(CHANGED_FILES)
    _ensure_worker_result(
        worker_result_path=worker_result_path,
        task_dir=task_dir,
        package_path=package_path,
        transcript_path=transcript_path,
        manifest_path=manifest_path,
    )
    print("forgeunit codex exec worker completed")


def _read_prompt_from_boundary() -> str:
    stdin_text = ""
    if not sys.stdin.isatty():
        stdin_text = sys.stdin.read()
    prompt_ref = os.environ.get("FORGEUNIT_CODEX_EXEC_PROMPT")
    if prompt_ref:
        prompt_path = Path(prompt_ref)
        if prompt_path.exists() and prompt_path.is_file():
            file_text = prompt_path.read_text(encoding="utf-8")
            if file_text.strip():
                return file_text
    return stdin_text


def _augment_prompt(*, prompt_text: str, unit_id: str, worker_result_path: Path) -> str:
    boundary_contract = f"""

ForgeUnit Codex Exec Boundary Contract
=====================================

You are running inside a ForgeUnit task directory. Follow these hard output rules:

1. Write the Codex Skill package to: {PACKAGE_REF}
2. Write boundary transcript evidence to: {TRANSCRIPT_REF}
3. Write worker evidence manifest to: {MANIFEST_REF}
4. Optionally write ForgeUnit worker_result JSON to: {worker_result_path.as_posix()}
5. Only change files under package/ and evidence/.
6. Do not inline raw prompts, private requirements, or raw model transcripts in graph state.
7. The worker_result is not acceptance. SkillFoundry Verifier and LocalSkillRegistry decide acceptance.

Required SKILL.md sections:
Overview, When To Use, When Not To Use, Inputs, Outputs, Workflow, Safety.

Required worker_result shape if you write it:
{{
  "status": "completed",
  "output_artifacts": [{{"path": "{PACKAGE_REF}", "kind": "codex_skill", "summary": "Generated Codex Skill package."}}],
  "boundary_evidence": [
    {{"path": "{TRANSCRIPT_REF}", "kind": "transcript", "summary": "Boundary transcript summary."}},
    {{"path": "{MANIFEST_REF}", "kind": "worker_evidence_manifest", "summary": "Worker evidence manifest."}}
  ],
  "changed_files": {json.dumps(CHANGED_FILES)},
  "usage": null,
  "usage_unavailable_reason": "external_worker_no_provider_telemetry"
}}

Unit id: {unit_id}
"""
    return prompt_text.rstrip() + "\n" + boundary_contract


def _check_command_available(command: str) -> None:
    if not command.strip():
        raise WorkerBoundaryError("codex command is empty")
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise WorkerBoundaryError(f"codex command is not shell-parseable: {exc}") from exc
    if not parts:
        raise WorkerBoundaryError("codex command is empty")
    if _looks_like_complex_shell(command):
        return
    executable = parts[0]
    if shutil.which(executable) is None and not Path(executable).exists():
        raise WorkerBoundaryError(f"codex command missing: {executable}")


def _looks_like_complex_shell(command: str) -> bool:
    return any(token in command for token in ("|", "&&", "||", ";", "$(", "`", "<", ">"))


def _invoke_codex_command(
    *,
    command: str,
    cwd: Path,
    prompt: str,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            text=True,
            input=prompt,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkerBoundaryError(f"codex exec command timed out after {timeout_seconds}s") from exc


def _write_wrapper_diagnostics(
    *,
    run_dir: Path,
    command: str,
    result: subprocess.CompletedProcess[str],
) -> None:
    workers_dir = run_dir / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "skillfoundry.forgeunit_codex_exec_worker_result.v1",
        "command_summary": _command_summary(command),
        "returncode": result.returncode,
        "stdout_bytes": len((result.stdout or "").encode("utf-8")),
        "stderr_bytes": len((result.stderr or "").encode("utf-8")),
        "required_outputs": CHANGED_FILES,
        "raw_prompt_included": False,
        "raw_stdout_included": False,
        "raw_stderr_included": False,
    }
    (workers_dir / "forgeunit_codex_exec_worker_result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _command_summary(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return "codex-compatible command"
    if not parts:
        return "codex-compatible command"
    executable = Path(parts[0]).name
    return executable or "codex-compatible command"


def _require_file(task_dir: Path, ref: str, message: str) -> Path:
    path = _resolve_task_ref(task_dir, ref)
    if not path.exists() or not path.is_file():
        raise WorkerBoundaryError(f"{message}. Expected {ref} under FORGEUNIT_TASK_DIR.")
    return path


def _ensure_transcript(*, task_dir: Path, unit_id: str) -> Path:
    path = _resolve_task_ref(task_dir, TRANSCRIPT_REF)
    if path.exists() and path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "# ForgeUnit Codex Exec Boundary Transcript",
                "",
                f"unit_id: {unit_id}",
                "status: completed",
                "raw_prompt_included: false",
                "raw_command_output_included: false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _ensure_manifest(*, task_dir: Path, unit_id: str, command_returncode: int) -> Path:
    path = _resolve_task_ref(task_dir, MANIFEST_REF)
    if path.exists() and path.is_file():
        payload = _read_json_object(path, "worker evidence manifest")
        _validate_manifest_payload(payload)
        return path
    payload = _default_manifest_payload(unit_id=unit_id, command_returncode=command_returncode)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _default_manifest_payload(*, unit_id: str, command_returncode: int) -> dict[str, Any]:
    return {
        "schema": "forgeunit.worker_evidence_manifest",
        "version": "0.6",
        "unit_id": unit_id,
        "status": "completed",
        "output_artifacts": [
            {"path": PACKAGE_REF, "kind": "codex_skill", "summary": "Generated Codex Skill package."}
        ],
        "evidence_artifacts": [
            {"path": TRANSCRIPT_REF, "kind": "transcript", "summary": "Boundary transcript summary."}
        ],
        "changed_files": CHANGED_FILES,
        "commands": [
            {
                "command": "codex exec command bridge",
                "exit_code": command_returncode,
                "summary": "Codex-compatible command completed.",
            }
        ],
        "usage": None,
        "usage_unavailable_reason": "external_worker_no_provider_telemetry",
    }


def _validate_manifest_payload(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != "forgeunit.worker_evidence_manifest":
        raise WorkerBoundaryError("evidence/manifest.json has invalid schema")
    if payload.get("status") != "completed":
        raise WorkerBoundaryError("evidence/manifest.json status must be completed")
    _validate_changed_files(_string_list(payload.get("changed_files")))


def _ensure_worker_result(
    *,
    worker_result_path: Path,
    task_dir: Path,
    package_path: Path,
    transcript_path: Path,
    manifest_path: Path,
) -> None:
    _assert_under(task_dir, package_path)
    _assert_under(task_dir, transcript_path)
    _assert_under(task_dir, manifest_path)
    if worker_result_path.exists():
        payload = _read_json_object(worker_result_path, "worker_result")
        _validate_worker_result_payload(payload)
        return
    payload = {
        "status": "completed",
        "output_artifacts": [
            {"path": PACKAGE_REF, "kind": "codex_skill", "summary": "Generated Codex Skill package."}
        ],
        "boundary_evidence": [
            {"path": TRANSCRIPT_REF, "kind": "transcript", "summary": "Boundary transcript summary."},
            {"path": MANIFEST_REF, "kind": "worker_evidence_manifest", "summary": "Worker evidence manifest."},
        ],
        "changed_files": CHANGED_FILES,
        "usage": None,
        "usage_unavailable_reason": "external_worker_no_provider_telemetry",
    }
    worker_result_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _validate_worker_result_payload(payload: Mapping[str, Any]) -> None:
    if payload.get("status") != "completed":
        raise WorkerBoundaryError("worker_result status must be completed")
    output_paths = _artifact_paths(payload.get("output_artifacts"))
    evidence_paths = _artifact_paths(payload.get("boundary_evidence"))
    if PACKAGE_REF not in output_paths:
        raise WorkerBoundaryError(f"worker_result is missing output artifact: {PACKAGE_REF}")
    for required in (TRANSCRIPT_REF, MANIFEST_REF):
        if required not in evidence_paths:
            raise WorkerBoundaryError(f"worker_result is missing boundary evidence: {required}")
    _validate_changed_files(_string_list(payload.get("changed_files")))


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise WorkerBoundaryError(f"{label} is missing or invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise WorkerBoundaryError(f"{label} must be a JSON object")
    return payload


def _artifact_paths(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, Mapping) and isinstance(item.get("path"), str):
            result.append(str(item["path"]))
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _validate_changed_files(changed_files: list[str]) -> None:
    if not changed_files:
        raise WorkerBoundaryError("changed_files must list package/evidence outputs")
    for ref in changed_files:
        if not isinstance(ref, str) or ref.startswith("/") or ".." in Path(ref).parts:
            raise WorkerBoundaryError(f"unsafe changed file ref: {ref!r}")
        if not (ref == "package" or ref.startswith("package/") or ref == "evidence" or ref.startswith("evidence/")):
            raise WorkerBoundaryError(f"changed file outside package/evidence write scope: {ref}")


def _resolve_task_ref(task_dir: Path, ref: str) -> Path:
    if ref.startswith("/") or ".." in Path(ref).parts:
        raise WorkerBoundaryError(f"unsafe task ref: {ref!r}")
    path = (task_dir / ref).resolve()
    _assert_under(task_dir, path)
    return path


def _assert_under(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise WorkerBoundaryError(f"path escapes ForgeUnit task dir: {path}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
