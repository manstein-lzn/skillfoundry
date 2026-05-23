"""Adapter for routing frozen FrontDesk jobs into the vNext factory."""

from __future__ import annotations

from pathlib import Path

from skillfoundry.frontdesk_schema import FreezeManifest, FrontDeskState
from skillfoundry.registry import DEFAULT_REGISTRY_VERSION
from skillfoundry.schema import SchemaValidationError, sha256_file
from skillfoundry.security import PathSecurityError
from skillfoundry.workspace import JobWorkspace

from ..config import ForgeUnitSkillFoundryError
from ..engine import ForgeUnitSkillFactoryEngine
from ..product import ForgeUnitSkillFactoryResult
from .workspace import run_existing_workspace_skill_factory


FRONTDESK_STATE_REF = "frontdesk/state.json"


def run_frozen_frontdesk_skill_factory(
    workspace: JobWorkspace,
    *,
    registry_path: str | Path,
    command: str,
    repair_command: str | None = None,
    attempt_limit: int = 2,
    version: str = DEFAULT_REGISTRY_VERSION,
    created_at: str | None = None,
    engine: ForgeUnitSkillFactoryEngine | None = None,
) -> ForgeUnitSkillFactoryResult:
    """Run vNext only after FrontDesk has frozen a route_to_build job."""

    if not isinstance(workspace, JobWorkspace):
        raise ForgeUnitSkillFoundryError("workspace must be a JobWorkspace")
    workspace.check_locked_inputs()
    state = _read_frontdesk_state(workspace)
    _require_frozen_route_to_build(workspace, state)
    return run_existing_workspace_skill_factory(
        workspace,
        registry_path=registry_path,
        command=command,
        repair_command=repair_command,
        attempt_limit=attempt_limit,
        version=version,
        created_at=created_at,
        engine=engine,
    )


def _read_frontdesk_state(workspace: JobWorkspace) -> FrontDeskState:
    try:
        state_path = workspace.resolve_path(FRONTDESK_STATE_REF, must_exist=True)
        return FrontDeskState.read_json_file(state_path)
    except (OSError, PathSecurityError, SchemaValidationError) as exc:
        raise ForgeUnitSkillFoundryError(f"frontdesk state is missing or invalid: {exc}") from exc


def _require_frozen_route_to_build(workspace: JobWorkspace, state: FrontDeskState) -> None:
    if state.job_id != workspace.job_id:
        raise ForgeUnitSkillFoundryError(
            f"frontdesk state job_id must be {workspace.job_id!r}, got {state.job_id!r}"
        )
    if state.readiness != "frozen" or state.next_action != "route_to_build":
        raise ForgeUnitSkillFoundryError("frontdesk job must be frozen with next_action route_to_build")
    if not state.freeze_manifest_ref:
        raise ForgeUnitSkillFoundryError("frozen frontdesk job must include freeze_manifest_ref")
    freeze_manifest = _read_freeze_manifest(workspace, state.freeze_manifest_ref)
    _require_freeze_manifest_artifacts(workspace, freeze_manifest)


def _read_freeze_manifest(workspace: JobWorkspace, freeze_manifest_ref: str) -> FreezeManifest:
    try:
        manifest_path = workspace.resolve_path(freeze_manifest_ref, must_exist=True)
        return FreezeManifest.read_json_file(manifest_path)
    except (OSError, PathSecurityError, SchemaValidationError) as exc:
        raise ForgeUnitSkillFoundryError(f"frontdesk freeze manifest is missing or invalid: {exc}") from exc


def _require_freeze_manifest_artifacts(workspace: JobWorkspace, freeze_manifest: FreezeManifest) -> None:
    for ref in _freeze_manifest_required_refs(freeze_manifest):
        try:
            workspace.resolve_path(ref, must_exist=True)
        except (OSError, PathSecurityError) as exc:
            raise ForgeUnitSkillFoundryError(
                f"frontdesk freeze manifest artifact is missing or unsafe: {ref}"
            ) from exc
    for ref, expected_hash in freeze_manifest.artifact_hashes.items():
        try:
            actual_hash = sha256_file(workspace.resolve_path(ref, must_exist=True))
        except (OSError, PathSecurityError) as exc:
            raise ForgeUnitSkillFoundryError(
                f"frontdesk freeze manifest artifact is missing or unsafe: {ref}"
            ) from exc
        if actual_hash != expected_hash:
            raise ForgeUnitSkillFoundryError(
                f"frontdesk freeze manifest hash mismatch for {ref}: "
                f"expected {expected_hash}, got {actual_hash}"
            )


def _freeze_manifest_required_refs(freeze_manifest: FreezeManifest) -> tuple[str, ...]:
    refs = [
        freeze_manifest.elicitation_report_ref,
        freeze_manifest.spec_audit_report_ref,
        freeze_manifest.skill_spec_ref,
        freeze_manifest.acceptance_criteria_ref,
        freeze_manifest.verification_spec_ref,
        freeze_manifest.worker_input_ref,
        freeze_manifest.build_contract_ref,
    ]
    if freeze_manifest.freeze_gate_result_ref:
        refs.append(freeze_manifest.freeze_gate_result_ref)
    return tuple(refs)
