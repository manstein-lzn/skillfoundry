"""Workspace helpers for adaptive steering artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .adaptive import (
    CapabilityStateEstimate,
    DecisionLedger,
    DecisionRecord,
    NextStepContract,
    ObservationReport,
    RoutePlan,
    StateCorrection,
)
from .schema import ArtifactRecord, SchemaModel, sha256_file, utc_now
from .security import PathSecurityError, resolve_under_root, validate_relative_path
from .workspace import JobWorkspace


ADAPTIVE_DIR = "adaptive"
ADAPTIVE_CREATED_BY = "skillfoundry.adaptive_workspace"
ADAPTIVE_CAPABILITY_STATE_REF = "adaptive/capability_state.json"
ADAPTIVE_DECISION_LEDGER_REF = "adaptive/decision_ledger.json"


@dataclass(frozen=True)
class AdaptiveWorkspace:
    """A confined adaptive steering view over an existing ``JobWorkspace``."""

    workspace: JobWorkspace

    @property
    def job_id(self) -> str:
        return self.workspace.job_id

    @property
    def root(self) -> Path:
        return self.workspace.resolve_path(ADAPTIVE_DIR, must_exist=True)

    def resolve_path(self, relative_path: str, *, must_exist: bool = False) -> Path:
        return _resolve_adaptive_path(self.workspace, relative_path, must_exist=must_exist)


def _as_adaptive_workspace(workspace: AdaptiveWorkspace | JobWorkspace) -> AdaptiveWorkspace:
    if isinstance(workspace, AdaptiveWorkspace):
        return workspace
    if isinstance(workspace, JobWorkspace):
        return AdaptiveWorkspace(workspace=workspace)
    raise TypeError("workspace must be an AdaptiveWorkspace or JobWorkspace")


def _validate_iteration(iteration: int) -> None:
    if not isinstance(iteration, int) or isinstance(iteration, bool) or iteration < 0:
        raise ValueError("iteration must be a non-negative integer")


def adaptive_contract_ref(iteration: int) -> str:
    _validate_iteration(iteration)
    return f"{ADAPTIVE_DIR}/next_step_contract_{iteration:03d}.json"


def adaptive_route_plan_ref(iteration: int) -> str:
    _validate_iteration(iteration)
    return f"{ADAPTIVE_DIR}/route_plan_{iteration:03d}.json"


def adaptive_observation_ref(iteration: int) -> str:
    _validate_iteration(iteration)
    return f"{ADAPTIVE_DIR}/observation_report_{iteration:03d}.json"


def adaptive_correction_ref(iteration: int) -> str:
    _validate_iteration(iteration)
    return f"{ADAPTIVE_DIR}/state_correction_{iteration:03d}.json"


def _adaptive_job_ref(relative_path: str) -> str:
    safe_path = validate_relative_path(relative_path)
    parts = safe_path.parts
    if parts and parts[0] == ADAPTIVE_DIR:
        parts = parts[1:]
    if not parts:
        raise PathSecurityError("adaptive artifact path must name a file below adaptive/")
    return PurePosixPath(ADAPTIVE_DIR, *parts).as_posix()


def _resolve_adaptive_path(workspace: JobWorkspace, relative_path: str, *, must_exist: bool = False) -> Path:
    job_ref = _adaptive_job_ref(relative_path)
    return workspace.resolve_path(job_ref, must_exist=must_exist)


def _ensure_adaptive_parent(workspace: JobWorkspace, job_ref: str) -> None:
    parent_ref = PurePosixPath(job_ref).parent.as_posix()
    parent_path = resolve_under_root(workspace.root, parent_ref, must_exist=False)
    parent_path.mkdir(parents=True, exist_ok=True)


def _artifact_record_for_file(workspace: JobWorkspace, job_ref: str) -> ArtifactRecord:
    artifact_path = workspace.resolve_path(job_ref, must_exist=True)
    return ArtifactRecord(
        artifact_id=f"{workspace.job_id}:{job_ref.replace('/', ':')}",
        path=job_ref,
        kind="adaptive_artifact",
        sha256=sha256_file(artifact_path),
        created_by=ADAPTIVE_CREATED_BY,
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


def _write_schema_artifact(workspace: AdaptiveWorkspace | JobWorkspace, job_ref: str, payload: SchemaModel) -> ArtifactRecord:
    adaptive = _as_adaptive_workspace(workspace)
    if not isinstance(payload, SchemaModel):
        raise TypeError("adaptive artifacts must be schema objects")
    _ensure_adaptive_parent(adaptive.workspace, job_ref)
    path = adaptive.workspace.resolve_path(job_ref)
    payload.write_json_file(path)
    return _upsert_manifest_record(adaptive.workspace, job_ref)


def initialize_adaptive_workspace(workspace: JobWorkspace, *, overwrite: bool = False) -> AdaptiveWorkspace:
    """Create ``adaptive/`` files inside an existing job workspace and register them."""

    adaptive_dir = workspace.resolve_path(ADAPTIVE_DIR)
    adaptive_dir.mkdir(parents=True, exist_ok=True)
    workspace.resolve_path(f"{ADAPTIVE_DIR}/attempts").mkdir(parents=True, exist_ok=True)
    adaptive = AdaptiveWorkspace(workspace=workspace)

    ledger_path = workspace.resolve_path(ADAPTIVE_DECISION_LEDGER_REF)
    if overwrite or not ledger_path.exists():
        DecisionLedger(job_id=workspace.job_id).write_json_file(ledger_path)
    _upsert_manifest_record(workspace, ADAPTIVE_DECISION_LEDGER_REF)
    workspace.check_locked_inputs()
    return adaptive


def write_capability_state_estimate(
    workspace: AdaptiveWorkspace | JobWorkspace,
    state: CapabilityStateEstimate,
) -> ArtifactRecord:
    """Write the latest capability state estimate."""

    return _write_schema_artifact(workspace, ADAPTIVE_CAPABILITY_STATE_REF, state)


def read_capability_state_estimate(workspace: AdaptiveWorkspace | JobWorkspace) -> CapabilityStateEstimate:
    adaptive = _as_adaptive_workspace(workspace)
    return CapabilityStateEstimate.read_json_file(adaptive.workspace.resolve_path(ADAPTIVE_CAPABILITY_STATE_REF, must_exist=True))


def write_route_plan(
    workspace: AdaptiveWorkspace | JobWorkspace,
    plan: RoutePlan,
) -> ArtifactRecord:
    """Write a route plan under its stable iteration ref."""

    return _write_schema_artifact(workspace, adaptive_route_plan_ref(plan.iteration), plan)


def read_route_plan(workspace: AdaptiveWorkspace | JobWorkspace, iteration: int) -> RoutePlan:
    adaptive = _as_adaptive_workspace(workspace)
    return RoutePlan.read_json_file(adaptive.workspace.resolve_path(adaptive_route_plan_ref(iteration), must_exist=True))


def write_next_step_contract(
    workspace: AdaptiveWorkspace | JobWorkspace,
    contract: NextStepContract,
) -> ArtifactRecord:
    """Write a next-step contract under its stable iteration ref."""

    return _write_schema_artifact(workspace, adaptive_contract_ref(contract.iteration), contract)


def read_next_step_contract(workspace: AdaptiveWorkspace | JobWorkspace, iteration: int) -> NextStepContract:
    adaptive = _as_adaptive_workspace(workspace)
    return NextStepContract.read_json_file(adaptive.workspace.resolve_path(adaptive_contract_ref(iteration), must_exist=True))


def write_observation_report(
    workspace: AdaptiveWorkspace | JobWorkspace,
    report: ObservationReport,
) -> ArtifactRecord:
    """Write an observation report under its stable iteration ref."""

    return _write_schema_artifact(workspace, adaptive_observation_ref(report.iteration), report)


def read_observation_report(workspace: AdaptiveWorkspace | JobWorkspace, iteration: int) -> ObservationReport:
    adaptive = _as_adaptive_workspace(workspace)
    return ObservationReport.read_json_file(adaptive.workspace.resolve_path(adaptive_observation_ref(iteration), must_exist=True))


def write_state_correction(
    workspace: AdaptiveWorkspace | JobWorkspace,
    correction: StateCorrection,
) -> ArtifactRecord:
    """Write a state correction under its stable iteration ref."""

    return _write_schema_artifact(workspace, adaptive_correction_ref(correction.iteration), correction)


def read_state_correction(workspace: AdaptiveWorkspace | JobWorkspace, iteration: int) -> StateCorrection:
    adaptive = _as_adaptive_workspace(workspace)
    return StateCorrection.read_json_file(adaptive.workspace.resolve_path(adaptive_correction_ref(iteration), must_exist=True))


def read_decision_ledger(workspace: AdaptiveWorkspace | JobWorkspace) -> DecisionLedger:
    adaptive = _as_adaptive_workspace(workspace)
    return DecisionLedger.read_json_file(adaptive.workspace.resolve_path(ADAPTIVE_DECISION_LEDGER_REF, must_exist=True))


def append_decision_record(
    workspace: AdaptiveWorkspace | JobWorkspace,
    decision: DecisionRecord,
) -> ArtifactRecord:
    """Append a decision to ``adaptive/decision_ledger.json`` and register the updated artifact."""

    adaptive = _as_adaptive_workspace(workspace)
    ledger_path = adaptive.workspace.resolve_path(ADAPTIVE_DECISION_LEDGER_REF)
    if ledger_path.exists():
        ledger = DecisionLedger.read_json_file(ledger_path)
    else:
        ledger = DecisionLedger(job_id=adaptive.job_id)

    updated = DecisionLedger(
        job_id=adaptive.job_id,
        decisions=[*ledger.decisions, decision],
        metadata=ledger.metadata,
        schema_version=ledger.schema_version,
    )
    updated.validate()
    _ensure_adaptive_parent(adaptive.workspace, ADAPTIVE_DECISION_LEDGER_REF)
    updated.write_json_file(ledger_path)
    return _upsert_manifest_record(adaptive.workspace, ADAPTIVE_DECISION_LEDGER_REF)
