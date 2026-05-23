"""Refs-only evidence summary for the clean SkillFoundry-on-ForgeUnit path."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skillfoundry.graph_v2 import SkillFoundryV2State, validate_v2_graph_state
from skillfoundry.schema import JsonValue, ensure_json_compatible, sha256_file, utc_now
from skillfoundry.workspace import JobWorkspace

from .config import ForgeUnitSkillFoundryError, SkillFactoryMode
from .state import FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF, PRODUCT_TRUST_BOUNDARIES


FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF = "contextforge/forgeunit_skillfoundry_summary.json"
EVIDENCE_SUMMARY_SCHEMA_VERSION = "forgeunit_skillfoundry.evidence_summary.v1"


def build_evidence_summary(
    workspace: JobWorkspace,
    state: SkillFoundryV2State,
    *,
    mode: SkillFactoryMode,
    registry_path: Path,
    created_at: str | None = None,
) -> dict[str, JsonValue]:
    """Build the product-facing refs-only evidence summary."""

    validate_v2_graph_state(state)
    refs = state.get("refs", {})
    contextforge = state.get("contextforge", {})
    if not isinstance(refs, dict) or not isinstance(contextforge, dict):
        raise ForgeUnitSkillFoundryError("evidence summary requires refs and contextforge mappings")
    payload = {
        "schema_version": EVIDENCE_SUMMARY_SCHEMA_VERSION,
        "job_id": workspace.job_id,
        "engine": "forgeunit",
        "mode": mode,
        "created_at": created_at or utc_now(),
        "stage": str(state.get("stage", "")),
        "status": str(state.get("status", "")),
        "workspace_root": workspace.root.as_posix(),
        "registry_path": Path(registry_path).as_posix(),
        "verification": {
            "status": _optional_scalar(contextforge.get("last_verification_status")),
            "passed": contextforge.get("last_verification_status") == "passed",
            "current_result_ref": _first_ref(refs, "skillfoundry_verification_result", "verification_result"),
        },
        "registry": {
            "approved": contextforge.get("registry_approved") is True,
            "skill_id": _optional_scalar(contextforge.get("registry_skill_id")),
            "version": _optional_scalar(contextforge.get("registry_version")),
            "decision_ref": _optional_ref(refs, "registry_decision"),
            "entry_ref": _optional_ref(refs, "registry_entry"),
        },
        "attempts": _attempt_summaries(workspace),
        "refs": _summary_refs(refs),
        "trust_boundaries": {
            **PRODUCT_TRUST_BOUNDARIES,
            "command_string_included": False,
        },
    }
    compatible = ensure_json_compatible(payload)
    if not isinstance(compatible, dict):
        raise ForgeUnitSkillFoundryError("evidence summary payload must be a JSON object")
    return compatible  # type: ignore[return-value]


def write_evidence_summary(
    workspace: JobWorkspace,
    state: SkillFoundryV2State,
    *,
    mode: SkillFactoryMode,
    registry_path: Path,
    created_at: str | None = None,
) -> SkillFoundryV2State:
    """Write the refs-only evidence summary and return state with its ref/hash."""

    payload = build_evidence_summary(
        workspace,
        state,
        mode=mode,
        registry_path=registry_path,
        created_at=created_at,
    )
    summary_path = workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    refs = dict(state.get("refs", {}))
    refs["forgeunit_skillfoundry_summary"] = FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    hashes = dict(state.get("hashes", {}))
    hashes["forgeunit_skillfoundry_summary"] = sha256_file(summary_path)
    contextforge = dict(state.get("contextforge", {}))
    contextforge["forgeunit_skillfoundry_summary_ref"] = FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    final_state: SkillFoundryV2State = dict(state)
    final_state.update({"refs": refs, "hashes": hashes, "contextforge": contextforge})
    validate_v2_graph_state(final_state)
    return final_state


def read_evidence_summary(workspace: JobWorkspace) -> dict[str, Any]:
    """Read the persisted product evidence summary."""

    try:
        payload = json.loads(workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF, must_exist=True).read_text())
    except Exception as exc:
        raise ForgeUnitSkillFoundryError(f"evidence summary is missing or invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise ForgeUnitSkillFoundryError("evidence summary must be a JSON object")
    return payload


def _summary_refs(refs: dict[str, Any]) -> dict[str, str]:
    allowed = {
        "acceptance_coverage_plan",
        "acceptance_coverage_result",
        "final_report",
        "forgeunit_initial_verification_result",
        "forgeunit_repair_packet",
        "forgeunit_repair_verification_result",
        "forgeunit_skillfoundry_graph_state",
        "forgeunit_skillfoundry_product_state",
        "registry_decision",
        "registry_entry",
        "skillfoundry_verification_result",
        "verification_result",
    }
    selected = {key: value for key, value in refs.items() if key in allowed and isinstance(value, str)}
    selected["forgeunit_skillfoundry_product_state"] = selected.get(
        "forgeunit_skillfoundry_product_state",
        FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF,
    )
    selected["forgeunit_skillfoundry_summary"] = FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    return selected


def _attempt_summaries(workspace: JobWorkspace) -> list[dict[str, str]]:
    attempts_dir = workspace.resolve_path("attempts")
    if not attempts_dir.exists():
        return []
    result: list[dict[str, str]] = []
    for attempt_dir in sorted(attempts_dir.iterdir(), key=lambda path: path.name):
        if not attempt_dir.is_dir() or not attempt_dir.name.isdecimal():
            continue
        attempt_id = attempt_dir.name
        item: dict[str, str] = {"attempt_id": attempt_id}
        for name, ref in {
            "input_manifest_ref": f"attempts/{attempt_id}/input_manifest.json",
            "execution_report_ref": f"attempts/{attempt_id}/execution_report.json",
            "verification_result_ref": f"attempts/{attempt_id}/verification_result.json",
            "forgeunit_summary_ref": f"attempts/{attempt_id}/forgeunit_summary.json",
        }.items():
            if workspace.resolve_path(ref).is_file():
                item[name] = ref
        if len(item) > 1:
            result.append(item)
    return result


def _first_ref(refs: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _optional_ref(refs, key)
        if value is not None:
            return value
    return None


def _optional_ref(refs: dict[str, Any], key: str) -> str | None:
    value = refs.get(key)
    return value if isinstance(value, str) and value else None


def _optional_scalar(value: Any) -> JsonValue:
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return None
