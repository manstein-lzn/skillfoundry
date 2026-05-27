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

import yaml


DEFAULT_CODEX_COMMAND = "codex exec"
PACKAGE_REF = "package/SKILL.md"
TRANSCRIPT_REF = "evidence/transcript.md"
MANIFEST_REF = "evidence/manifest.json"
CHANGED_FILES = [PACKAGE_REF, TRANSCRIPT_REF, MANIFEST_REF]
DEFAULT_WRITE_SCOPES = ["package", "evidence"]


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

    allowed_scopes = _unit_write_scope(task_dir=task_dir, unit_id=unit_id)
    extra_allowed_refs = _protocol_output_refs(task_dir=task_dir, worker_result_path=worker_result_path)
    prompt_text = _read_prompt_from_boundary()
    augmented_prompt = _augment_prompt(
        prompt_text=prompt_text,
        unit_id=unit_id,
        worker_result_path=worker_result_path,
        allowed_scopes=allowed_scopes,
    )
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
    _validate_skill_frontmatter(package_path)
    _validate_frozen_task_requirements(task_dir)
    transcript_path = _ensure_transcript(task_dir=task_dir, unit_id=unit_id)
    changed_files = _discover_changed_files(task_dir, allowed_scopes=allowed_scopes)
    manifest_path = _ensure_manifest(
        task_dir=task_dir,
        unit_id=unit_id,
        command_returncode=result.returncode,
        changed_files=changed_files,
        allowed_scopes=allowed_scopes,
        extra_allowed_refs=extra_allowed_refs,
    )
    _validate_changed_files(changed_files, allowed_scopes=allowed_scopes, extra_allowed_refs=extra_allowed_refs)
    _ensure_worker_result(
        worker_result_path=worker_result_path,
        task_dir=task_dir,
        package_path=package_path,
        transcript_path=transcript_path,
        manifest_path=manifest_path,
        changed_files=changed_files,
        allowed_scopes=allowed_scopes,
        extra_allowed_refs=extra_allowed_refs,
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


def _unit_write_scope(*, task_dir: Path, unit_id: str) -> list[str]:
    task_yaml = _resolve_task_ref(task_dir, "task.yaml")
    if not task_yaml.exists() or not task_yaml.is_file():
        return _normalize_write_scopes([])
    try:
        payload = yaml.safe_load(task_yaml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise WorkerBoundaryError(f"task.yaml is invalid YAML: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise WorkerBoundaryError("task.yaml must be a YAML mapping")
    units = payload.get("units")
    if not isinstance(units, Mapping):
        return _normalize_write_scopes([])
    unit = units.get(unit_id)
    if not isinstance(unit, Mapping):
        return _normalize_write_scopes([])
    worker = unit.get("worker")
    if not isinstance(worker, Mapping):
        return _normalize_write_scopes([])
    write_scope = worker.get("write_scope")
    if write_scope is None:
        return _normalize_write_scopes([])
    if not isinstance(write_scope, list):
        raise WorkerBoundaryError(f"task.yaml units.{unit_id}.worker.write_scope must be a list")
    return _normalize_write_scopes(_string_list(write_scope))


def _protocol_output_refs(*, task_dir: Path, worker_result_path: Path) -> list[str]:
    try:
        ref = worker_result_path.resolve().relative_to(task_dir.resolve()).as_posix()
    except ValueError:
        return []
    if not ref or ref.startswith("/") or ".." in Path(ref).parts:
        return []
    return [ref]


def _normalize_write_scopes(scopes: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in [*DEFAULT_WRITE_SCOPES, *scopes]:
        if not isinstance(raw, str):
            continue
        ref = raw.strip().strip("/")
        if not ref:
            continue
        if ref.startswith("/") or ".." in Path(ref).parts or ref == ".":
            raise WorkerBoundaryError(f"unsafe ForgeUnit write scope: {raw!r}")
        if ref not in seen:
            normalized.append(ref)
            seen.add(ref)
    return normalized


def _augment_prompt(
    *,
    prompt_text: str,
    unit_id: str,
    worker_result_path: Path,
    allowed_scopes: list[str],
) -> str:
    allowed_scope_text = ", ".join(f"`{scope}/`" for scope in allowed_scopes)
    boundary_contract = f"""

ForgeUnit Codex Exec Boundary Contract
=====================================

You are running inside a ForgeUnit task directory. Follow these hard output rules:

1. Write the Codex Skill package to: {PACKAGE_REF}
2. Write boundary transcript evidence to: {TRANSCRIPT_REF}
3. Write worker evidence manifest to: {MANIFEST_REF}
4. Optionally write ForgeUnit worker_result JSON to: {worker_result_path.as_posix()}
5. Only change files under the current ForgeUnit write scopes: {allowed_scope_text}.
6. Do not inline raw prompts, private requirements, or raw model transcripts in graph state.
7. The worker_result is not acceptance. SkillFoundry Verifier and LocalSkillRegistry decide acceptance.
8. In worker_result, output_artifacts, boundary_evidence, and changed_files must list files only, not directories.

	You must read the frozen task files in this directory before writing output:
	- skill_spec.yaml
	- acceptance_criteria.yaml
	- verification_spec.yaml
	- worker_input.md
	- adaptive/attempts/*/codex_worker_input.md when present
	- adaptive/next_step_contract_*.json when present

	Satisfy every must acceptance criterion in acceptance_criteria.yaml. Do not stop
	after writing only package/SKILL.md when the frozen spec asks for executable
	assets, tests, fixtures, docs, or verifier code.

	When adaptive steering files are present, treat the latest NextStepContract as
	the current bounded work unit. Stay inside its allowed_scope plus the required
	ForgeUnit evidence refs. If the contract asks for package/skillfoundry.bundle.json,
	write a valid skillfoundry.bundle.v1 manifest with package-relative refs. If you
	already produced a complete package in an earlier step, writing that manifest is
	allowed even before the harness explicitly asks for it.

If any frozen task file mentions Rust, Cargo, verifier, tests/fixtures, or
cargo test, you must also create a local Rust project inside package/:
- either package/Cargo.toml with package/src, or a single nested tool project
  such as package/verifier/Cargo.toml with package/verifier/src
- Rust tests and fixtures under the Rust project, for example
  package/tests/fixtures or package/fixtures when the tests reference it
- a documented cargo test / smoke verification command

Run cargo test yourself when you create a Rust project. If you cannot create the
required Rust project and tests, exit non-zero instead of claiming completion.

Required SKILL.md Markdown structure:
- YAML frontmatter first.
- Frontmatter must be valid YAML. Quote string values containing colons,
  commas, brackets, hash signs, or other punctuation.
- Recommended frontmatter shape:
  ---
  name: codexarium
  description: "Clean-room local wiki / atomic note maintenance skill."
  ---
- A single H1 title for the skill, for example: # Codexarium
- Exact H2 headings with non-empty bodies:
  ## Overview
  ## When To Use
  ## When Not To Use
  ## Inputs
  ## Outputs
  ## Workflow
  ## Safety
- Do not use H1 headings for the required sections; SkillFoundry verifies
  these sections as H2 headings below the skill title.

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

If you write additional files inside another allowed scope such as an adaptive
attempt evidence directory, include those file refs in changed_files.

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


def _validate_frozen_task_requirements(task_dir: Path) -> None:
    frozen_text = _frozen_task_text(task_dir)
    if not _requires_rust_project(frozen_text):
        return

    cargo_manifests = _package_files(task_dir, "Cargo.toml")
    if not cargo_manifests:
        raise WorkerBoundaryError(
            "frozen acceptance requires Rust/Cargo verifier work, but no Cargo.toml was produced under package/"
        )
    rust_sources = [path for path in _package_files(task_dir, "*.rs") if "/src/" in path]
    if not rust_sources:
        raise WorkerBoundaryError(
            "frozen acceptance requires Rust/Cargo verifier work, but no package/**/src/*.rs files were produced"
        )
    fixture_files = [path for path in _package_files(task_dir, "*") if _is_fixture_ref(path)]
    if not fixture_files:
        raise WorkerBoundaryError(
            "frozen acceptance requires verifier fixtures, but no package/**/fixtures files were produced"
        )


def _validate_skill_frontmatter(package_path: Path) -> None:
    skill_text = package_path.read_text(encoding="utf-8", errors="replace")
    if not skill_text.startswith("---\n"):
        raise WorkerBoundaryError("package/SKILL.md must start with YAML frontmatter")
    end = skill_text.find("\n---", 4)
    if end == -1:
        raise WorkerBoundaryError("package/SKILL.md frontmatter closing delimiter is missing")
    try:
        payload = yaml.safe_load(skill_text[4:end])
    except yaml.YAMLError as exc:
        raise WorkerBoundaryError(
            "package/SKILL.md frontmatter is invalid YAML; quote frontmatter values containing colons "
            f"or punctuation: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise WorkerBoundaryError("package/SKILL.md frontmatter must be a YAML mapping")
    for key in ("name", "description"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise WorkerBoundaryError(f"package/SKILL.md frontmatter must include non-empty {key!r}")


def _frozen_task_text(task_dir: Path) -> str:
    refs = ("skill_spec.yaml", "acceptance_criteria.yaml", "verification_spec.yaml", "worker_input.md")
    chunks: list[str] = []
    for ref in refs:
        path = _resolve_task_ref(task_dir, ref)
        if path.exists() and path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks).lower()


def _requires_rust_project(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "rust",
            "cargo",
            "cargo.toml",
            "cargo test",
            "tests/fixtures",
            "local verifier",
            "本地 verifier",
        )
    )


def _is_fixture_ref(ref: str) -> bool:
    parts = Path(ref).parts
    return "fixtures" in parts


def _package_files(task_dir: Path, pattern: str) -> list[str]:
    package_dir = _resolve_task_ref(task_dir, "package")
    if not package_dir.exists() or not package_dir.is_dir():
        return []
    refs: list[str] = []
    for path in sorted(package_dir.rglob(pattern)):
        if not path.is_file():
            continue
        try:
            relative_parts = path.relative_to(package_dir).parts
        except ValueError:
            continue
        if "target" in relative_parts:
            continue
        refs.append("package/" + path.relative_to(package_dir).as_posix())
    return refs


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


def _ensure_manifest(
    *,
    task_dir: Path,
    unit_id: str,
    command_returncode: int,
    changed_files: list[str],
    allowed_scopes: list[str],
    extra_allowed_refs: list[str],
) -> Path:
    path = _resolve_task_ref(task_dir, MANIFEST_REF)
    if path.exists() and path.is_file():
        payload = _read_json_object(path, "worker evidence manifest")
        payload = _normalized_manifest_payload(
            existing=payload,
            unit_id=unit_id,
            command_returncode=command_returncode,
            changed_files=changed_files,
            allowed_scopes=allowed_scopes,
            extra_allowed_refs=extra_allowed_refs,
        )
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path
    payload = _default_manifest_payload(
        unit_id=unit_id,
        command_returncode=command_returncode,
        changed_files=changed_files,
    )
    _validate_manifest_payload(payload, allowed_scopes=allowed_scopes, extra_allowed_refs=extra_allowed_refs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _default_manifest_payload(
    *,
    unit_id: str,
    command_returncode: int,
    changed_files: list[str] | None = None,
) -> dict[str, Any]:
    changed_files = changed_files or CHANGED_FILES
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
        "changed_files": changed_files,
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


def _validate_manifest_payload(
    payload: Mapping[str, Any],
    *,
    allowed_scopes: list[str],
    extra_allowed_refs: list[str],
) -> None:
    if payload.get("schema") != "forgeunit.worker_evidence_manifest":
        raise WorkerBoundaryError("evidence/manifest.json has invalid schema")
    if not isinstance(payload.get("unit_id"), str) or not str(payload.get("unit_id")).strip():
        raise WorkerBoundaryError("evidence/manifest.json is missing unit_id")
    if payload.get("status") != "completed":
        raise WorkerBoundaryError("evidence/manifest.json status must be completed")
    _validate_changed_files(
        _string_list(payload.get("changed_files")),
        allowed_scopes=allowed_scopes,
        extra_allowed_refs=extra_allowed_refs,
    )


def _normalized_manifest_payload(
    *,
    existing: Mapping[str, Any],
    unit_id: str,
    command_returncode: int,
    changed_files: list[str],
    allowed_scopes: list[str],
    extra_allowed_refs: list[str],
) -> dict[str, Any]:
    if existing.get("schema") not in {None, "forgeunit.worker_evidence_manifest"}:
        raise WorkerBoundaryError("evidence/manifest.json has invalid schema")
    default = _default_manifest_payload(
        unit_id=unit_id,
        command_returncode=command_returncode,
        changed_files=changed_files,
    )
    payload = dict(existing)
    payload["schema"] = "forgeunit.worker_evidence_manifest"
    payload["version"] = "0.6"
    payload["unit_id"] = str(payload.get("unit_id") or unit_id)
    payload["status"] = "completed"
    if not payload.get("output_artifacts"):
        payload["output_artifacts"] = default["output_artifacts"]
    if not payload.get("evidence_artifacts"):
        payload["evidence_artifacts"] = default["evidence_artifacts"]
    payload["changed_files"] = _merged_changed_files(_string_list(payload.get("changed_files")), changed_files)
    if not payload.get("commands"):
        payload["commands"] = default["commands"]
    else:
        payload["commands"] = _normalized_manifest_commands(payload.get("commands"))
    if "usage" not in payload:
        payload["usage"] = None
    if not payload.get("usage_unavailable_reason") and payload.get("usage") is None:
        payload["usage_unavailable_reason"] = "external_worker_no_provider_telemetry"
    _validate_manifest_payload(payload, allowed_scopes=allowed_scopes, extra_allowed_refs=extra_allowed_refs)
    return payload


def _normalized_manifest_commands(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        command = item.get("command")
        if not isinstance(command, str) or not command.strip():
            continue
        exit_code = item.get("exit_code")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            continue
        normalized = dict(item)
        normalized["summary"] = str(normalized.get("summary") or "")
        result.append(normalized)
    return result


def _ensure_worker_result(
    *,
    worker_result_path: Path,
    task_dir: Path,
    package_path: Path,
    transcript_path: Path,
    manifest_path: Path,
    changed_files: list[str],
    allowed_scopes: list[str],
    extra_allowed_refs: list[str],
) -> None:
    _assert_under(task_dir, package_path)
    _assert_under(task_dir, transcript_path)
    _assert_under(task_dir, manifest_path)
    if worker_result_path.exists():
        payload = _read_json_object(worker_result_path, "worker_result")
        payload = _normalized_worker_result_payload(
            existing=payload,
            task_dir=task_dir,
            changed_files=changed_files,
            allowed_scopes=allowed_scopes,
            extra_allowed_refs=extra_allowed_refs,
        )
        worker_result_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
        "changed_files": changed_files,
        "usage": None,
        "usage_unavailable_reason": "external_worker_no_provider_telemetry",
    }
    _validate_worker_result_payload(
        payload,
        task_dir=task_dir,
        allowed_scopes=allowed_scopes,
        extra_allowed_refs=extra_allowed_refs,
    )
    worker_result_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalized_worker_result_payload(
    *,
    existing: Mapping[str, Any],
    task_dir: Path,
    changed_files: list[str],
    allowed_scopes: list[str],
    extra_allowed_refs: list[str],
) -> dict[str, Any]:
    if existing.get("status") != "completed":
        raise WorkerBoundaryError("worker_result status must be completed")
    payload = dict(existing)
    payload["status"] = "completed"
    payload["output_artifacts"] = _normalized_artifacts(
        payload.get("output_artifacts"),
        task_dir=task_dir,
        required=[
            {"path": PACKAGE_REF, "kind": "codex_skill", "summary": "Generated Codex Skill package."},
        ],
    )
    payload["boundary_evidence"] = _normalized_artifacts(
        payload.get("boundary_evidence"),
        task_dir=task_dir,
        required=[
            {"path": TRANSCRIPT_REF, "kind": "transcript", "summary": "Boundary transcript summary."},
            {"path": MANIFEST_REF, "kind": "worker_evidence_manifest", "summary": "Worker evidence manifest."},
        ],
    )
    payload["changed_files"] = _merged_changed_files(
        _existing_file_refs(task_dir, _string_list(payload.get("changed_files"))),
        changed_files,
    )
    if "usage" not in payload:
        payload["usage"] = None
    if not payload.get("usage_unavailable_reason") and payload.get("usage") is None:
        payload["usage_unavailable_reason"] = "external_worker_no_provider_telemetry"
    _validate_worker_result_payload(
        payload,
        task_dir=task_dir,
        allowed_scopes=allowed_scopes,
        extra_allowed_refs=extra_allowed_refs,
    )
    return payload


def _normalized_artifacts(
    value: Any,
    *,
    task_dir: Path,
    required: list[dict[str, str]],
) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    seen: set[str] = set()
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            path = item.get("path")
            if not isinstance(path, str) or not path.strip():
                continue
            ref = path.strip()
            if not _is_existing_file_ref(task_dir, ref) or ref in seen:
                continue
            artifacts.append(
                {
                    "path": ref,
                    "kind": str(item.get("kind") or "artifact"),
                    "summary": str(item.get("summary") or ""),
                }
            )
            seen.add(ref)
    for item in required:
        ref = item["path"]
        if ref not in seen:
            if not _is_existing_file_ref(task_dir, ref):
                raise WorkerBoundaryError(f"required worker_result artifact is missing or not a file: {ref}")
            artifacts.append(dict(item))
            seen.add(ref)
    return artifacts


def _validate_worker_result_payload(
    payload: Mapping[str, Any],
    *,
    task_dir: Path,
    allowed_scopes: list[str],
    extra_allowed_refs: list[str],
) -> None:
    if payload.get("status") != "completed":
        raise WorkerBoundaryError("worker_result status must be completed")
    output_paths = _artifact_paths(payload.get("output_artifacts"))
    evidence_paths = _artifact_paths(payload.get("boundary_evidence"))
    if PACKAGE_REF not in output_paths:
        raise WorkerBoundaryError(f"worker_result is missing output artifact: {PACKAGE_REF}")
    for required in (TRANSCRIPT_REF, MANIFEST_REF):
        if required not in evidence_paths:
            raise WorkerBoundaryError(f"worker_result is missing boundary evidence: {required}")
    for ref in [*output_paths, *evidence_paths]:
        if not _is_existing_file_ref(task_dir, ref):
            raise WorkerBoundaryError(f"worker_result artifact is missing or not a file: {ref}")
    changed_files = _merged_changed_files(
        _string_list(payload.get("changed_files")),
        _discover_changed_files(task_dir, allowed_scopes=allowed_scopes),
    )
    _validate_changed_files(
        changed_files,
        allowed_scopes=allowed_scopes,
        extra_allowed_refs=extra_allowed_refs,
    )


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


def _discover_changed_files(task_dir: Path, *, allowed_scopes: list[str] | None = None) -> list[str]:
    discovered: list[str] = []
    scopes = _normalize_write_scopes(allowed_scopes or [])
    for scope in scopes:
        root = _resolve_task_ref(task_dir, scope)
        if not root.exists():
            continue
        if root.is_file():
            discovered.append(root.relative_to(task_dir).as_posix())
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                discovered.append(path.relative_to(task_dir).as_posix())
    return _merged_changed_files(CHANGED_FILES, discovered)


def _merged_changed_files(first: list[str], second: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in [*first, *second]:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _existing_file_refs(task_dir: Path, refs: list[str]) -> list[str]:
    return [ref for ref in refs if _is_existing_file_ref(task_dir, ref)]


def _is_existing_file_ref(task_dir: Path, ref: str) -> bool:
    try:
        path = _resolve_task_ref(task_dir, ref)
    except WorkerBoundaryError:
        return False
    return path.is_file()


def _validate_changed_files(
    changed_files: list[str],
    *,
    allowed_scopes: list[str] | None = None,
    extra_allowed_refs: list[str] | None = None,
) -> None:
    scopes = _normalize_write_scopes(allowed_scopes or [])
    extra_refs = set(_safe_extra_allowed_refs(extra_allowed_refs or []))
    if not changed_files:
        raise WorkerBoundaryError("changed_files must list outputs inside the ForgeUnit write scope")
    for ref in changed_files:
        if not isinstance(ref, str) or ref.startswith("/") or ".." in Path(ref).parts:
            raise WorkerBoundaryError(f"unsafe changed file ref: {ref!r}")
        if ref in extra_refs:
            continue
        if not _ref_is_under_scope(ref, scopes):
            allowed = ", ".join(f"{scope}/" for scope in scopes)
            raise WorkerBoundaryError(f"changed file outside ForgeUnit write scope ({allowed}): {ref}")


def _safe_extra_allowed_refs(refs: list[str]) -> list[str]:
    result: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip():
            continue
        text = ref.strip()
        if text.startswith("/") or ".." in Path(text).parts:
            continue
        result.append(text)
    return result


def _ref_is_under_scope(ref: str, scopes: list[str]) -> bool:
    return any(ref == scope or ref.startswith(scope + "/") for scope in scopes)


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
