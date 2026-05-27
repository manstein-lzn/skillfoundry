"""Configuration boundary for the clean ForgeUnit SkillFoundry kernel."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from skillfoundry.registry import DEFAULT_REGISTRY_VERSION
from skillfoundry.workspace import JOB_ID_RE


SkillFactoryMode = Literal["command_bridge", "repair_command_bridge", "adaptive_codex", "adaptive_pi_worker"]


class ForgeUnitSkillFoundryError(RuntimeError):
    """Raised when the clean composition layer cannot run safely."""


@dataclass(frozen=True)
class SkillFactoryConfig:
    """Validated runtime configuration for one SkillFoundry-on-ForgeUnit run."""

    runs_root: Path
    job_id: str
    registry_path: Path
    command: str
    repair_command: str | None = None
    worker_input: str | None = None
    attempt_limit: int = 2
    version: str = DEFAULT_REGISTRY_VERSION
    created_at: str | None = None
    overwrite_workspace: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "runs_root", Path(self.runs_root))
        object.__setattr__(self, "registry_path", Path(self.registry_path))
        validate_job_id(self.job_id)
        _require_command(self.command, "command")
        if self.repair_command is not None:
            _require_command(self.repair_command, "repair_command")
        if not isinstance(self.attempt_limit, int) or isinstance(self.attempt_limit, bool) or self.attempt_limit <= 0:
            raise ForgeUnitSkillFoundryError("attempt_limit must be a positive integer")
        if self.repair_command is not None and self.attempt_limit < 2:
            raise ForgeUnitSkillFoundryError("repair_command_bridge mode requires attempt_limit >= 2")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ForgeUnitSkillFoundryError("version must be a non-empty string")
        if self.created_at is not None and (not isinstance(self.created_at, str) or not self.created_at.strip()):
            raise ForgeUnitSkillFoundryError("created_at must be a non-empty string when provided")
        if not isinstance(self.overwrite_workspace, bool):
            raise ForgeUnitSkillFoundryError("overwrite_workspace must be a boolean")

    @property
    def mode(self) -> SkillFactoryMode:
        return "repair_command_bridge" if self.repair_command is not None else "command_bridge"


def validate_job_id(job_id: str) -> None:
    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        raise ForgeUnitSkillFoundryError("job_id must be a safe SkillFoundry job id")


def _require_command(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ForgeUnitSkillFoundryError(f"{field_name} must be a non-empty explicit command bridge")
