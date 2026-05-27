"""Workspace helpers for Front Desk requirements clarification artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import yaml

from .frontdesk_schema import (
    AcceptanceCriteriaSet,
    ConversationTurn,
    ElicitationReport,
    FeasibilityReport,
    FreezeManifest,
    FrontDeskConfig,
    SpecAuditReport,
    TaskContract,
)
from .schema import ArtifactRecord, JsonValue, SchemaModel, SchemaValidationError, ensure_json_compatible, sha256_file, utc_now
from .security import PathSecurityError, resolve_under_root, validate_relative_path
from .workspace import JobWorkspace


FRONTDESK_DIR = "frontdesk"
FRONTDESK_CREATED_BY = "skillfoundry.frontdesk_workspace"
FRONTDESK_CONVERSATION_REF = "frontdesk/conversation.jsonl"
FRONTDESK_CLARIFICATION_SUMMARY_REF = "frontdesk/clarification_summary.md"
FRONTDESK_PRODUCT_SEMANTIC_LOCK_REF = "frontdesk/product_semantic_lock.json"
FRONTDESK_PRODUCT_SEMANTIC_COVERAGE_REF = "frontdesk/product_semantic_coverage.json"
FRONTDESK_TASK_CONTRACT_REF = "frontdesk/task_contract.json"
FRONTDESK_BUDGET_REF = "frontdesk/budget.json"
FRONTDESK_RISK_REPORT_REF = "frontdesk/risk_report.json"
DEFAULT_FRONTDESK_REFS = (
    FRONTDESK_CONVERSATION_REF,
    FRONTDESK_CLARIFICATION_SUMMARY_REF,
    FRONTDESK_PRODUCT_SEMANTIC_LOCK_REF,
    FRONTDESK_PRODUCT_SEMANTIC_COVERAGE_REF,
    FRONTDESK_BUDGET_REF,
    FRONTDESK_RISK_REPORT_REF,
)


@dataclass(frozen=True)
class FrontDeskWorkspace:
    """A confined Front Desk view over an existing ``JobWorkspace``."""

    workspace: JobWorkspace

    @property
    def job_id(self) -> str:
        return self.workspace.job_id

    @property
    def root(self) -> Path:
        return self.workspace.resolve_path(FRONTDESK_DIR, must_exist=True)

    @property
    def conversation_path(self) -> Path:
        return self.resolve_path("conversation.jsonl", must_exist=True)

    def resolve_path(self, relative_path: str, *, must_exist: bool = False) -> Path:
        return _resolve_frontdesk_path(self.workspace, relative_path, must_exist=must_exist)

    def append_conversation_turn(self, turn: ConversationTurn | Mapping[str, Any]) -> ArtifactRecord:
        return append_conversation_turn(self, turn)

    def read_conversation_turns(self) -> list[ConversationTurn]:
        return read_conversation_turns(self)

    def write_artifact(
        self,
        relative_path: str,
        payload: SchemaModel | Mapping[str, Any] | list[Any] | str,
    ) -> ArtifactRecord:
        return write_frontdesk_artifact(self, relative_path, payload)


def _as_frontdesk_workspace(workspace: FrontDeskWorkspace | JobWorkspace) -> FrontDeskWorkspace:
    if isinstance(workspace, FrontDeskWorkspace):
        return workspace
    if isinstance(workspace, JobWorkspace):
        return FrontDeskWorkspace(workspace=workspace)
    raise TypeError("workspace must be a FrontDeskWorkspace or JobWorkspace")


def _frontdesk_job_ref(relative_path: str) -> str:
    safe_path = validate_relative_path(relative_path)
    parts = safe_path.parts
    if parts and parts[0] == FRONTDESK_DIR:
        parts = parts[1:]
    if not parts:
        raise PathSecurityError("frontdesk artifact path must name a file below frontdesk/")
    return PurePosixPath(FRONTDESK_DIR, *parts).as_posix()


def _resolve_frontdesk_path(workspace: JobWorkspace, relative_path: str, *, must_exist: bool = False) -> Path:
    job_ref = _frontdesk_job_ref(relative_path)
    return workspace.resolve_path(job_ref, must_exist=must_exist)


def _ensure_frontdesk_parent(workspace: JobWorkspace, job_ref: str) -> Path:
    parent_ref = PurePosixPath(job_ref).parent.as_posix()
    parent_path = resolve_under_root(workspace.root, parent_ref, must_exist=False)
    parent_path.mkdir(parents=True, exist_ok=True)
    return parent_path


def _artifact_record_for_file(workspace: JobWorkspace, job_ref: str) -> ArtifactRecord:
    artifact_path = workspace.resolve_path(job_ref, must_exist=True)
    return ArtifactRecord(
        artifact_id=f"{workspace.job_id}:{job_ref.replace('/', ':')}",
        path=job_ref,
        kind="frontdesk_artifact",
        sha256=sha256_file(artifact_path),
        created_by=FRONTDESK_CREATED_BY,
        created_at=utc_now(),
        job_id=workspace.job_id,
        attempt_id=None,
        locked=False,
    )


def _upsert_manifest_record(workspace: JobWorkspace, job_ref: str) -> ArtifactRecord:
    record = _artifact_record_for_file(workspace, job_ref)
    manifest = workspace.read_manifest()
    updated: list[ArtifactRecord] = []
    for existing in manifest.artifacts:
        if existing.path == record.path and existing.locked:
            raise ValueError(f"cannot replace locked manifest record for {record.path}")
        if existing.artifact_id == record.artifact_id and existing.locked:
            raise ValueError(f"cannot replace locked manifest record {record.artifact_id}")
        if existing.path == record.path or existing.artifact_id == record.artifact_id:
            continue
        updated.append(existing)
    updated.append(record)
    manifest.artifacts = updated
    workspace.write_manifest(manifest)
    workspace.check_locked_inputs()
    return record


def _write_json_file(path: Path, payload: Any) -> None:
    compatible = ensure_json_compatible(payload)
    text = json.dumps(compatible, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8")


def _write_payload(path: Path, payload: SchemaModel | Mapping[str, Any] | list[Any] | str) -> None:
    suffix = path.suffix.lower()
    if isinstance(payload, SchemaModel):
        if suffix in {".yaml", ".yml"}:
            payload.write_yaml_file(path)
        else:
            payload.write_json_file(path)
        return
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
        return
    compatible = ensure_json_compatible(payload)
    if suffix in {".yaml", ".yml"}:
        path.write_text(yaml.safe_dump(compatible, sort_keys=True, allow_unicode=True), encoding="utf-8")
    else:
        _write_json_file(path, compatible)


def initialize_frontdesk_workspace(
    workspace: JobWorkspace,
    *,
    config: FrontDeskConfig | None = None,
    overwrite: bool = False,
) -> FrontDeskWorkspace:
    """Create ``frontdesk/`` files inside an existing job workspace and register them."""

    frontdesk_dir = workspace.resolve_path(FRONTDESK_DIR)
    frontdesk_dir.mkdir(parents=True, exist_ok=True)
    config = config or FrontDeskConfig()
    config.validate()

    defaults: dict[str, SchemaModel | dict[str, JsonValue] | str] = {
        FRONTDESK_CONVERSATION_REF: "",
        FRONTDESK_CLARIFICATION_SUMMARY_REF: (
            "# Clarification Summary\n\n"
            "No Front Desk clarification summary has been generated for this workspace yet.\n"
        ),
        FRONTDESK_PRODUCT_SEMANTIC_LOCK_REF: {
            "schema_version": "skillfoundry.product_semantic_lock.placeholder.v1",
            "status": "not_started",
        },
        FRONTDESK_PRODUCT_SEMANTIC_COVERAGE_REF: {
            "schema_version": "skillfoundry.product_semantic_coverage.placeholder.v1",
            "status": "not_started",
        },
        FRONTDESK_BUDGET_REF: config,
        FRONTDESK_RISK_REPORT_REF: {
            "schema_version": "skillfoundry.frontdesk_risk_report.v1",
            "risk_flags": [],
            "redaction_status": "not_started",
        },
    }

    for job_ref, payload in defaults.items():
        path = workspace.resolve_path(job_ref)
        if overwrite or not path.exists():
            _write_payload(path, payload)
        _upsert_manifest_record(workspace, job_ref)

    workspace.check_locked_inputs()
    return FrontDeskWorkspace(workspace=workspace)


def append_conversation_turn(
    workspace: FrontDeskWorkspace | JobWorkspace,
    turn: ConversationTurn | Mapping[str, Any],
) -> ArtifactRecord:
    """Append one validated conversation turn to ``frontdesk/conversation.jsonl``."""

    frontdesk = _as_frontdesk_workspace(workspace)
    if isinstance(turn, Mapping):
        turn = ConversationTurn.from_dict(turn)
    if not isinstance(turn, ConversationTurn):
        raise SchemaValidationError("turn must be a ConversationTurn or JSON object")
    turn.validate()

    path = frontdesk.conversation_path
    with path.open("a", encoding="utf-8") as handle:
        handle.write(turn.to_json(indent=None) + "\n")
    return _upsert_manifest_record(frontdesk.workspace, FRONTDESK_CONVERSATION_REF)


def read_conversation_turns(workspace: FrontDeskWorkspace | JobWorkspace) -> list[ConversationTurn]:
    """Read conversation turns from ``frontdesk/conversation.jsonl`` in append order."""

    frontdesk = _as_frontdesk_workspace(workspace)
    turns: list[ConversationTurn] = []
    for line_number, line in enumerate(frontdesk.conversation_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            turns.append(ConversationTurn.from_json(stripped))
        except SchemaValidationError as exc:
            raise SchemaValidationError(f"conversation.jsonl line {line_number} is invalid: {exc}") from exc
    return turns


def write_frontdesk_artifact(
    workspace: FrontDeskWorkspace | JobWorkspace,
    relative_path: str,
    payload: SchemaModel | Mapping[str, Any] | list[Any] | str,
) -> ArtifactRecord:
    """Write a file below ``frontdesk/`` and upsert its artifact manifest record."""

    frontdesk = _as_frontdesk_workspace(workspace)
    job_ref = _frontdesk_job_ref(relative_path)
    _ensure_frontdesk_parent(frontdesk.workspace, job_ref)
    path = frontdesk.workspace.resolve_path(job_ref)
    _write_payload(path, payload)
    return _upsert_manifest_record(frontdesk.workspace, job_ref)


def write_elicitation_report(
    workspace: FrontDeskWorkspace | JobWorkspace,
    report: ElicitationReport,
    *,
    sequence: int = 1,
) -> ArtifactRecord:
    if sequence <= 0:
        raise ValueError("sequence must be positive")
    return write_frontdesk_artifact(workspace, f"elicitation_report_{sequence:03d}.json", report)


def write_spec_audit_report(
    workspace: FrontDeskWorkspace | JobWorkspace,
    report: SpecAuditReport,
    *,
    sequence: int = 1,
) -> ArtifactRecord:
    if sequence <= 0:
        raise ValueError("sequence must be positive")
    return write_frontdesk_artifact(workspace, f"spec_audit_report_{sequence:03d}.json", report)


def write_acceptance_criteria(
    workspace: FrontDeskWorkspace | JobWorkspace,
    criteria: AcceptanceCriteriaSet,
    *,
    relative_path: str = "acceptance_criteria.yaml",
) -> ArtifactRecord:
    return write_frontdesk_artifact(workspace, relative_path, criteria)


def write_feasibility_report(
    workspace: FrontDeskWorkspace | JobWorkspace,
    report: FeasibilityReport,
    *,
    relative_path: str = "feasibility_report.json",
) -> ArtifactRecord:
    return write_frontdesk_artifact(workspace, relative_path, report)


def write_task_contract(
    workspace: FrontDeskWorkspace | JobWorkspace,
    contract: TaskContract,
    *,
    relative_path: str = "task_contract.json",
) -> ArtifactRecord:
    return write_frontdesk_artifact(workspace, relative_path, contract)


def write_freeze_manifest(
    workspace: FrontDeskWorkspace | JobWorkspace,
    manifest: FreezeManifest,
    *,
    relative_path: str = "freeze_manifest.json",
) -> ArtifactRecord:
    return write_frontdesk_artifact(workspace, relative_path, manifest)
