"""PiWorker command boundary for owned agent-runtime experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import shlex
import subprocess
import time
from typing import Any, Mapping, Protocol, Sequence

from .schema import ExecutionReport, JsonValue, ensure_json_compatible, sha256_file, utc_now
from .security import PathSecurityError, validate_relative_path
from .workspace import JobWorkspace


PI_WORKER_INPUT_SCHEMA_VERSION = "skillfoundry.pi_worker_input.v1"
PI_WORKER_OUTPUT_SCHEMA_VERSION = "skillfoundry.pi_worker_output.v1"
DEFAULT_PI_WORKER_TIMEOUT_SECONDS = 300

PI_WORKER_INPUT_NAME = "pi_worker_input.json"
PI_WORKER_OUTPUT_NAME = "pi_worker_output.json"
PI_WORKER_SESSION_NAME = "pi_session.jsonl"
PI_WORKER_EVENTS_NAME = "pi_events.jsonl"
PI_WORKER_METRICS_NAME = "pi_metrics.json"

PI_WORKER_STATUSES = frozenset({"completed", "failed", "blocked", "cancelled"})
PI_WORKER_VERIFICATION_STATUSES = frozenset({"passed", "failed", "not_run", "review_required"})


class PiWorkerError(RuntimeError):
    """Raised when the PiWorker adapter cannot prepare or parse its boundary."""


@dataclass(frozen=True)
class PiWorkerCommandResult:
    """Process result returned by a PiWorker command runner."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class PiWorkerCommandRunner(Protocol):
    """Command runner boundary used by ``PiWorker``."""

    def run(
        self,
        command: Sequence[str],
        *,
        input_path: Path,
        cwd: Path,
        timeout_seconds: int,
    ) -> PiWorkerCommandResult:
        """Run the Pi sidecar command against one input artifact."""


class SubprocessPiWorkerCommandRunner:
    """Subprocess-backed runner for the future Node Pi sidecar."""

    def run(
        self,
        command: Sequence[str],
        *,
        input_path: Path,
        cwd: Path,
        timeout_seconds: int,
    ) -> PiWorkerCommandResult:
        try:
            completed = subprocess.run(
                [*command, str(input_path)],
                cwd=cwd,
                timeout=timeout_seconds,
                text=True,
                capture_output=True,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return PiWorkerCommandResult(
                returncode=-1,
                stdout=_process_output_text(exc.stdout),
                stderr=_process_output_text(exc.stderr),
                timed_out=True,
            )
        return PiWorkerCommandResult(
            returncode=completed.returncode,
            stdout=_process_output_text(completed.stdout),
            stderr=_process_output_text(completed.stderr),
        )


@dataclass(frozen=True)
class PiWorkerConfig:
    """Configuration for one PiWorker adapter instance."""

    command: tuple[str, ...]
    timeout_seconds: int = DEFAULT_PI_WORKER_TIMEOUT_SECONDS
    runtime_name: str = "pi-worker"
    model_provider: str | None = None
    model: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.command:
            raise PiWorkerError("PiWorker command must not be empty")
        for part in self.command:
            if not isinstance(part, str) or not part or "\x00" in part:
                raise PiWorkerError("PiWorker command parts must be non-empty strings without NUL bytes")
        if (
            not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise PiWorkerError("PiWorker timeout_seconds must be a positive integer")
        _reject_sensitive_runtime_metadata(self.metadata)


@dataclass(frozen=True)
class PiWorkerRunResult:
    """Normalized PiWorker output consumed by SkillFoundry."""

    job_id: str
    iteration: int
    status: str
    produced_artifacts: list[str] = field(default_factory=list)
    changed_refs: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    worker_claims: list[str] = field(default_factory=list)
    verifier_evidence: list[str] = field(default_factory=list)
    new_unknowns: list[str] = field(default_factory=list)
    recommended_next_steps: list[str] = field(default_factory=list)
    verification_status: str = "not_run"
    input_ref: str = ""
    output_ref: str = ""
    session_ref: str = ""
    events_ref: str = ""
    metrics_ref: str = ""
    duration_ms: int = 0
    metrics: dict[str, JsonValue] = field(default_factory=dict)

    def validate(self) -> None:
        if not isinstance(self.job_id, str) or not self.job_id:
            raise PiWorkerError("PiWorker result job_id must be a non-empty string")
        if not isinstance(self.iteration, int) or isinstance(self.iteration, bool) or self.iteration <= 0:
            raise PiWorkerError("PiWorker result iteration must be a positive integer")
        if self.status not in PI_WORKER_STATUSES:
            raise PiWorkerError(f"PiWorker status is not supported: {self.status}")
        if self.verification_status not in PI_WORKER_VERIFICATION_STATUSES:
            raise PiWorkerError(f"PiWorker verification_status is not supported: {self.verification_status}")
        for field_name in (
            "produced_artifacts",
            "changed_refs",
            "verifier_evidence",
        ):
            _validate_ref_list(getattr(self, field_name), field_name)
        for field_name in ("input_ref", "output_ref", "session_ref", "events_ref", "metrics_ref"):
            value = getattr(self, field_name)
            if value:
                _validate_ref(value, field_name)
        for field_name in (
            "commands_run",
            "tests_run",
            "failures",
            "worker_claims",
            "new_unknowns",
            "recommended_next_steps",
        ):
            _validate_str_list(getattr(self, field_name), field_name)
        if not isinstance(self.duration_ms, int) or isinstance(self.duration_ms, bool) or self.duration_ms < 0:
            raise PiWorkerError("PiWorker duration_ms must be a non-negative integer")

    def to_adaptive_kwargs(self) -> dict[str, object]:
        """Return kwargs compatible with ``AdaptiveWorkUnitResult``."""

        self.validate()
        return {
            "produced_artifacts": list(self.produced_artifacts),
            "changed_refs": list(self.changed_refs),
            "commands_run": list(self.commands_run),
            "tests_run": list(self.tests_run),
            "failures": list(self.failures),
            "worker_claims": list(self.worker_claims),
            "verifier_evidence": list(self.verifier_evidence),
            "new_unknowns": list(self.new_unknowns),
            "recommended_next_steps": list(self.recommended_next_steps),
            "verification_status": self.verification_status,
        }


class PiWorker:
    """Invoke a Pi runtime sidecar and normalize its work-unit result."""

    def __init__(
        self,
        config: PiWorkerConfig,
        *,
        runner: PiWorkerCommandRunner | None = None,
    ) -> None:
        self.config = config
        self.runner = runner or SubprocessPiWorkerCommandRunner()

    def invoke(self, workspace: JobWorkspace, contract: Any) -> PiWorkerRunResult:
        """Run PiWorker against one next-step contract."""

        workspace.check_locked_inputs()
        iteration = _contract_iteration(contract)
        refs = _pi_worker_refs(iteration)
        _ensure_attempt_dir(workspace, refs["attempt_dir"])
        input_payload = self._build_input_payload(workspace, contract, refs)
        input_path = workspace.resolve_path(refs["input"])
        _write_json(input_path, input_payload)

        started = time.monotonic()
        command_result = self.runner.run(
            self.config.command,
            input_path=input_path,
            cwd=workspace.root,
            timeout_seconds=self.config.timeout_seconds,
        )
        duration_ms = _duration_ms(started)
        output_path = workspace.resolve_path(refs["output"])
        if command_result.timed_out:
            return self._failure_result(
                workspace,
                iteration=iteration,
                refs=refs,
                duration_ms=duration_ms,
                failure=f"pi_worker timed out after {self.config.timeout_seconds} seconds",
                command_result=command_result,
                status="failed",
            )
        if command_result.returncode != 0:
            return self._failure_result(
                workspace,
                iteration=iteration,
                refs=refs,
                duration_ms=duration_ms,
                failure=f"pi_worker exited with return code {command_result.returncode}",
                command_result=command_result,
                status="failed",
            )
        if not output_path.is_file():
            return self._failure_result(
                workspace,
                iteration=iteration,
                refs=refs,
                duration_ms=duration_ms,
                failure=f"pi_worker output artifact is missing: {refs['output']}",
                command_result=command_result,
                status="failed",
            )

        try:
            result = _read_output_result(output_path, workspace=workspace, input_ref=refs["input"], duration_ms=duration_ms)
            result.validate()
        except PiWorkerError as exc:
            return self._failure_result(
                workspace,
                iteration=iteration,
                refs=refs,
                duration_ms=duration_ms,
                failure=str(exc),
                command_result=command_result,
                status="failed",
            )
        return result

    def _build_input_payload(self, workspace: JobWorkspace, contract: Any, refs: Mapping[str, str]) -> dict[str, JsonValue]:
        payload = {
            "schema_version": PI_WORKER_INPUT_SCHEMA_VERSION,
            "job_id": workspace.job_id,
            "iteration": _contract_iteration(contract),
            "workspace_root": str(workspace.root.resolve()),
            "created_at": utc_now(),
            "attempt_dir_ref": refs["attempt_dir"],
            "input_ref": refs["input"],
            "output_ref": refs["output"],
            "session_ref": refs["session"],
            "events_ref": refs["events"],
            "metrics_ref": refs["metrics"],
            "contract": _contract_payload(contract),
            "runtime": {
                "runtime_name": self.config.runtime_name,
                "command": list(self.config.command),
                "timeout_seconds": self.config.timeout_seconds,
                "model_provider": self.config.model_provider,
                "model": self.config.model,
                "metadata": ensure_json_compatible(dict(self.config.metadata)),
            },
        }
        return ensure_json_compatible(payload)  # type: ignore[return-value]

    def _failure_result(
        self,
        workspace: JobWorkspace,
        *,
        iteration: int,
        refs: Mapping[str, str],
        duration_ms: int,
        failure: str,
        command_result: PiWorkerCommandResult,
        status: str,
    ) -> PiWorkerRunResult:
        output_path = workspace.resolve_path(refs["output"])
        payload = {
            "schema_version": PI_WORKER_OUTPUT_SCHEMA_VERSION,
            "job_id": workspace.job_id,
            "iteration": iteration,
            "status": status,
            "produced_artifacts": [],
            "changed_refs": [refs["output"]],
            "commands_run": [_format_command(self.config.command)],
            "tests_run": [],
            "failures": [
                failure,
                *_prefixed_stream_lines("stdout", command_result.stdout),
                *_prefixed_stream_lines("stderr", command_result.stderr),
            ],
            "worker_claims": [],
            "verifier_evidence": [refs["output"]],
            "new_unknowns": [],
            "recommended_next_steps": ["Inspect PiWorker sidecar failure before retrying."],
            "verification_status": "failed",
            "input_ref": refs["input"],
            "output_ref": refs["output"],
            "session_ref": refs["session"],
            "events_ref": refs["events"],
            "metrics_ref": refs["metrics"],
            "duration_ms": duration_ms,
            "metrics": {
                "duration_ms": duration_ms,
                "returncode": command_result.returncode,
                "timed_out": command_result.timed_out,
            },
        }
        _write_json(output_path, payload)
        return _result_from_payload(payload, input_ref=refs["input"], duration_ms=duration_ms)


def load_pi_worker_run_result(workspace: JobWorkspace, iteration: int) -> PiWorkerRunResult:
    """Load a normalized PiWorker result from a workspace attempt directory."""

    refs = _pi_worker_refs(iteration)
    output_path = workspace.resolve_path(refs["output"], must_exist=True)
    return _read_output_result(output_path, workspace=workspace, input_ref=refs["input"], duration_ms=0)


def build_pi_worker_execution_report(
    workspace: JobWorkspace,
    result: PiWorkerRunResult,
    *,
    attempt_id: str | None = None,
    created_at: str | None = None,
) -> ExecutionReport:
    """Build the attempt-level execution report expected by the package verifier."""

    result.validate()
    attempt_value = attempt_id or f"{result.iteration:03d}"
    if not isinstance(attempt_value, str) or not attempt_value:
        raise PiWorkerError("attempt_id must be a non-empty string")
    created = created_at or utc_now()
    artifacts = _dedupe_refs(
        [
            *result.produced_artifacts,
            *result.changed_refs,
            result.output_ref,
            result.session_ref,
            result.events_ref,
            result.metrics_ref,
            result.input_ref,
            f"adaptive/attempts/{result.iteration:03d}/work_unit_result.json",
        ]
    )
    report = ExecutionReport(
        report_id=f"{workspace.job_id}:pi-worker:{attempt_value}",
        invocation_id=f"{workspace.job_id}:pi-worker:{attempt_value}",
        job_id=workspace.job_id,
        attempt_id=attempt_value,
        status="completed" if result.status == "completed" else "failed",
        started_at=created,
        finished_at=created,
        duration_ms=result.duration_ms,
        exit_status="success" if result.status == "completed" else "failure",
        summary=(
            f"PiWorker completed attempt {attempt_value} with {len(result.produced_artifacts)} produced artifact(s)."
        ),
        artifacts=artifacts,
        failures=list(result.failures),
    )
    report.validate()
    return report


def _pi_worker_refs(iteration: int) -> dict[str, str]:
    if not isinstance(iteration, int) or isinstance(iteration, bool) or iteration <= 0:
        raise PiWorkerError("PiWorker iteration must be a positive integer")
    attempt_dir = f"adaptive/attempts/{iteration:03d}"
    return {
        "attempt_dir": attempt_dir,
        "input": f"{attempt_dir}/{PI_WORKER_INPUT_NAME}",
        "output": f"{attempt_dir}/{PI_WORKER_OUTPUT_NAME}",
        "session": f"{attempt_dir}/{PI_WORKER_SESSION_NAME}",
        "events": f"{attempt_dir}/{PI_WORKER_EVENTS_NAME}",
        "metrics": f"{attempt_dir}/{PI_WORKER_METRICS_NAME}",
    }


def _ensure_attempt_dir(workspace: JobWorkspace, attempt_dir_ref: str) -> None:
    workspace.resolve_path(attempt_dir_ref).mkdir(parents=True, exist_ok=True)


def _contract_iteration(contract: Any) -> int:
    iteration = getattr(contract, "iteration", None)
    if not isinstance(iteration, int) or isinstance(iteration, bool) or iteration <= 0:
        raise PiWorkerError("PiWorker contract must expose a positive integer iteration")
    return iteration


def _contract_payload(contract: Any) -> dict[str, JsonValue]:
    if hasattr(contract, "to_dict"):
        payload = contract.to_dict()
    else:
        payload = {
            "job_id": getattr(contract, "job_id", ""),
            "iteration": getattr(contract, "iteration", 0),
            "current_state_ref": getattr(contract, "current_state_ref", ""),
            "next_objective": getattr(contract, "next_objective", ""),
            "why_now": getattr(contract, "why_now", ""),
            "risk_if_too_large": getattr(contract, "risk_if_too_large", ""),
            "risk_if_too_small": getattr(contract, "risk_if_too_small", ""),
            "allowed_scope": list(getattr(contract, "allowed_scope", [])),
            "visible_refs": list(getattr(contract, "visible_refs", [])),
            "expected_outputs": list(getattr(contract, "expected_outputs", [])),
            "exit_criteria": list(getattr(contract, "exit_criteria", [])),
            "stop_conditions": list(getattr(contract, "stop_conditions", [])),
            "route_plan_ref": getattr(contract, "route_plan_ref", None),
            "estimated_followups": list(getattr(contract, "estimated_followups", [])),
            "metadata": dict(getattr(contract, "metadata", {})),
        }
    return ensure_json_compatible(dict(payload))  # type: ignore[return-value]


def _read_output_result(output_path: Path, *, workspace: JobWorkspace, input_ref: str, duration_ms: int) -> PiWorkerRunResult:
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PiWorkerError(f"PiWorker output artifact is invalid JSON: {output_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PiWorkerError(f"PiWorker output artifact must be a JSON object: {output_path}")
    return _result_from_payload(payload, input_ref=input_ref, duration_ms=duration_ms, default_job_id=workspace.job_id)


def _result_from_payload(
    payload: Mapping[str, Any],
    *,
    input_ref: str,
    duration_ms: int,
    default_job_id: str | None = None,
) -> PiWorkerRunResult:
    if payload.get("schema_version") != PI_WORKER_OUTPUT_SCHEMA_VERSION:
        raise PiWorkerError("PiWorker output schema_version is unsupported")
    result = PiWorkerRunResult(
        job_id=str(payload.get("job_id") or default_job_id or ""),
        iteration=_positive_int(payload.get("iteration"), "iteration"),
        status=str(payload.get("status") or "failed"),
        produced_artifacts=_string_list(payload.get("produced_artifacts")),
        changed_refs=_string_list(payload.get("changed_refs")),
        commands_run=_string_list(payload.get("commands_run")),
        tests_run=_string_list(payload.get("tests_run")),
        failures=_string_list(payload.get("failures")),
        worker_claims=_string_list(payload.get("worker_claims")),
        verifier_evidence=_string_list(payload.get("verifier_evidence")),
        new_unknowns=_string_list(payload.get("new_unknowns")),
        recommended_next_steps=_string_list(payload.get("recommended_next_steps")),
        verification_status=str(payload.get("verification_status") or "not_run"),
        input_ref=str(payload.get("input_ref") or input_ref),
        output_ref=str(payload.get("output_ref") or ""),
        session_ref=str(payload.get("session_ref") or ""),
        events_ref=str(payload.get("events_ref") or ""),
        metrics_ref=str(payload.get("metrics_ref") or ""),
        duration_ms=_non_negative_int(payload.get("duration_ms", duration_ms), "duration_ms"),
        metrics=_json_mapping(payload.get("metrics", {}), "metrics"),
    )
    result.validate()
    return result


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    compatible = ensure_json_compatible(dict(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(compatible, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _validate_ref(value: str, field_name: str) -> None:
    try:
        validate_relative_path(value)
    except PathSecurityError as exc:
        raise PiWorkerError(f"{field_name} must be a safe relative ref: {exc}") from exc


def _validate_ref_list(value: list[str], field_name: str) -> None:
    if not isinstance(value, list):
        raise PiWorkerError(f"{field_name} must be a list of refs")
    for item in value:
        if not isinstance(item, str) or not item:
            raise PiWorkerError(f"{field_name} must contain non-empty string refs")
        _validate_ref(item, field_name)


def _validate_str_list(value: list[str], field_name: str) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise PiWorkerError(f"{field_name} must be a list of non-empty strings")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _json_mapping(value: Any, field_name: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise PiWorkerError(f"{field_name} must be a JSON object")
    return ensure_json_compatible(dict(value))  # type: ignore[return-value]


def _reject_sensitive_runtime_metadata(value: Any, path: str = "metadata") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            normalized = key_text.lower().replace("-", "_")
            if normalized in {
                "api_key",
                "apikey",
                "authorization",
                "auth",
                "bearer",
                "token",
                "access_token",
                "refresh_token",
                "secret",
                "client_secret",
                "password",
            }:
                raise PiWorkerError(
                    f"PiWorker runtime metadata must not contain sensitive key {path}.{key_text}; "
                    "use PI_WORKER_API_KEY or OPENAI_API_KEY in the process environment"
                )
            _reject_sensitive_runtime_metadata(nested, f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive_runtime_metadata(item, f"{path}[{index}]")


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PiWorkerError(f"{field_name} must be a positive integer")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PiWorkerError(f"{field_name} must be a non-negative integer")
    return value


def _process_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _format_command(command: Sequence[str]) -> str:
    return shlex.join(list(command))


def _prefixed_stream_lines(stream_name: str, text: str) -> list[str]:
    if not text:
        return [f"{stream_name}: <empty>"]
    return [f"{stream_name}: {line}" for line in text.splitlines()]


def _dedupe_refs(refs: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or not ref:
            continue
        if ref in seen:
            continue
        seen.add(ref)
        ordered.append(ref)
    return ordered
