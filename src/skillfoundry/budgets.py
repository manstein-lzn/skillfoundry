"""Shared budget semantics for SkillFoundry runtime contracts."""

from __future__ import annotations


UNLIMITED_TOKEN_BUDGET_SENTINEL = 1_000_000_000
TOKEN_BUDGET_MODE_EXPLICIT = "explicit"
TOKEN_BUDGET_MODE_UNLIMITED_DEFAULT = "unlimited_default"


def effective_token_budget(max_total_tokens: int | None) -> int:
    """Return the integer budget required by ContextForge-compatible APIs."""

    return max_total_tokens if max_total_tokens is not None else UNLIMITED_TOKEN_BUDGET_SENTINEL


def token_budget_mode(max_total_tokens: int | None) -> str:
    """Return the persisted mode describing how the token budget was chosen."""

    if max_total_tokens is None:
        return TOKEN_BUDGET_MODE_UNLIMITED_DEFAULT
    return TOKEN_BUDGET_MODE_EXPLICIT
