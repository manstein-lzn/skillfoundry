"""Thin product entry for SkillFoundry on ForgeUnit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skillfoundry.graph_v2 import SkillFoundryV2State
from skillfoundry.registry import DEFAULT_REGISTRY_VERSION
from skillfoundry.schema import BuildContract, SkillSpec, VerificationSpec
from skillfoundry.workspace import JobWorkspace, initialize_job_workspace

from .config import SkillFactoryConfig, validate_job_id
from .engine import ForgeUnitSkillFactoryEngine
from .graph import run_skill_factory_graph


@dataclass(frozen=True)
class ForgeUnitSkillFactoryResult:
    """Refs-only product result plus the local workspace location."""

    job_id: str
    mode: str
    workspace_root: Path
    registry_path: Path
    state: SkillFoundryV2State

    @property
    def refs(self) -> dict[str, str]:
        return dict(self.state.get("refs", {}))

    @property
    def contextforge(self) -> dict[str, Any]:
        return dict(self.state.get("contextforge", {}))


def prepare_skill_factory_workspace(
    runs_root: str | Path,
    job_id: str,
    *,
    worker_input: str | None = None,
    skill_spec: SkillSpec | None = None,
    verification_spec: VerificationSpec | None = None,
    build_contract: BuildContract | None = None,
    overwrite: bool = False,
) -> JobWorkspace:
    """Create or reuse a standard SkillFoundry workspace for the clean product path."""

    validate_job_id(job_id)
    workspace_root = Path(runs_root) / job_id
    if workspace_root.exists() and (workspace_root / "artifact_manifest.json").is_file() and not overwrite:
        workspace = JobWorkspace(root=workspace_root, job_id=job_id)
        workspace.check_locked_inputs()
        return workspace
    return initialize_job_workspace(
        runs_root,
        job_id,
        worker_input=worker_input,
        skill_spec=skill_spec,
        verification_spec=verification_spec,
        build_contract=build_contract,
        overwrite=overwrite,
    )


def run_codex_skill_factory(
    runs_root: str | Path,
    job_id: str,
    *,
    registry_path: str | Path,
    command: str,
    repair_command: str | None = None,
    worker_input: str | None = None,
    attempt_limit: int = 2,
    version: str = DEFAULT_REGISTRY_VERSION,
    created_at: str | None = None,
    overwrite_workspace: bool = False,
    engine: ForgeUnitSkillFactoryEngine | None = None,
) -> ForgeUnitSkillFactoryResult:
    """Run the clean ForgeUnit-backed Codex Skill factory path."""

    config = SkillFactoryConfig(
        runs_root=Path(runs_root),
        job_id=job_id,
        registry_path=Path(registry_path),
        command=command,
        repair_command=repair_command,
        worker_input=worker_input,
        attempt_limit=attempt_limit,
        version=version,
        created_at=created_at,
        overwrite_workspace=overwrite_workspace,
    )
    graph_result = run_skill_factory_graph(config, engine=engine)
    return ForgeUnitSkillFactoryResult(
        job_id=config.job_id,
        mode=graph_result.mode,
        workspace_root=graph_result.workspace_root,
        registry_path=config.registry_path,
        state=graph_result.state,
    )
