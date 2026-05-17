"""WP3 worker boundary, deterministic fake fixtures, and attempt artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
from pathlib import Path, PurePosixPath
import time
from typing import Any, Mapping, Protocol

from .schema import (
    BuildContract,
    ExecutionReport,
    JsonValue,
    WorkerInvocation,
    ensure_json_compatible,
    sha256_file,
    sha256_json,
    utc_now,
)
from .security import PathSecurityError, validate_relative_path
from .workspace import JobWorkspace


WORKER_ADAPTER_VERSION = "skillfoundry.worker_adapter.v1"


class WorkerAttemptLimitError(ValueError):
    """Raised before invocation when an attempt would exceed its contract."""


class WorkerPathError(PathSecurityError):
    """Raised when a worker attempts a write outside its allowed roots."""


class FakeWorkerMode(StrEnum):
    """Deterministic FakeWorker fixture modes for WP3 tests and E2E smoke."""

    MINIMAL_SUCCESS = "minimal_success"
    INTENTIONAL_FAILURE = "intentional_failure"
    REPAIR_SUCCESS = "repair_success"
    MISSING_REPORT = "missing_report"
    PATH_ESCAPE = "path_escape"
    SIMULATED_TIMEOUT = "simulated_timeout"


@dataclass(frozen=True)
class WorkerExecutionOutcome:
    """Worker-returned execution summary before adapter classification."""

    status: str
    exit_status: str
    summary: str
    artifacts: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    transcript_lines: list[str] = field(default_factory=list)
    write_execution_report: bool = True
    usage_available: bool = False
    usage_unavailable_reason: str = "worker usage data is unavailable at the adapter boundary"
    simulated_duration_ms: int | None = None
    timed_out: bool = False


@dataclass(frozen=True)
class WorkerRunResult:
    """Collected worker boundary result.

    ``accepted`` is deliberately always false in WP3: worker completion is not
    verifier acceptance and cannot register a package by itself.
    """

    invocation: WorkerInvocation
    report: ExecutionReport
    input_manifest: dict[str, JsonValue]
    failure_class: str | None
    ready_for_verifier: bool
    accepted: bool = False


class BuildWorker(Protocol):
    """Narrow interface implemented by external builder adapters."""

    @property
    def worker_type(self) -> str:
        """Stable worker type recorded in invocation metadata."""

    def run(self, context: "WorkerRunContext") -> WorkerExecutionOutcome:
        """Run the worker against a confined context."""


@dataclass
class WorkerRunContext:
    """Confined write context passed to worker implementations."""

    _workspace: JobWorkspace
    job_id: str
    attempt_id: str
    invocation_id: str
    attempt_dir_ref: str
    timeout_seconds: int
    writable_roots: tuple[str, ...]
    input_manifest: Mapping[str, JsonValue]
    previous_attempt_id: str | None = None
    writes: list[str] = field(default_factory=list)

    def write_text(self, relative_path: str, content: str) -> None:
        """Write UTF-8 text only under package/ or this attempt directory."""

        target = self.resolve_write_path(relative_path)
        target.write_text(content, encoding="utf-8")
        self.writes.append(relative_path)

    def write_json(self, relative_path: str, payload: Mapping[str, Any]) -> None:
        compatible = ensure_json_compatible(dict(payload))
        text = json.dumps(compatible, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        self.write_text(relative_path, text + "\n")

    def resolve_write_path(self, relative_path: str) -> Path:
        safe_relative = validate_relative_path(relative_path)
        if not any(_is_under_or_equal(safe_relative, validate_relative_path(root)) for root in self.writable_roots):
            roots = ", ".join(self.writable_roots)
            raise WorkerPathError(f"worker write is outside allowed roots ({roots}): {relative_path}")
        return self._workspace.resolve_path(str(safe_relative))


class WorkerAdapter:
    """Prepare, run, collect, and classify a worker invocation."""

    def __init__(
        self,
        worker: BuildWorker,
        *,
        adapter_version: str = WORKER_ADAPTER_VERSION,
        env_allowlist: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        self.worker = worker
        self.adapter_version = adapter_version
        self.env_allowlist = tuple(env_allowlist or ())

    def invoke(
        self,
        workspace: JobWorkspace,
        attempt_id: str,
        *,
        previous_attempt_id: str | None = None,
        timeout_seconds: int | None = None,
        worker_config: Mapping[str, Any] | None = None,
    ) -> WorkerRunResult:
        """Run one confined worker attempt and return boundary evidence."""

        contract = BuildContract.read_yaml_file(workspace.resolve_path("build_contract.yaml", must_exist=True))
        if contract.job_id != workspace.job_id:
            raise ValueError(f"build contract job_id {contract.job_id!r} does not match workspace {workspace.job_id!r}")

        _enforce_attempt_limit(attempt_id, contract.attempt_limit)
        timeout = int(timeout_seconds if timeout_seconds is not None else contract.timeout_seconds)
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")

        attempt_dir_ref = _attempt_dir_ref(attempt_id)
        attempt_dir = workspace.resolve_path(attempt_dir_ref)
        attempt_dir.mkdir(parents=False, exist_ok=False)

        invocation_id = _invocation_id(workspace.job_id, attempt_id, self.worker.worker_type, worker_config)
        artifact_refs = _attempt_artifact_refs(attempt_id)
        writable_roots = ("package", attempt_dir_ref)
        input_manifest = self._build_input_manifest(
            workspace=workspace,
            contract=contract,
            attempt_id=attempt_id,
            invocation_id=invocation_id,
            timeout_seconds=timeout,
            writable_roots=writable_roots,
            previous_attempt_id=previous_attempt_id,
            worker_config=worker_config or {},
        )
        _write_json(workspace, artifact_refs["input_manifest"], input_manifest)
        input_manifest_hash = sha256_file(workspace.resolve_path(artifact_refs["input_manifest"], must_exist=True))

        before_snapshot = _snapshot_workspace(workspace.root)
        workspace_hash_before = sha256_json(before_snapshot)
        started_at = utc_now()
        monotonic_started = time.monotonic()
        context = WorkerRunContext(
            _workspace=workspace,
            job_id=workspace.job_id,
            attempt_id=attempt_id,
            invocation_id=invocation_id,
            attempt_dir_ref=attempt_dir_ref,
            timeout_seconds=timeout,
            writable_roots=writable_roots,
            input_manifest=input_manifest,
            previous_attempt_id=previous_attempt_id,
        )

        outcome: WorkerExecutionOutcome
        failure_class: str | None = None
        try:
            outcome = self.worker.run(context)
        except WorkerPathError as exc:
            failure_class = "path_escape"
            outcome = _failure_outcome(
                exit_status="rejected",
                summary="Worker attempted to write outside allowed paths.",
                failure=str(exc),
                transcript_line=f"path security rejection: {exc}",
            )
        except PathSecurityError as exc:
            failure_class = "path_escape"
            outcome = _failure_outcome(
                exit_status="rejected",
                summary="Worker attempted an unsafe workspace path.",
                failure=str(exc),
                transcript_line=f"path security rejection: {exc}",
            )
        except Exception as exc:  # pragma: no cover - defensive boundary classification
            failure_class = "worker_exception"
            outcome = _failure_outcome(
                exit_status="failure",
                summary="Worker raised an unexpected exception.",
                failure=f"{type(exc).__name__}: {exc}",
                transcript_line=f"worker exception: {type(exc).__name__}: {exc}",
            )

        elapsed_ms = _duration_ms(monotonic_started, outcome.simulated_duration_ms)
        timed_out = outcome.timed_out or elapsed_ms > timeout * 1000
        if timed_out:
            failure_class = "timeout"
            outcome = WorkerExecutionOutcome(
                status="failed",
                exit_status="timeout",
                summary="Worker invocation exceeded the configured timeout.",
                artifacts=outcome.artifacts,
                failures=[*outcome.failures, f"timeout_seconds={timeout}"],
                transcript_lines=[*outcome.transcript_lines, "adapter classified invocation as timeout"],
                write_execution_report=True,
                usage_available=outcome.usage_available,
                usage_unavailable_reason=outcome.usage_unavailable_reason,
                simulated_duration_ms=max(elapsed_ms, timeout * 1000),
                timed_out=True,
            )
            elapsed_ms = _duration_ms(monotonic_started, outcome.simulated_duration_ms)

        missing_report = not outcome.write_execution_report
        if missing_report:
            failure_class = "missing_execution_report"
            outcome = WorkerExecutionOutcome(
                status="failed",
                exit_status="failure",
                summary="Worker did not produce execution_report.json; adapter classified the attempt as failure.",
                artifacts=outcome.artifacts,
                failures=[*outcome.failures, "missing execution_report.json"],
                transcript_lines=[*outcome.transcript_lines, "adapter classified missing execution report as failure"],
                write_execution_report=True,
                usage_available=outcome.usage_available,
                usage_unavailable_reason=outcome.usage_unavailable_reason,
                simulated_duration_ms=elapsed_ms,
                timed_out=False,
            )

        if failure_class is None and outcome.exit_status != "success":
            failure_class = outcome.exit_status or "worker_failure"
        if failure_class is None and outcome.status != "completed":
            failure_class = outcome.status or "worker_failure"

        finished_at = utc_now()
        transcript = _format_transcript(
            invocation_id=invocation_id,
            worker_type=self.worker.worker_type,
            outcome=outcome,
            writes=context.writes,
        )
        _write_text(workspace, artifact_refs["transcript"], transcript)

        report = ExecutionReport(
            report_id=f"report-{invocation_id}",
            invocation_id=invocation_id,
            job_id=workspace.job_id,
            attempt_id=attempt_id,
            status=outcome.status,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=elapsed_ms,
            exit_status=outcome.exit_status,
            summary=outcome.summary,
            artifacts=list(outcome.artifacts),
            failures=list(outcome.failures),
        )
        report.write_json_file(workspace.resolve_path(artifact_refs["execution_report"]))

        after_worker_snapshot = _snapshot_workspace(workspace.root)
        _write_text(workspace, artifact_refs["diff"], _summary_patch(before_snapshot, after_worker_snapshot))
        workspace_hash_after = sha256_json(_snapshot_workspace(workspace.root))

        invocation = WorkerInvocation(
            invocation_id=invocation_id,
            job_id=workspace.job_id,
            attempt_id=attempt_id,
            worker_type=self.worker.worker_type,
            adapter_version=self.adapter_version,
            input_manifest_hash=input_manifest_hash,
            workspace_hash_before=workspace_hash_before,
            workspace_hash_after=workspace_hash_after,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=elapsed_ms,
            usage_available=outcome.usage_available,
            usage_unavailable_reason=outcome.usage_unavailable_reason,
            transcript_ref=artifact_refs["transcript"],
            execution_report_ref=artifact_refs["execution_report"],
            diff_ref=artifact_refs["diff"],
            exit_status=outcome.exit_status,
        )

        return WorkerRunResult(
            invocation=invocation,
            report=report,
            input_manifest=input_manifest,
            failure_class=failure_class,
            ready_for_verifier=outcome.status == "completed" and outcome.exit_status == "success",
        )

    def _build_input_manifest(
        self,
        *,
        workspace: JobWorkspace,
        contract: BuildContract,
        attempt_id: str,
        invocation_id: str,
        timeout_seconds: int,
        writable_roots: tuple[str, ...],
        previous_attempt_id: str | None,
        worker_config: Mapping[str, Any],
    ) -> dict[str, JsonValue]:
        payload = {
            "schema_version": "skillfoundry.worker_input_manifest.v1",
            "adapter_version": self.adapter_version,
            "generated_at": utc_now(),
            "invocation_id": invocation_id,
            "job_id": workspace.job_id,
            "attempt_id": attempt_id,
            "worker_type": self.worker.worker_type,
            "build_contract_ref": "build_contract.yaml",
            "skill_spec_ref": contract.skill_spec_ref,
            "verification_spec_ref": contract.verification_spec_ref,
            "worker_input_ref": "worker_input.md",
            "artifact_manifest_ref": "artifact_manifest.json",
            "locked_input_hashes": contract.locked_input_hashes,
            "declared_allowed_write_paths": list(contract.allowed_write_paths),
            "writable_paths": list(writable_roots),
            "blocked_paths": list(contract.blocked_paths),
            "env_allowlist": sorted(self.env_allowlist),
            "timeout_seconds": timeout_seconds,
            "attempt_limit": contract.attempt_limit,
            "previous_attempt_id": previous_attempt_id,
            "worker_config": ensure_json_compatible(dict(worker_config)),
        }
        return ensure_json_compatible(payload)  # type: ignore[return-value]


class FakeWorker:
    """Deterministic local worker used to test the WP3 boundary."""

    def __init__(self, mode: FakeWorkerMode | str = FakeWorkerMode.MINIMAL_SUCCESS) -> None:
        self.mode = FakeWorkerMode(mode)

    @property
    def worker_type(self) -> str:
        return f"fake:{self.mode.value}"

    def run(self, context: WorkerRunContext) -> WorkerExecutionOutcome:
        if self.mode is FakeWorkerMode.MINIMAL_SUCCESS:
            return self._minimal_success(context)
        if self.mode is FakeWorkerMode.INTENTIONAL_FAILURE:
            return self._intentional_failure(context)
        if self.mode is FakeWorkerMode.REPAIR_SUCCESS:
            return self._repair_success(context)
        if self.mode is FakeWorkerMode.MISSING_REPORT:
            return self._missing_report(context)
        if self.mode is FakeWorkerMode.PATH_ESCAPE:
            return self._path_escape(context)
        if self.mode is FakeWorkerMode.SIMULATED_TIMEOUT:
            return self._simulated_timeout(context)
        raise AssertionError(f"unhandled fake worker mode: {self.mode}")

    def _minimal_success(self, context: WorkerRunContext) -> WorkerExecutionOutcome:
        context.write_text("package/SKILL.md", _skill_markdown("minimal-success", "Build a minimal fixture skill."))
        return WorkerExecutionOutcome(
            status="completed",
            exit_status="success",
            summary="FakeWorker wrote a minimal package; verifier approval is still required.",
            artifacts=["package/SKILL.md"],
            transcript_lines=["created package/SKILL.md"],
            usage_unavailable_reason="FakeWorker does not call model providers.",
        )

    def _intentional_failure(self, context: WorkerRunContext) -> WorkerExecutionOutcome:
        context.write_text(
            "package/SKILL.md",
            "# Intentional Failure Fixture\n\nThis package is intentionally incomplete for verifier tests.\n",
        )
        return WorkerExecutionOutcome(
            status="failed",
            exit_status="failure",
            summary="FakeWorker intentionally produced an incomplete package.",
            artifacts=["package/SKILL.md"],
            failures=["intentional failure fixture"],
            transcript_lines=["created intentionally incomplete package/SKILL.md"],
            usage_unavailable_reason="FakeWorker does not call model providers.",
        )

    def _repair_success(self, context: WorkerRunContext) -> WorkerExecutionOutcome:
        repair_basis = context.previous_attempt_id or "unknown"
        context.write_text(
            "package/SKILL.md",
            _skill_markdown("repair-success", f"Repair after failed attempt {repair_basis}."),
        )
        return WorkerExecutionOutcome(
            status="completed",
            exit_status="success",
            summary="FakeWorker wrote a repaired package; verifier approval is still required.",
            artifacts=["package/SKILL.md"],
            transcript_lines=[f"repaired package/SKILL.md using previous attempt {repair_basis}"],
            usage_unavailable_reason="FakeWorker does not call model providers.",
        )

    def _missing_report(self, context: WorkerRunContext) -> WorkerExecutionOutcome:
        context.write_text("package/SKILL.md", _skill_markdown("missing-report", "Omit the worker report."))
        return WorkerExecutionOutcome(
            status="completed",
            exit_status="success",
            summary="FakeWorker omitted the execution report fixture.",
            artifacts=["package/SKILL.md"],
            transcript_lines=["created package/SKILL.md but omitted execution_report.json"],
            write_execution_report=False,
            usage_unavailable_reason="FakeWorker does not call model providers.",
        )

    def _path_escape(self, context: WorkerRunContext) -> WorkerExecutionOutcome:
        context.write_text("../outside-job.txt", "this must never be written\n")
        return WorkerExecutionOutcome(
            status="completed",
            exit_status="success",
            summary="unreachable path escape fixture result",
            usage_unavailable_reason="FakeWorker does not call model providers.",
        )

    def _simulated_timeout(self, context: WorkerRunContext) -> WorkerExecutionOutcome:
        return WorkerExecutionOutcome(
            status="failed",
            exit_status="timeout",
            summary="FakeWorker deterministically simulated a timeout.",
            failures=["simulated timeout"],
            transcript_lines=["simulated timeout without sleeping"],
            usage_unavailable_reason="FakeWorker does not call model providers.",
            simulated_duration_ms=context.timeout_seconds * 1000 + 1,
            timed_out=True,
        )


class CodexWorker:
    """Placeholder for the future WP8 Codex adapter; it does not run Codex."""

    @property
    def worker_type(self) -> str:
        return "codex:placeholder"

    def run(self, context: WorkerRunContext) -> WorkerExecutionOutcome:
        return WorkerExecutionOutcome(
            status="failed",
            exit_status="unsupported",
            summary="CodexWorker is a placeholder; real Codex invocation is intentionally not implemented in WP3.",
            failures=["real Codex worker integration is deferred until WP8"],
            transcript_lines=["no Codex CLI, SDK, LLM call, shell runtime, or MCP runtime was invoked"],
            usage_unavailable_reason="CodexWorker placeholder does not invoke a provider.",
        )


def _attempt_artifact_refs(attempt_id: str) -> dict[str, str]:
    attempt_dir = _attempt_dir_ref(attempt_id)
    return {
        "input_manifest": f"{attempt_dir}/input_manifest.json",
        "execution_report": f"{attempt_dir}/execution_report.json",
        "diff": f"{attempt_dir}/output_diff.patch",
        "transcript": f"{attempt_dir}/worker_transcript.log",
    }


def _attempt_dir_ref(attempt_id: str) -> str:
    _attempt_number(attempt_id)
    return f"attempts/{attempt_id}"


def _attempt_number(attempt_id: str) -> int:
    if not isinstance(attempt_id, str) or not attempt_id.isdecimal():
        raise ValueError("attempt_id must be a positive decimal string")
    number = int(attempt_id)
    if number <= 0:
        raise ValueError("attempt_id must be positive")
    return number


def _enforce_attempt_limit(attempt_id: str, attempt_limit: int) -> None:
    number = _attempt_number(attempt_id)
    if number > attempt_limit:
        raise WorkerAttemptLimitError(f"attempt {attempt_id} exceeds attempt_limit {attempt_limit}")


def _invocation_id(
    job_id: str,
    attempt_id: str,
    worker_type: str,
    worker_config: Mapping[str, Any] | None,
) -> str:
    digest = sha256_json(
        {
            "attempt_id": attempt_id,
            "job_id": job_id,
            "worker_config": ensure_json_compatible(dict(worker_config or {})),
            "worker_type": worker_type,
            "adapter_version": WORKER_ADAPTER_VERSION,
        }
    )
    return f"inv-{digest[:20]}"


def _is_under_or_equal(path: PurePosixPath, root: PurePosixPath) -> bool:
    return path == root or path.parts[: len(root.parts)] == root.parts


def _write_json(workspace: JobWorkspace, relative_path: str, payload: Mapping[str, Any]) -> None:
    compatible = ensure_json_compatible(dict(payload))
    text = json.dumps(compatible, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    _write_text(workspace, relative_path, text + "\n")


def _write_text(workspace: JobWorkspace, relative_path: str, content: str) -> None:
    workspace.resolve_path(relative_path).write_text(content, encoding="utf-8")


def _failure_outcome(*, exit_status: str, summary: str, failure: str, transcript_line: str) -> WorkerExecutionOutcome:
    return WorkerExecutionOutcome(
        status="failed",
        exit_status=exit_status,
        summary=summary,
        failures=[failure],
        transcript_lines=[transcript_line],
        usage_unavailable_reason="Worker failed before usage data could be available.",
    )


def _duration_ms(monotonic_started: float, simulated_duration_ms: int | None) -> int:
    if simulated_duration_ms is not None:
        return max(0, int(simulated_duration_ms))
    return max(0, int((time.monotonic() - monotonic_started) * 1000))


def _snapshot_workspace(root: Path) -> list[dict[str, JsonValue]]:
    root_path = Path(root).resolve(strict=True)
    entries: list[dict[str, JsonValue]] = []
    for path in sorted(root_path.rglob("*")):
        relative = path.relative_to(root_path).as_posix()
        if path.is_symlink():
            entries.append({"path": relative, "kind": "symlink", "target": str(path.readlink())})
        elif path.is_file():
            entries.append({"path": relative, "kind": "file", "sha256": sha256_file(path), "size": path.stat().st_size})
        elif path.is_dir():
            entries.append({"path": relative, "kind": "dir"})
    return entries


def _summary_patch(before: list[dict[str, JsonValue]], after: list[dict[str, JsonValue]]) -> str:
    before_by_path = {str(item["path"]): item for item in before}
    after_by_path = {str(item["path"]): item for item in after}
    paths = sorted(set(before_by_path) | set(after_by_path))
    lines = [
        "# SkillFoundry deterministic output summary",
        "# This is a summary patch, not a source-control diff.",
    ]
    for path in paths:
        old = before_by_path.get(path)
        new = after_by_path.get(path)
        if old is None:
            lines.append(f"+ {path} {new.get('kind') if new else 'unknown'} {_hash_for_entry(new)}")
        elif new is None:
            lines.append(f"- {path} {old.get('kind')} {_hash_for_entry(old)}")
        elif _hash_for_entry(old) != _hash_for_entry(new) or old.get("kind") != new.get("kind"):
            lines.append(f"~ {path} {old.get('kind')}:{_hash_for_entry(old)} -> {new.get('kind')}:{_hash_for_entry(new)}")
    if len(lines) == 2:
        lines.append("# no workspace changes")
    return "\n".join(lines) + "\n"


def _hash_for_entry(entry: Mapping[str, JsonValue] | None) -> str:
    if not entry:
        return "-"
    if entry.get("kind") == "file":
        return str(entry.get("sha256"))
    if entry.get("kind") == "symlink":
        return str(entry.get("target"))
    return "-"


def _format_transcript(
    *,
    invocation_id: str,
    worker_type: str,
    outcome: WorkerExecutionOutcome,
    writes: list[str],
) -> str:
    lines = [
        f"invocation_id={invocation_id}",
        f"worker_type={worker_type}",
        f"status={outcome.status}",
        f"exit_status={outcome.exit_status}",
    ]
    lines.extend(f"write={path}" for path in writes)
    lines.extend(outcome.transcript_lines)
    return "\n".join(lines) + "\n"


def _skill_markdown(name: str, description: str) -> str:
    return "\n".join(
        [
            "---",
            f"name: {name}",
            f"description: {description}",
            "---",
            "",
            f"# {name}",
            "",
            "## When To Use",
            "",
            "- Use this deterministic fixture when SkillFoundry needs a local worker package.",
            "",
            "## Inputs",
            "",
            "- A SkillFoundry build contract and worker input manifest.",
            "",
            "## Outputs",
            "",
            "- A Codex Skill package candidate in `package/`.",
            "",
            "## Guardrails",
            "",
            "- This worker output still requires the future independent Verifier gate.",
            "",
        ]
    )
