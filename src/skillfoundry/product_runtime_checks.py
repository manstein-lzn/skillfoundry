"""Runtime command checks for product-grade SkillFoundry candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Self

from .bundle_verifier import hash_package_tree
from .schema import (
    JsonValue,
    SchemaModel,
    SchemaValidationError,
    _reject_unknown_fields,
    _require_bool,
    _require_json_mapping,
    _require_non_empty_str,
    _require_positive_int,
    _require_sha256,
    _require_str_list,
    utc_now,
)
from .security import PathSecurityError, validate_relative_path
from .workspace import JobWorkspace


PRODUCT_RUNTIME_CHECK_PLAN_REF = "package/skillfoundry.runtime_checks.json"
PRODUCT_RUNTIME_CHECK_RESULT_REF = "qa/product_runtime_check_result.json"
PRODUCT_RUNTIME_CHECK_OUTPUT_DIR = "qa/runtime_checks"
PRODUCT_RUNTIME_CHECK_VERSION = "skillfoundry.product_runtime_checks.v1"
DEFAULT_RUNTIME_CHECK_TIMEOUT_SECONDS = 30
MAX_RUNTIME_CHECK_TIMEOUT_SECONDS = 120
MAX_RUNTIME_OUTPUT_BYTES = 256 * 1024
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


def _require_safe_id(value: Any, field_name: str) -> None:
    _require_non_empty_str(value, field_name)
    if not SAFE_ID_RE.fullmatch(value):
        raise SchemaValidationError(f"{field_name} must be a safe id")


def _require_ref(value: Any, field_name: str) -> None:
    _require_non_empty_str(value, field_name)
    try:
        validate_relative_path(value)
    except PathSecurityError as exc:
        raise SchemaValidationError(f"{field_name} must be a safe relative artifact ref: {exc}") from exc


def _require_ref_list(value: Any, field_name: str) -> None:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list of artifact refs")
    for index, item in enumerate(value):
        _require_ref(item, f"{field_name}[{index}]")


def _require_command(value: Any, field_name: str) -> None:
    if not isinstance(value, list) or not value:
        raise SchemaValidationError(f"{field_name} must be a non-empty argv list")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise SchemaValidationError(f"{field_name}[{index}] must be a non-empty string")


def _require_exit_code(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be an integer exit code")


def _require_optional_exit_code(value: Any, field_name: str) -> None:
    if value is not None:
        _require_exit_code(value, field_name)


def _require_safe_json_mapping(value: Any, field_name: str) -> None:
    _require_json_mapping(value, field_name)


@dataclass
class RuntimeCheckCommand(SchemaModel):
    check_id: str
    item_id: str
    command: list[str]
    expected_exit_code: int = 0
    cwd: str = "package"
    timeout_seconds: int = DEFAULT_RUNTIME_CHECK_TIMEOUT_SECONDS
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: str = "skillfoundry.runtime_check_command.v1"

    def validate(self) -> None:
        super().validate()
        _require_safe_id(self.check_id, "check_id")
        _require_safe_id(self.item_id, "item_id")
        _require_command(self.command, "command")
        _require_exit_code(self.expected_exit_code, "expected_exit_code")
        _require_ref(self.cwd, "cwd")
        _require_positive_int(self.timeout_seconds, "timeout_seconds")
        if self.timeout_seconds > MAX_RUNTIME_CHECK_TIMEOUT_SECONDS:
            raise SchemaValidationError(f"timeout_seconds must be <= {MAX_RUNTIME_CHECK_TIMEOUT_SECONDS}")
        _require_ref_list(self.evidence_refs, "evidence_refs")
        _require_safe_json_mapping(self.metadata, "metadata")


@dataclass
class RuntimeCheckPlan(SchemaModel):
    commands: list[RuntimeCheckCommand]
    runner_version: str = PRODUCT_RUNTIME_CHECK_VERSION
    schema_version: str = "skillfoundry.runtime_check_plan.v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("RuntimeCheckPlan payload must be a JSON object")
        _reject_unknown_fields(cls, payload)
        if "commands" not in payload:
            raise SchemaValidationError("RuntimeCheckPlan missing required field(s): commands")
        if not isinstance(payload["commands"], list):
            raise SchemaValidationError("commands must be a list")
        instance = cls(
            commands=[RuntimeCheckCommand.from_dict(item) for item in payload["commands"]],
            runner_version=payload.get("runner_version", PRODUCT_RUNTIME_CHECK_VERSION),
            schema_version=payload.get("schema_version", "skillfoundry.runtime_check_plan.v1"),
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        super().validate()
        if not isinstance(self.commands, list):
            raise SchemaValidationError("commands must be a list")
        seen: set[str] = set()
        for index, command in enumerate(self.commands):
            if not isinstance(command, RuntimeCheckCommand):
                raise SchemaValidationError(f"commands[{index}] must be a RuntimeCheckCommand")
            command.validate()
            if command.check_id in seen:
                raise SchemaValidationError(f"duplicate runtime check_id: {command.check_id}")
            seen.add(command.check_id)
        _require_non_empty_str(self.runner_version, "runner_version")


@dataclass
class RuntimeCheckResultItem(SchemaModel):
    check_id: str
    item_id: str
    command: list[str]
    expected_exit_code: int
    actual_exit_code: int | None
    passed: bool
    timed_out: bool
    stdout_ref: str | None
    stderr_ref: str | None
    message: str
    evidence_refs: list[str] = field(default_factory=list)
    schema_version: str = "skillfoundry.runtime_check_result_item.v1"

    def validate(self) -> None:
        super().validate()
        _require_safe_id(self.check_id, "check_id")
        _require_safe_id(self.item_id, "item_id")
        _require_command(self.command, "command")
        _require_exit_code(self.expected_exit_code, "expected_exit_code")
        _require_optional_exit_code(self.actual_exit_code, "actual_exit_code")
        _require_bool(self.passed, "passed")
        _require_bool(self.timed_out, "timed_out")
        if self.stdout_ref is not None:
            _require_ref(self.stdout_ref, "stdout_ref")
        if self.stderr_ref is not None:
            _require_ref(self.stderr_ref, "stderr_ref")
        _require_non_empty_str(self.message, "message")
        _require_ref_list(self.evidence_refs, "evidence_refs")


@dataclass
class ProductRuntimeCheckResult(SchemaModel):
    job_id: str
    passed: bool
    plan_present: bool
    plan_ref: str
    package_hash: str
    checked_item_ids: list[str]
    missing_item_ids: list[str]
    checks: list[RuntimeCheckResultItem]
    failures: list[str]
    evidence_refs: list[str]
    runner_version: str = PRODUCT_RUNTIME_CHECK_VERSION
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "skillfoundry.product_runtime_check_result.v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("ProductRuntimeCheckResult payload must be a JSON object")
        _reject_unknown_fields(cls, payload)
        required = [
            "job_id",
            "passed",
            "plan_present",
            "plan_ref",
            "package_hash",
            "checked_item_ids",
            "missing_item_ids",
            "checks",
            "failures",
            "evidence_refs",
        ]
        missing = [name for name in required if name not in payload]
        if missing:
            raise SchemaValidationError(f"ProductRuntimeCheckResult missing required field(s): {', '.join(missing)}")
        if not isinstance(payload["checks"], list):
            raise SchemaValidationError("checks must be a list")
        instance = cls(
            job_id=payload["job_id"],
            passed=payload["passed"],
            plan_present=payload["plan_present"],
            plan_ref=payload["plan_ref"],
            package_hash=payload["package_hash"],
            checked_item_ids=payload["checked_item_ids"],
            missing_item_ids=payload["missing_item_ids"],
            checks=[RuntimeCheckResultItem.from_dict(item) for item in payload["checks"]],
            failures=payload["failures"],
            evidence_refs=payload["evidence_refs"],
            runner_version=payload.get("runner_version", PRODUCT_RUNTIME_CHECK_VERSION),
            created_at=payload.get("created_at", utc_now()),
            schema_version=payload.get("schema_version", "skillfoundry.product_runtime_check_result.v1"),
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        _require_bool(self.passed, "passed")
        _require_bool(self.plan_present, "plan_present")
        _require_ref(self.plan_ref, "plan_ref")
        _require_sha256(self.package_hash, "package_hash")
        _require_str_list(self.checked_item_ids, "checked_item_ids")
        _require_str_list(self.missing_item_ids, "missing_item_ids")
        if not isinstance(self.checks, list):
            raise SchemaValidationError("checks must be a list")
        for index, check in enumerate(self.checks):
            if not isinstance(check, RuntimeCheckResultItem):
                raise SchemaValidationError(f"checks[{index}] must be a RuntimeCheckResultItem")
            check.validate()
        _require_str_list(self.failures, "failures")
        _require_ref_list(self.evidence_refs, "evidence_refs")
        _require_non_empty_str(self.runner_version, "runner_version")
        _require_non_empty_str(self.created_at, "created_at")


class ProductRuntimeCheckRunner:
    """Execute package-declared runtime checks without shell expansion."""

    def run(
        self,
        workspace: JobWorkspace,
        *,
        required_item_ids: list[str] | None = None,
        plan: RuntimeCheckPlan | None = None,
    ) -> ProductRuntimeCheckResult:
        required = list(dict.fromkeys(required_item_ids or []))
        workspace.resolve_path("qa").mkdir(parents=True, exist_ok=True)
        output_dir = workspace.resolve_path(PRODUCT_RUNTIME_CHECK_OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        plan_present = plan is not None or _optional_workspace_path(workspace, PRODUCT_RUNTIME_CHECK_PLAN_REF).is_file()
        failures: list[str] = []
        checks: list[RuntimeCheckResultItem] = []
        evidence_refs: list[str] = []

        if plan is None:
            try:
                plan = RuntimeCheckPlan.read_json_file(
                    workspace.resolve_path(PRODUCT_RUNTIME_CHECK_PLAN_REF, must_exist=True)
                )
                evidence_refs.append(PRODUCT_RUNTIME_CHECK_PLAN_REF)
            except Exception as exc:
                missing = required
                if missing or plan_present:
                    failures.append(f"runtime_check_plan: {PRODUCT_RUNTIME_CHECK_PLAN_REF} is required: {exc}")
                result = ProductRuntimeCheckResult(
                    job_id=workspace.job_id,
                    passed=not failures,
                    plan_present=plan_present,
                    plan_ref=PRODUCT_RUNTIME_CHECK_PLAN_REF,
                    package_hash=hash_package_tree(workspace),
                    checked_item_ids=[],
                    missing_item_ids=missing,
                    checks=[],
                    failures=failures,
                    evidence_refs=[],
                    runner_version=PRODUCT_RUNTIME_CHECK_VERSION,
                )
                result.write_json_file(workspace.resolve_path(PRODUCT_RUNTIME_CHECK_RESULT_REF))
                return result

        commands = _commands_for_required_items(plan, required)
        command_item_ids = [command.item_id for command in commands]
        missing = [item_id for item_id in required if item_id not in command_item_ids]
        failures.extend(f"runtime_check_missing: {item_id}" for item_id in missing)

        for command in commands:
            result_item = self._run_command(workspace, command)
            checks.append(result_item)
            evidence_refs.extend(result_item.evidence_refs)
            if not result_item.passed:
                failures.append(f"{result_item.check_id}: {result_item.message}")

        result = ProductRuntimeCheckResult(
            job_id=workspace.job_id,
            passed=not failures,
            plan_present=plan_present,
            plan_ref=PRODUCT_RUNTIME_CHECK_PLAN_REF,
            package_hash=hash_package_tree(workspace),
            checked_item_ids=list(dict.fromkeys(command_item_ids)),
            missing_item_ids=missing,
            checks=checks,
            failures=failures,
            evidence_refs=_dedupe_refs(evidence_refs),
            runner_version=PRODUCT_RUNTIME_CHECK_VERSION,
        )
        result.write_json_file(workspace.resolve_path(PRODUCT_RUNTIME_CHECK_RESULT_REF))
        return result

    def _run_command(self, workspace: JobWorkspace, command: RuntimeCheckCommand) -> RuntimeCheckResultItem:
        stdout_ref, stderr_ref = _output_refs(command.check_id)
        stdout_path = workspace.resolve_path(stdout_ref)
        stderr_path = workspace.resolve_path(stderr_ref)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        cwd = workspace.resolve_path(command.cwd, must_exist=True)
        try:
            completed = subprocess.run(
                command.command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=command.timeout_seconds,
                shell=False,
                check=False,
            )
            stdout_path.write_text(_truncate_output(completed.stdout), encoding="utf-8")
            stderr_path.write_text(_truncate_output(completed.stderr), encoding="utf-8")
            passed = completed.returncode == command.expected_exit_code
            message = (
                f"exit code matched {command.expected_exit_code}"
                if passed
                else f"expected exit code {command.expected_exit_code}, got {completed.returncode}"
            )
            return RuntimeCheckResultItem(
                check_id=command.check_id,
                item_id=command.item_id,
                command=command.command,
                expected_exit_code=command.expected_exit_code,
                actual_exit_code=completed.returncode,
                passed=passed,
                timed_out=False,
                stdout_ref=stdout_ref,
                stderr_ref=stderr_ref,
                message=message,
                evidence_refs=_dedupe_refs([stdout_ref, stderr_ref, *command.evidence_refs]),
            )
        except subprocess.TimeoutExpired as exc:
            stdout_path.write_text(_truncate_output(exc.stdout or ""), encoding="utf-8")
            stderr_path.write_text(_truncate_output(exc.stderr or ""), encoding="utf-8")
            return RuntimeCheckResultItem(
                check_id=command.check_id,
                item_id=command.item_id,
                command=command.command,
                expected_exit_code=command.expected_exit_code,
                actual_exit_code=None,
                passed=False,
                timed_out=True,
                stdout_ref=stdout_ref,
                stderr_ref=stderr_ref,
                message=f"timed out after {command.timeout_seconds}s",
                evidence_refs=_dedupe_refs([stdout_ref, stderr_ref, *command.evidence_refs]),
            )
        except OSError as exc:
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text(str(exc) + "\n", encoding="utf-8")
            return RuntimeCheckResultItem(
                check_id=command.check_id,
                item_id=command.item_id,
                command=command.command,
                expected_exit_code=command.expected_exit_code,
                actual_exit_code=None,
                passed=False,
                timed_out=False,
                stdout_ref=stdout_ref,
                stderr_ref=stderr_ref,
                message=f"command failed to start: {exc}",
                evidence_refs=_dedupe_refs([stdout_ref, stderr_ref, *command.evidence_refs]),
            )


def run_product_runtime_checks(
    workspace: JobWorkspace,
    *,
    required_item_ids: list[str] | None = None,
) -> ProductRuntimeCheckResult:
    return ProductRuntimeCheckRunner().run(workspace, required_item_ids=required_item_ids)


def _commands_for_required_items(plan: RuntimeCheckPlan, required_item_ids: list[str]) -> list[RuntimeCheckCommand]:
    if not required_item_ids:
        return plan.commands
    required = set(required_item_ids)
    return [command for command in plan.commands if command.item_id in required]


def _optional_workspace_path(workspace: JobWorkspace, ref: str) -> Path:
    safe = validate_relative_path(ref)
    return workspace.root.joinpath(*safe.parts)


def _output_refs(check_id: str) -> tuple[str, str]:
    safe = _safe_filename(check_id)
    return (
        f"{PRODUCT_RUNTIME_CHECK_OUTPUT_DIR}/{safe}.stdout.txt",
        f"{PRODUCT_RUNTIME_CHECK_OUTPUT_DIR}/{safe}.stderr.txt",
    )


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _truncate_output(value: str | bytes) -> str:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_RUNTIME_OUTPUT_BYTES:
        return text
    return encoded[:MAX_RUNTIME_OUTPUT_BYTES].decode("utf-8", errors="replace") + "\n[truncated]\n"


def _dedupe_refs(refs: list[str]) -> list[str]:
    result: list[str] = []
    for ref in refs:
        if ref and ref not in result:
            result.append(ref)
    return result
