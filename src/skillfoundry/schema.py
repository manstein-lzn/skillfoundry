"""Core SkillFoundry schema objects and deterministic serialization."""

from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, fields
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, ClassVar, Mapping, Self

import yaml


JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SchemaValidationError(ValueError):
    """Raised when a schema payload is missing required or JSON-safe values."""


def utc_now() -> str:
    """Return a compact UTC timestamp suitable for persisted schema fields."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_json_compatible(value: Any, path: str = "$") -> JsonValue:
    """Validate and return a value that can be serialized as strict JSON."""

    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SchemaValidationError(f"{path} must be a finite float")
        return value
    if isinstance(value, list):
        return [ensure_json_compatible(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, tuple):
        return [ensure_json_compatible(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise SchemaValidationError(f"{path} contains a non-string key")
            result[key] = ensure_json_compatible(item, f"{path}.{key}")
        return result
    raise SchemaValidationError(f"{path} is not JSON-compatible: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic JSON bytes for hashing contracts and artifacts."""

    if isinstance(value, SchemaModel):
        value = value.to_dict()
    compatible = ensure_json_compatible(value)
    return json.dumps(
        compatible,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_non_empty_str(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")


def _require_str_list(value: Any, field_name: str) -> None:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list of strings")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise SchemaValidationError(f"{field_name}[{index}] must be a non-empty string")


def _require_json_mapping(value: Any, field_name: str) -> None:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{field_name} must be a JSON object")
    ensure_json_compatible(value, field_name)


def _require_bool(value: Any, field_name: str) -> None:
    if not isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be a boolean")


def _require_non_negative_int(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SchemaValidationError(f"{field_name} must be a non-negative integer")


def _require_positive_int(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SchemaValidationError(f"{field_name} must be a positive integer")


def _require_sha256(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise SchemaValidationError(f"{field_name} must be a lowercase sha256 hex digest")


def _require_hash_mapping(value: Any, field_name: str) -> None:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{field_name} must be a JSON object")
    for key, item in value.items():
        _require_non_empty_str(key, f"{field_name} key")
        _require_sha256(item, f"{field_name}.{key}")


def _reject_unknown_fields(cls: type["SchemaModel"], payload: Mapping[str, Any]) -> None:
    known = {item.name for item in fields(cls) if item.init}
    unknown = set(payload) - known
    if unknown:
        names = ", ".join(sorted(unknown))
        raise SchemaValidationError(f"{cls.__name__} has unknown field(s): {names}")


@dataclass
class SchemaModel:
    """Base class for dataclass-backed schema records."""

    SCHEMA_VERSION: ClassVar[str] = "skillfoundry.schema.v1"

    def validate(self) -> None:
        _require_non_empty_str(getattr(self, "schema_version"), "schema_version")

    def to_dict(self) -> dict[str, JsonValue]:
        self.validate()
        return ensure_json_compatible(asdict(self))  # type: ignore[return-value]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError(f"{cls.__name__} payload must be a JSON object")
        _reject_unknown_fields(cls, payload)
        kwargs: dict[str, Any] = {}
        missing: list[str] = []
        for item in fields(cls):
            if not item.init:
                continue
            if item.name in payload:
                kwargs[item.name] = payload[item.name]
            elif item.default is MISSING and item.default_factory is MISSING:
                missing.append(item.name)
        if missing:
            raise SchemaValidationError(f"{cls.__name__} missing required field(s): {', '.join(missing)}")
        instance = cls(**kwargs)
        instance.validate()
        return instance

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=indent, ensure_ascii=False, allow_nan=False)

    @classmethod
    def from_json(cls, text: str) -> Self:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SchemaValidationError(f"{cls.__name__} JSON is invalid: {exc}") from exc
        return cls.from_dict(payload)

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=True, allow_unicode=True)

    @classmethod
    def from_yaml(cls, text: str) -> Self:
        payload = yaml.safe_load(text)
        if payload is None:
            raise SchemaValidationError(f"{cls.__name__} YAML is empty")
        return cls.from_dict(payload)

    def write_json_file(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json() + "\n", encoding="utf-8")

    @classmethod
    def read_json_file(cls, path: str | Path) -> Self:
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    def write_yaml_file(self, path: str | Path) -> None:
        Path(path).write_text(self.to_yaml(), encoding="utf-8")

    @classmethod
    def read_yaml_file(cls, path: str | Path) -> Self:
        return cls.from_yaml(Path(path).read_text(encoding="utf-8"))


@dataclass
class SkillSpec(SchemaModel):
    skill_id: str
    title: str
    description: str
    trigger_scenarios: list[str]
    non_trigger_scenarios: list[str]
    required_inputs: list[str]
    expected_outputs: list[str]
    constraints: list[str]
    acceptance_criteria: list[str]
    reference_materials: list[str]
    security_notes: list[str]
    schema_version: str = "skillfoundry.skill_spec.v1"

    def validate(self) -> None:
        super().validate()
        for name in ("skill_id", "title", "description"):
            _require_non_empty_str(getattr(self, name), name)
        for name in (
            "trigger_scenarios",
            "non_trigger_scenarios",
            "required_inputs",
            "expected_outputs",
            "constraints",
            "acceptance_criteria",
            "reference_materials",
            "security_notes",
        ):
            _require_str_list(getattr(self, name), name)


@dataclass
class BuildContract(SchemaModel):
    job_id: str
    skill_spec_ref: str
    verification_spec_ref: str
    workspace_root: str
    allowed_write_paths: list[str]
    blocked_paths: list[str]
    timeout_seconds: int
    attempt_limit: int
    required_artifacts: list[str]
    locked_input_hashes: dict[str, str]
    schema_version: str = "skillfoundry.build_contract.v1"

    def validate(self) -> None:
        super().validate()
        for name in ("job_id", "skill_spec_ref", "verification_spec_ref", "workspace_root"):
            _require_non_empty_str(getattr(self, name), name)
        for name in ("allowed_write_paths", "blocked_paths", "required_artifacts"):
            _require_str_list(getattr(self, name), name)
        _require_positive_int(self.timeout_seconds, "timeout_seconds")
        _require_positive_int(self.attempt_limit, "attempt_limit")
        _require_hash_mapping(self.locked_input_hashes, "locked_input_hashes")


@dataclass
class VerificationSpec(SchemaModel):
    spec_id: str
    job_id: str
    required_checks: list[str]
    artifact_requirements: list[str]
    path_policies: list[str]
    acceptance_criteria: list[str]
    verifier_version: str
    schema_version: str = "skillfoundry.verification_spec.v1"

    def validate(self) -> None:
        super().validate()
        for name in ("spec_id", "job_id", "verifier_version"):
            _require_non_empty_str(getattr(self, name), name)
        for name in ("required_checks", "artifact_requirements", "path_policies", "acceptance_criteria"):
            _require_str_list(getattr(self, name), name)


@dataclass
class WorkerInvocation(SchemaModel):
    invocation_id: str
    job_id: str
    attempt_id: str
    worker_type: str
    adapter_version: str
    input_manifest_hash: str
    workspace_hash_before: str
    workspace_hash_after: str
    started_at: str
    finished_at: str
    duration_ms: int
    usage_available: bool
    usage_unavailable_reason: str | None
    transcript_ref: str
    execution_report_ref: str
    diff_ref: str
    exit_status: str
    schema_version: str = "skillfoundry.worker_invocation.v1"

    def validate(self) -> None:
        super().validate()
        for name in (
            "invocation_id",
            "job_id",
            "attempt_id",
            "worker_type",
            "adapter_version",
            "started_at",
            "finished_at",
            "transcript_ref",
            "execution_report_ref",
            "diff_ref",
            "exit_status",
        ):
            _require_non_empty_str(getattr(self, name), name)
        for name in ("input_manifest_hash", "workspace_hash_before", "workspace_hash_after"):
            _require_sha256(getattr(self, name), name)
        _require_non_negative_int(self.duration_ms, "duration_ms")
        _require_bool(self.usage_available, "usage_available")
        if not self.usage_available:
            _require_non_empty_str(self.usage_unavailable_reason, "usage_unavailable_reason")


@dataclass
class ExecutionReport(SchemaModel):
    report_id: str
    invocation_id: str
    job_id: str
    attempt_id: str
    status: str
    started_at: str
    finished_at: str
    duration_ms: int
    exit_status: str
    summary: str
    artifacts: list[str]
    failures: list[str]
    schema_version: str = "skillfoundry.execution_report.v1"

    def validate(self) -> None:
        super().validate()
        for name in (
            "report_id",
            "invocation_id",
            "job_id",
            "attempt_id",
            "status",
            "started_at",
            "finished_at",
            "exit_status",
            "summary",
        ):
            _require_non_empty_str(getattr(self, name), name)
        _require_non_negative_int(self.duration_ms, "duration_ms")
        _require_str_list(self.artifacts, "artifacts")
        _require_str_list(self.failures, "failures")


@dataclass
class VerificationResult(SchemaModel):
    result_id: str
    job_id: str
    package_hash: str
    verification_spec_hash: str
    passed: bool
    checks: list[dict[str, JsonValue]]
    failures: list[str]
    evidence_refs: list[str]
    verifier_version: str
    created_at: str
    llm_judge_ref: str | None = None
    schema_version: str = "skillfoundry.verification_result.v1"

    def validate(self) -> None:
        super().validate()
        for name in ("result_id", "job_id", "verifier_version", "created_at"):
            _require_non_empty_str(getattr(self, name), name)
        _require_sha256(self.package_hash, "package_hash")
        _require_sha256(self.verification_spec_hash, "verification_spec_hash")
        _require_bool(self.passed, "passed")
        if not isinstance(self.checks, list):
            raise SchemaValidationError("checks must be a list of JSON objects")
        for index, check in enumerate(self.checks):
            _require_json_mapping(check, f"checks[{index}]")
        _require_str_list(self.failures, "failures")
        _require_str_list(self.evidence_refs, "evidence_refs")
        if self.llm_judge_ref is not None:
            _require_non_empty_str(self.llm_judge_ref, "llm_judge_ref")


@dataclass
class RepairAttempt(SchemaModel):
    attempt_id: str
    job_id: str
    based_on_result_id: str
    repair_instructions_ref: str
    status: str
    created_at: str
    input_hashes: dict[str, str]
    output_refs: list[str]
    schema_version: str = "skillfoundry.repair_attempt.v1"

    def validate(self) -> None:
        super().validate()
        for name in (
            "attempt_id",
            "job_id",
            "based_on_result_id",
            "repair_instructions_ref",
            "status",
            "created_at",
        ):
            _require_non_empty_str(getattr(self, name), name)
        _require_hash_mapping(self.input_hashes, "input_hashes")
        _require_str_list(self.output_refs, "output_refs")


@dataclass
class ArtifactRecord(SchemaModel):
    artifact_id: str
    path: str
    kind: str
    sha256: str
    created_by: str
    created_at: str
    job_id: str
    attempt_id: str | None
    locked: bool
    schema_version: str = "skillfoundry.artifact_record.v1"

    def validate(self) -> None:
        super().validate()
        for name in ("artifact_id", "path", "kind", "created_by", "created_at", "job_id"):
            _require_non_empty_str(getattr(self, name), name)
        _require_sha256(self.sha256, "sha256")
        if self.attempt_id is not None:
            _require_non_empty_str(self.attempt_id, "attempt_id")
        _require_bool(self.locked, "locked")


@dataclass
class ArtifactManifest(SchemaModel):
    job_id: str
    artifacts: list[ArtifactRecord]
    created_at: str
    schema_version: str = "skillfoundry.artifact_manifest.v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("ArtifactManifest payload must be a JSON object")
        _reject_unknown_fields(cls, payload)
        missing = [name for name in ("job_id", "artifacts", "created_at") if name not in payload]
        if missing:
            raise SchemaValidationError(f"ArtifactManifest missing required field(s): {', '.join(missing)}")
        artifacts = payload["artifacts"]
        if not isinstance(artifacts, list):
            raise SchemaValidationError("artifacts must be a list")
        records = [ArtifactRecord.from_dict(item) for item in artifacts]
        instance = cls(
            job_id=payload["job_id"],
            artifacts=records,
            created_at=payload["created_at"],
            schema_version=payload.get("schema_version", "skillfoundry.artifact_manifest.v1"),
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        if not isinstance(self.artifacts, list):
            raise SchemaValidationError("artifacts must be a list")
        seen: set[str] = set()
        for index, record in enumerate(self.artifacts):
            if not isinstance(record, ArtifactRecord):
                raise SchemaValidationError(f"artifacts[{index}] must be an ArtifactRecord")
            record.validate()
            if record.artifact_id in seen:
                raise SchemaValidationError(f"duplicate artifact_id: {record.artifact_id}")
            seen.add(record.artifact_id)
        _require_non_empty_str(self.created_at, "created_at")

    def locked_records(self) -> list[ArtifactRecord]:
        return [record for record in self.artifacts if record.locked]

    def record_for_path(self, relative_path: str) -> ArtifactRecord | None:
        for record in self.artifacts:
            if record.path == relative_path:
                return record
        return None


@dataclass
class RegistryEntry(SchemaModel):
    skill_id: str
    version: str
    package_path: str
    package_hash: str
    build_job_id: str
    worker_invocation_id: str
    verification_spec_hash: str
    verification_result_hash: str
    artifact_manifest_hash: str
    verifier_version: str
    approval_status: str
    review_status: str
    created_at: str
    provenance: dict[str, JsonValue]
    quarantine_status: str
    schema_version: str = "skillfoundry.registry_entry.v1"

    def validate(self) -> None:
        super().validate()
        for name in (
            "skill_id",
            "version",
            "package_path",
            "build_job_id",
            "worker_invocation_id",
            "verifier_version",
            "approval_status",
            "review_status",
            "created_at",
            "quarantine_status",
        ):
            _require_non_empty_str(getattr(self, name), name)
        for name in ("package_hash", "verification_spec_hash", "verification_result_hash", "artifact_manifest_hash"):
            _require_sha256(getattr(self, name), name)
        _require_json_mapping(self.provenance, "provenance")


@dataclass
class ApprovalRecord(SchemaModel):
    approval_id: str
    registry_entry_ref: str
    status: str
    reviewer: str
    reason: str
    created_at: str
    evidence_refs: list[str]
    schema_version: str = "skillfoundry.approval_record.v1"

    def validate(self) -> None:
        super().validate()
        for name in ("approval_id", "registry_entry_ref", "status", "reviewer", "reason", "created_at"):
            _require_non_empty_str(getattr(self, name), name)
        _require_str_list(self.evidence_refs, "evidence_refs")
