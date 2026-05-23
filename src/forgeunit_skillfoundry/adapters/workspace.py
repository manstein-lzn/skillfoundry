"""Adapter for routing an existing locked JobWorkspace into vNext."""

from __future__ import annotations

from pathlib import Path

from skillfoundry.registry import DEFAULT_REGISTRY_VERSION
from skillfoundry.workspace import JobWorkspace

from ..config import ForgeUnitSkillFoundryError
from ..engine import ForgeUnitSkillFactoryEngine
from ..product import ForgeUnitSkillFactoryResult, run_codex_skill_factory


def run_existing_workspace_skill_factory(
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
    """Run the clean ForgeUnit SkillFactory path against an existing workspace."""

    if not isinstance(workspace, JobWorkspace):
        raise ForgeUnitSkillFoundryError("workspace must be a JobWorkspace")
    workspace.check_locked_inputs()
    _require_workspace_root_matches_job_id(workspace)
    return run_codex_skill_factory(
        workspace.root.parent,
        workspace.job_id,
        registry_path=registry_path,
        command=command,
        repair_command=repair_command,
        attempt_limit=attempt_limit,
        version=version,
        created_at=created_at,
        overwrite_workspace=False,
        engine=engine,
    )


def _require_workspace_root_matches_job_id(workspace: JobWorkspace) -> None:
    expected_root = workspace.root.parent / workspace.job_id
    if workspace.root.resolve() != expected_root.resolve():
        raise ForgeUnitSkillFoundryError(
            "existing workspace root must be named by its job_id so vNext can route it by runs_root/job_id"
        )
