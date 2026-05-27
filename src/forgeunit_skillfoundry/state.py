"""Refs-only product state for the clean SkillFoundry-on-ForgeUnit kernel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from skillfoundry.graph_v2 import SkillFoundryV2State, validate_v2_graph_state
from skillfoundry.schema import JsonValue, ensure_json_compatible, sha256_file, utc_now
from skillfoundry.workspace import JobWorkspace

from .config import ForgeUnitSkillFoundryError, SkillFactoryMode


FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF = "contextforge/forgeunit_skillfoundry_product_state.json"
PRODUCT_STATE_SCHEMA_VERSION = "forgeunit_skillfoundry.product_state.v1"
PRODUCT_TRUST_BOUNDARIES: dict[str, bool] = {
    "worker_self_report_is_not_acceptance": True,
    "adaptive_artifact_bodies_included": False,
    "raw_prompt_included": False,
    "raw_transcript_included": False,
    "raw_worker_input_included": False,
    "package_body_included": False,
    "live_codex_required": False,
}
ADAPTIVE_PRODUCT_REF_KEYS = frozenset(
    {
        "adaptive_state",
        "latest_route_plan",
        "latest_next_step_contract",
        "latest_work_unit_result",
        "latest_observation_report",
        "latest_state_correction",
        "bundle_verification_result",
        "product_grade_report",
        "product_repair_packet",
        "decision_ledger",
    }
)
ADAPTIVE_CONTEXT_SUMMARY_KEYS = {
    "adaptive_latest_iteration": "latest_iteration",
    "adaptive_latest_route": "latest_route",
    "adaptive_latest_decision": "latest_decision",
    "adaptive_latest_verification_status": "latest_verification_status",
    "adaptive_current_route_plan_ref": "current_route_plan_ref",
    "adaptive_latest_route_plan_iteration": "latest_route_plan_iteration",
}


def write_product_state(
    workspace: JobWorkspace,
    state: SkillFoundryV2State,
    *,
    mode: SkillFactoryMode,
    registry_path: Path,
    created_at: str | None = None,
) -> SkillFoundryV2State:
    """Persist the product read model and return state carrying its ref/hash."""

    payload = build_product_state_payload(
        workspace,
        state,
        mode=mode,
        registry_path=registry_path,
        created_at=created_at,
    )
    product_state_path = workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF)
    product_state_path.parent.mkdir(parents=True, exist_ok=True)
    product_state_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    refs = dict(state.get("refs", {}))
    refs["forgeunit_skillfoundry_product_state"] = FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF
    hashes = dict(state.get("hashes", {}))
    hashes["forgeunit_skillfoundry_product_state"] = sha256_file(product_state_path)
    contextforge = dict(state.get("contextforge", {}))
    contextforge.update(
        {
            "forgeunit_skillfoundry_engine": "forgeunit",
            "forgeunit_skillfoundry_mode": mode,
            "forgeunit_skillfoundry_product_state_ref": FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF,
        }
    )
    final_state: SkillFoundryV2State = dict(state)
    final_state.update({"refs": refs, "hashes": hashes, "contextforge": contextforge})
    validate_v2_graph_state(final_state)
    return final_state


def build_product_state_payload(
    workspace: JobWorkspace,
    state: SkillFoundryV2State,
    *,
    mode: SkillFactoryMode,
    registry_path: Path,
    created_at: str | None = None,
) -> dict[str, JsonValue]:
    """Construct the stable refs-only product read model payload."""

    validate_v2_graph_state(state)
    payload = {
        "schema_version": PRODUCT_STATE_SCHEMA_VERSION,
        "job_id": workspace.job_id,
        "engine": "forgeunit",
        "mode": mode,
        "created_at": created_at or utc_now(),
        "registry_path": Path(registry_path).as_posix(),
        "stage": str(state.get("stage", "")),
        "status": str(state.get("status", "")),
        "refs": _selected_refs(state.get("refs", {})),
        "adaptive_summary": build_adaptive_summary(state.get("contextforge", {})),
        "contextforge": _selected_contextforge(state.get("contextforge", {})),
        "trust_boundaries": dict(PRODUCT_TRUST_BOUNDARIES),
    }
    compatible = ensure_json_compatible(payload)
    if not isinstance(compatible, dict):
        raise ForgeUnitSkillFoundryError("product state payload must be a JSON object")
    return compatible  # type: ignore[return-value]


def _selected_refs(refs: Mapping[str, str]) -> dict[str, str]:
    allowed = {
        "acceptance_coverage_plan",
        "acceptance_coverage_result",
        "final_report",
        "forgeunit_initial_verification_result",
        "forgeunit_repair_packet",
        "forgeunit_repair_verification_result",
        "forgeunit_summary",
        "registry_decision",
        "registry_entry",
        "skillfoundry_verification_result",
        "verification_result",
    } | ADAPTIVE_PRODUCT_REF_KEYS
    return {key: value for key, value in refs.items() if key in allowed and isinstance(value, str)}


def build_adaptive_summary(contextforge: Mapping[str, Any]) -> dict[str, JsonValue]:
    """Return the product-facing adaptive steering summary without artifact bodies."""

    result: dict[str, JsonValue] = {
        "latest_iteration": None,
        "latest_route": None,
        "latest_decision": None,
        "latest_verification_status": None,
        "current_route_plan_ref": None,
        "latest_route_plan_iteration": None,
    }
    if not isinstance(contextforge, Mapping):
        return result
    for source_key, output_key in ADAPTIVE_CONTEXT_SUMMARY_KEYS.items():
        value = contextforge.get(source_key)
        if isinstance(value, (str, int, bool)) or value is None:
            result[output_key] = value
    return result


def _selected_contextforge(contextforge: Mapping[str, Any]) -> dict[str, JsonValue]:
    allowed = {
        "acceptance_coverage_passed",
        "acceptance_coverage_result_ref",
        "forgeunit_command_bridge_attempt_id",
        "forgeunit_repair_attempt_id",
        "forgeunit_repair_failed_attempt_id",
        "forgeunit_repair_status",
        "last_verification_status",
        "registry_approved",
        "registry_skill_id",
        "registry_version",
        "worker_self_report_is_not_acceptance",
    }
    result: dict[str, JsonValue] = {}
    for key, value in contextforge.items():
        if key not in allowed:
            continue
        if isinstance(value, (str, int, bool)) or value is None:
            result[key] = value
    return result
