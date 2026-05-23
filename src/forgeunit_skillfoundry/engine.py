"""ForgeUnit execution engine for the clean SkillFoundry composition layer."""

from __future__ import annotations

from dataclasses import dataclass

from skillfoundry.forgeunit_adapter import (
    run_forgeunit_command_bridge_pilot_graph,
    run_forgeunit_repair_pilot_graph,
)
from skillfoundry.graph_v2 import SkillFoundryV2State, validate_v2_graph_state

from .config import ForgeUnitSkillFoundryError, SkillFactoryConfig, SkillFactoryMode


@dataclass(frozen=True)
class ForgeUnitSkillFactoryEngineResult:
    """Refs-only state returned by the ForgeUnit engine boundary."""

    mode: SkillFactoryMode
    state: SkillFoundryV2State


class ForgeUnitSkillFactoryEngine:
    """Run one SkillFoundry job through ForgeUnit command-boundary execution."""

    def run(self, config: SkillFactoryConfig) -> ForgeUnitSkillFactoryEngineResult:
        if config.mode == "command_bridge":
            state = run_forgeunit_command_bridge_pilot_graph(
                config.runs_root,
                config.job_id,
                registry_path=config.registry_path,
                command=config.command,
                attempt_limit=config.attempt_limit,
                version=config.version,
                created_at=config.created_at,
            )
        elif config.mode == "repair_command_bridge":
            if config.repair_command is None:
                raise ForgeUnitSkillFoundryError("repair_command_bridge mode requires repair_command")
            state = run_forgeunit_repair_pilot_graph(
                config.runs_root,
                config.job_id,
                registry_path=config.registry_path,
                build_command=config.command,
                repair_command=config.repair_command,
                attempt_limit=config.attempt_limit,
                version=config.version,
                created_at=config.created_at,
            )
        else:  # pragma: no cover - Literal mode keeps this unreachable.
            raise ForgeUnitSkillFoundryError(f"unsupported SkillFactory mode: {config.mode!r}")

        validate_v2_graph_state(state)
        return ForgeUnitSkillFactoryEngineResult(mode=config.mode, state=state)
