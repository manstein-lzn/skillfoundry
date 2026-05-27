"""Thin adapters from existing SkillFoundry surfaces into the vNext factory."""

from .frontdesk import (
    FRONTDESK_STATE_REF,
    run_frozen_frontdesk_adaptive_codex_factory,
    run_frozen_frontdesk_pi_worker_factory,
    run_frozen_frontdesk_skill_factory,
)
from .workspace import run_existing_workspace_skill_factory

__all__ = [
    "FRONTDESK_STATE_REF",
    "run_existing_workspace_skill_factory",
    "run_frozen_frontdesk_adaptive_codex_factory",
    "run_frozen_frontdesk_pi_worker_factory",
    "run_frozen_frontdesk_skill_factory",
]
