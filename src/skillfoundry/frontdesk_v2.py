"""ContextForge contracts and governance evidence for Front Desk v2."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from contextforge import (
    AGENT_NODE_CONTRACT_SCHEMA,
    CHECKPOINT_POLICY_SCHEMA,
    GOAL_CONTRACT_SCHEMA,
    TOOL_PERMISSION_SCHEMA,
    WRITE_SCOPE_SCHEMA,
    AgentNodeContract,
    GoalContract,
    with_computed_hash,
)

from .frontdesk_schema import FrontDeskConfig
from .frontdesk_workspace import (
    FRONTDESK_BUDGET_REF,
    FRONTDESK_CLARIFICATION_SUMMARY_REF,
    FRONTDESK_CONVERSATION_REF,
    FRONTDESK_RISK_REPORT_REF,
    FrontDeskWorkspace,
    write_frontdesk_artifact,
)
from .schema import JsonValue, ensure_json_compatible, sha256_file, sha256_json, utc_now
from .workspace import JobWorkspace


FRONTDESK_V2_SCHEMA_VERSION = "skillfoundry.frontdesk_v2.v1"
FRONTDESK_V2_CONTRACT_DIR = "frontdesk/contextforge"
FRONTDESK_V2_GOAL_CONTRACT_REF = f"{FRONTDESK_V2_CONTRACT_DIR}/goal_contract.json"
FRONTDESK_V2_GOVERNANCE_REPORT_REF = f"{FRONTDESK_V2_CONTRACT_DIR}/governance_report.json"
FRONTDESK_V2_MANIFEST_REF = f"{FRONTDESK_V2_CONTRACT_DIR}/manifest.json"

CORE_NEED_DISCOVERY_NODE_ID = "frontdesk_core_need_discovery"
SOLUTION_PLANNER_NODE_ID = "frontdesk_solution_planner"
SPEC_AUDITOR_NODE_ID = "frontdesk_spec_auditor"
FRONTDESK_V2_NODE_IDS = (
    CORE_NEED_DISCOVERY_NODE_ID,
    SOLUTION_PLANNER_NODE_ID,
    SPEC_AUDITOR_NODE_ID,
)

_CONTRACT_VERSION = "0.1"
_SOLUTION_PLAN_REF = "frontdesk/solution_plan.json"
_DEFAULT_FRONTDESK_PROMPT_BUDGET_TOKENS = 24_000


@dataclass(frozen=True)
class FrontDeskV2Artifacts:
    """Refs written by the Front Desk v2 contract/governance slice."""

    goal_contract_ref: str
    node_contract_refs: dict[str, str]
    governance_report_ref: str
    manifest_ref: str


def build_frontdesk_goal_contract(
    workspace: FrontDeskWorkspace | JobWorkspace,
    *,
    created_at: str | None = None,
) -> GoalContract:
    """Build the Front Desk v2 GoalContract without mutating the workspace."""

    frontdesk = _coerce_frontdesk(workspace)
    timestamp = created_at or utc_now()
    source_hashes = _frontdesk_source_hashes(frontdesk)
    payload = {
        "schema": GOAL_CONTRACT_SCHEMA,
        "version": _CONTRACT_VERSION,
        "goal_id": _frontdesk_goal_id(frontdesk.job_id),
        "objective": "Clarify, plan, audit, and freeze SkillFoundry requirements through governed artifacts.",
        "success_criteria": [
            "Core need is summarized as governed context.",
            "Solution plan is approved before freeze.",
            "Spec audit evidence exists before build routing.",
            "Raw frontdesk conversation is never exposed to the builder context.",
            "Provider usage and budget evidence are recorded or explicitly unavailable with a reason.",
        ],
        "non_goals": [
            "Do not run build workers.",
            "Do not approve registry promotion.",
            "Do not treat raw conversation as trusted instructions.",
        ],
        "constraints": [
            "Front Desk node state and handoff artifacts must store refs, hashes, and summaries only.",
            "Raw frontdesk conversation is provenance and must not enter builder context.",
            "Freeze readiness fails closed on incomplete redaction, missing plan approval, or budget violations.",
        ],
        "assumptions": [
            f"Front Desk workspace exists at frontdesk/ for job {frontdesk.job_id}.",
            "Existing deterministic FrontDeskFreezeGate remains the freeze authority in this slice.",
        ],
        "budgets": _frontdesk_budget_payload(frontdesk),
        "checkpoint_policy": _checkpoint_policy(),
        "stop_conditions": [
            "frontdesk_freeze_ready",
            "frontdesk_needs_user_input",
            "frontdesk_human_review_required",
            "frontdesk_failed_closed",
        ],
        "verification_gate_id": None,
        "created_at": timestamp,
        "locked_at": timestamp,
        "contract_hash": "",
        "metadata": {
            "bridge": FRONTDESK_V2_SCHEMA_VERSION,
            "job_id": frontdesk.job_id,
            "source_hashes": source_hashes,
            "raw_conversation_included": False,
        },
    }
    return GoalContract.from_dict(with_computed_hash(payload, "contract_hash"))


def build_frontdesk_node_contracts(
    workspace: FrontDeskWorkspace | JobWorkspace,
    goal_contract: GoalContract | None = None,
) -> dict[str, AgentNodeContract]:
    """Build the three Front Desk v2 node contracts without mutating the workspace."""

    frontdesk = _coerce_frontdesk(workspace)
    goal = goal_contract or build_frontdesk_goal_contract(frontdesk)
    return {
        node_id: _build_frontdesk_node_contract(frontdesk, goal, node_id)
        for node_id in FRONTDESK_V2_NODE_IDS
    }


def evaluate_frontdesk_v2_governance(
    workspace: FrontDeskWorkspace | JobWorkspace,
    *,
    created_at: str | None = None,
) -> dict[str, JsonValue]:
    """Return freeze-readiness evidence for the Front Desk v2 boundary."""

    frontdesk = _coerce_frontdesk(workspace)
    timestamp = created_at or utc_now()
    budget, budget_blocker = _read_frontdesk_config_for_governance(frontdesk)
    risk_report = _read_json_ref(frontdesk, FRONTDESK_RISK_REPORT_REF)
    solution_plan = _read_json_ref(frontdesk, _SOLUTION_PLAN_REF)
    blocking_reasons: list[dict[str, JsonValue]] = []
    if budget_blocker is not None:
        blocking_reasons.append(budget_blocker)

    redaction_status = _json_str(risk_report.get("redaction_status")) if risk_report else None
    if redaction_status != "complete":
        blocking_reasons.append(
            _reason("redaction_not_complete", f"redaction_status={redaction_status or 'missing'}")
        )

    plan_status = _json_str(solution_plan.get("status")) if solution_plan else None
    if plan_status != "approved":
        blocking_reasons.append(_reason("approved_plan_required", f"solution_plan.status={plan_status or 'missing'}"))

    provider_usage = risk_report.get("provider_usage") if isinstance(risk_report.get("provider_usage"), Mapping) else {}
    usage_payload = _provider_usage_payload(provider_usage)
    blocking_reasons.extend(_provider_usage_blockers(provider_usage, budget))

    status = "ready_for_freeze" if not blocking_reasons else "blocked"
    report = {
        "schema_version": FRONTDESK_V2_SCHEMA_VERSION,
        "job_id": frontdesk.job_id,
        "status": status,
        "blocking_reasons": blocking_reasons,
        "frontdesk_refs": {
            "clarification_summary": FRONTDESK_CLARIFICATION_SUMMARY_REF,
            "risk_report": FRONTDESK_RISK_REPORT_REF,
            "budget": FRONTDESK_BUDGET_REF,
            "solution_plan": _SOLUTION_PLAN_REF,
            "raw_conversation": FRONTDESK_CONVERSATION_REF,
        },
        "provider_usage": usage_payload,
        "raw_conversation_included": False,
        "created_at": timestamp,
    }
    return ensure_json_compatible(report)  # type: ignore[return-value]


def write_frontdesk_v2_contract_artifacts(
    workspace: FrontDeskWorkspace | JobWorkspace,
    *,
    created_at: str | None = None,
) -> FrontDeskV2Artifacts:
    """Write Front Desk v2 ContextForge contracts and governance report."""

    frontdesk = _coerce_frontdesk(workspace)
    goal = build_frontdesk_goal_contract(frontdesk, created_at=created_at)
    nodes = build_frontdesk_node_contracts(frontdesk, goal)
    governance = evaluate_frontdesk_v2_governance(frontdesk, created_at=created_at)

    write_frontdesk_artifact(frontdesk, FRONTDESK_V2_GOAL_CONTRACT_REF, goal.to_dict())
    node_refs: dict[str, str] = {}
    for node_id, contract in nodes.items():
        ref = f"{FRONTDESK_V2_CONTRACT_DIR}/{node_id}.json"
        write_frontdesk_artifact(frontdesk, ref, contract.to_dict())
        node_refs[node_id] = ref
    write_frontdesk_artifact(frontdesk, FRONTDESK_V2_GOVERNANCE_REPORT_REF, governance)

    manifest = {
        "schema_version": FRONTDESK_V2_SCHEMA_VERSION,
        "job_id": frontdesk.job_id,
        "goal_contract": {
            "ref": FRONTDESK_V2_GOAL_CONTRACT_REF,
            "contract_hash": goal.contract_hash,
            "sha256": sha256_file(frontdesk.workspace.resolve_path(FRONTDESK_V2_GOAL_CONTRACT_REF, must_exist=True)),
        },
        "node_contracts": {
            node_id: {
                "ref": ref,
                "contract_hash": nodes[node_id].contract_hash,
                "sha256": sha256_file(frontdesk.workspace.resolve_path(ref, must_exist=True)),
            }
            for node_id, ref in node_refs.items()
        },
        "governance_report": {
            "ref": FRONTDESK_V2_GOVERNANCE_REPORT_REF,
            "sha256": sha256_file(
                frontdesk.workspace.resolve_path(FRONTDESK_V2_GOVERNANCE_REPORT_REF, must_exist=True)
            ),
        },
        "raw_conversation_included": False,
        "created_at": created_at or utc_now(),
    }
    write_frontdesk_artifact(frontdesk, FRONTDESK_V2_MANIFEST_REF, manifest)
    return FrontDeskV2Artifacts(
        goal_contract_ref=FRONTDESK_V2_GOAL_CONTRACT_REF,
        node_contract_refs=node_refs,
        governance_report_ref=FRONTDESK_V2_GOVERNANCE_REPORT_REF,
        manifest_ref=FRONTDESK_V2_MANIFEST_REF,
    )


def _build_frontdesk_node_contract(
    frontdesk: FrontDeskWorkspace,
    goal: GoalContract,
    node_id: str,
) -> AgentNodeContract:
    spec = _node_spec(node_id)
    source_hashes = _frontdesk_source_hashes(frontdesk)
    payload = {
        "schema": AGENT_NODE_CONTRACT_SCHEMA,
        "version": _CONTRACT_VERSION,
        "node_id": node_id,
        "goal_id": goal.goal_id,
        "role": spec["role"],
        "mission": spec["mission"],
        "visible_context": _visible_context(node_id),
        "forbidden_context": _forbidden_context(),
        "allowed_tools": _allowed_tools(),
        "write_scope": {
            "schema": WRITE_SCOPE_SCHEMA,
            "allowed_paths": ["frontdesk"],
            "forbidden_paths": [
                FRONTDESK_CONVERSATION_REF,
                "skill_spec.yaml",
                "verification_spec.yaml",
                "worker_input.md",
                "build_contract.yaml",
                "artifact_manifest.json",
            ],
            "allowed_artifact_kinds": ["frontdesk_artifact", "contextforge_contract", "governance_report"],
            "max_bytes": 2_000_000,
            "requires_diff_review": False,
            "metadata": {"boundary": "frontdesk_v2"},
        },
        "output_contract": spec["output_contract"],
        "worker": {
            "kind": "llm",
            "name": node_id,
            "version": None,
            "model": None,
            "parameters": {},
            "metadata": {
                "worker_boundary": "frontdesk_llm_node",
                "contextforge_records_boundary_only": True,
            },
        },
        "budgets": _frontdesk_budget_payload(frontdesk),
        "cache_policy": {
            "mode": "stable_prefix",
            "cache_epoch_id": "frontdesk-v2-" + sha256_json({"node_id": node_id, "source_hashes": source_hashes})[:16],
            "max_prefix_churn": 0.05,
            "metadata": {"stable_prefix_sources": sorted(source_hashes)},
        },
        "checkpoint_policy": _checkpoint_policy(),
        "stop_conditions": spec["stop_conditions"],
        "verification_gate_id": None,
        "handoff_policy": {
            "handoff_artifacts_only": True,
            "raw_conversation_handoff": False,
            "next_nodes": list(spec["next_nodes"]),
        },
        "contract_hash": "",
        "metadata": {
            "bridge": FRONTDESK_V2_SCHEMA_VERSION,
            "job_id": frontdesk.job_id,
            "raw_conversation_included": False,
            "source_hashes": source_hashes,
        },
    }
    return AgentNodeContract.from_dict(with_computed_hash(payload, "contract_hash"))


def _node_spec(node_id: str) -> dict[str, Any]:
    specs: dict[str, dict[str, Any]] = {
        CORE_NEED_DISCOVERY_NODE_ID: {
            "role": "core_need_discovery",
            "mission": "Derive a governed core-need brief from redacted Front Desk summaries.",
            "output_contract": "CoreNeedDiscoveryReport and CoreNeedBrief refs only.",
            "stop_conditions": ["core_need_ready", "needs_core_need_input", "human_review_required"],
            "next_nodes": [SOLUTION_PLANNER_NODE_ID],
        },
        SOLUTION_PLANNER_NODE_ID: {
            "role": "solution_planner",
            "mission": "Produce a solution plan from the governed core-need brief and acceptance constraints.",
            "output_contract": "SolutionPlan, draft SkillSpec, and draft AcceptanceCriteria refs only.",
            "stop_conditions": ["plan_draft_ready", "awaiting_plan_review", "plan_revision_requested"],
            "next_nodes": [SPEC_AUDITOR_NODE_ID],
        },
        SPEC_AUDITOR_NODE_ID: {
            "role": "spec_auditor",
            "mission": "Audit the approved plan and draft artifacts for feasibility, safety, and testability.",
            "output_contract": "SpecAuditReport and FeasibilityReport refs only.",
            "stop_conditions": ["approved", "needs_more_clarification", "infeasible", "human_review_required"],
            "next_nodes": [],
        },
    }
    if node_id not in specs:
        raise ValueError(f"unsupported Front Desk v2 node_id: {node_id}")
    return specs[node_id]


def _visible_context(node_id: str) -> list[dict[str, JsonValue]]:
    refs = [
        FRONTDESK_CLARIFICATION_SUMMARY_REF,
        FRONTDESK_RISK_REPORT_REF,
        FRONTDESK_BUDGET_REF,
    ]
    if node_id in {SOLUTION_PLANNER_NODE_ID, SPEC_AUDITOR_NODE_ID}:
        refs.append("frontdesk/core_need_brief.json")
    if node_id == SPEC_AUDITOR_NODE_ID:
        refs.append(_SOLUTION_PLAN_REF)
        refs.extend(["frontdesk/draft_skill_spec.yaml", "frontdesk/acceptance_criteria.yaml"])
    selectors = [
        {
            "selector_id": f"visible-{ref.replace('/', '-').replace('.', '-')}",
            "kind": "artifact",
            "value": ref,
            "required": ref
            in {
                FRONTDESK_CLARIFICATION_SUMMARY_REF,
                FRONTDESK_RISK_REPORT_REF,
                FRONTDESK_BUDGET_REF,
                "frontdesk/core_need_brief.json",
                _SOLUTION_PLAN_REF,
                "frontdesk/draft_skill_spec.yaml",
                "frontdesk/acceptance_criteria.yaml",
            },
            "reason": "Governed Front Desk artifact visible to this node.",
            "metadata": {
                "frontdesk_context": True,
                "stable_prefix": ref != _SOLUTION_PLAN_REF,
            },
        }
        for ref in refs
    ]
    if node_id == SPEC_AUDITOR_NODE_ID:
        selectors.append(
            {
                "selector_id": "visible-frontdesk-plan-review-tag",
                "kind": "tag",
                "value": "plan_review",
                "required": False,
                "reason": "Governed Front Desk plan review record visible to Spec Auditor when present.",
                "metadata": {
                    "frontdesk_context": True,
                    "stable_prefix": True,
                    "routed_ref": True,
                },
            }
        )
    return selectors


def _forbidden_context() -> list[dict[str, JsonValue]]:
    return [
        {
            "selector_id": "forbid-raw-frontdesk-conversation-artifact",
            "kind": "artifact",
            "value": FRONTDESK_CONVERSATION_REF,
            "required": False,
            "reason": "Raw conversation is provenance only; nodes consume governed summaries.",
            "metadata": {"fail_closed": True},
        },
        {
            "selector_id": "forbid-raw-frontdesk-conversation-tag",
            "kind": "tag",
            "value": "raw_frontdesk_conversation",
            "required": False,
            "reason": "Raw conversation tags must not enter v2 prompt context.",
            "metadata": {"fail_closed": True},
        },
    ]


def _allowed_tools() -> list[dict[str, JsonValue]]:
    return [
        {
            "schema": TOOL_PERMISSION_SCHEMA,
            "tool_name": "frontdesk_workspace.read_artifact",
            "allowed": True,
            "argument_schema": {"type": "object", "required": ["ref"]},
            "path_policy": "workspace_only",
            "network_policy": "disabled",
            "max_calls": 20,
            "timeout_seconds": 10,
            "requires_approval": False,
            "metadata": {"frontdesk_v2": True},
        },
        {
            "schema": TOOL_PERMISSION_SCHEMA,
            "tool_name": "frontdesk_workspace.write_artifact",
            "allowed": True,
            "argument_schema": {"type": "object", "required": ["ref", "payload"]},
            "path_policy": "workspace_only",
            "network_policy": "disabled",
            "max_calls": 10,
            "timeout_seconds": 10,
            "requires_approval": False,
            "metadata": {"frontdesk_v2": True},
        },
    ]


def _checkpoint_policy() -> dict[str, JsonValue]:
    return {
        "schema": CHECKPOINT_POLICY_SCHEMA,
        "triggers": ["phase_complete", "context_pressure", "handoff", "budget_threshold"],
        "max_interval_seconds": 1800,
        "max_steps_between_checkpoints": 10,
        "summary_budget_tokens": 800,
        "required": True,
        "metadata": {"boundary": "frontdesk_v2"},
    }


def _frontdesk_budget_payload(frontdesk: FrontDeskWorkspace) -> dict[str, JsonValue]:
    config = _read_frontdesk_config(frontdesk)
    prompt_budget_tokens = min(config.max_total_tokens, _DEFAULT_FRONTDESK_PROMPT_BUDGET_TOKENS)
    return {
        "prompt_budget_tokens": prompt_budget_tokens,
        "context_budget_tokens": prompt_budget_tokens,
        "max_frontdesk_model_calls": config.max_frontdesk_model_calls,
        "max_total_tokens": config.max_total_tokens,
        "max_provider_cost_usd": config.max_provider_cost_usd,
        "max_output_tokens_per_call": config.max_output_tokens_per_call,
    }


def _provider_usage_blockers(provider_usage: Mapping[str, Any], budget: FrontDeskConfig) -> list[dict[str, JsonValue]]:
    blockers: list[dict[str, JsonValue]] = []
    usage_available = provider_usage.get("usage_available")
    if usage_available is False:
        reason = _json_str(provider_usage.get("usage_unavailable_reason"))
        if reason is None:
            blockers.append(
                _reason("frontdesk_usage_unavailable_reason_missing", "usage_available=false without reason")
            )
        return blockers
    if usage_available is not True:
        blockers.append(_reason("frontdesk_usage_unavailable_reason_missing", "provider usage evidence missing"))
        return blockers

    model_call_count = _number(provider_usage.get("model_call_count"))
    total_tokens = _number(provider_usage.get("total_tokens"))
    cost_usd = _number(provider_usage.get("cost_usd"))
    missing_metrics = [
        name
        for name, value in (
            ("model_call_count", model_call_count),
            ("total_tokens", total_tokens),
            ("cost_usd", cost_usd),
        )
        if value is None
    ]
    if missing_metrics:
        blockers.append(
            _reason("frontdesk_usage_metrics_missing", "missing usage metric(s): " + ", ".join(missing_metrics))
        )
        return blockers
    if model_call_count is not None and model_call_count > budget.max_frontdesk_model_calls:
        blockers.append(_reason("frontdesk_model_call_budget_exceeded", str(model_call_count)))
    if total_tokens is not None and total_tokens > budget.max_total_tokens:
        blockers.append(_reason("frontdesk_token_budget_exceeded", str(total_tokens)))
    if cost_usd is not None and cost_usd > budget.max_provider_cost_usd:
        blockers.append(_reason("frontdesk_cost_budget_exceeded", str(cost_usd)))
    return blockers


def _provider_usage_payload(provider_usage: Any) -> dict[str, JsonValue]:
    usage = provider_usage if isinstance(provider_usage, Mapping) else {}
    return {
        "usage_available": usage.get("usage_available") if isinstance(usage.get("usage_available"), bool) else None,
        "usage_unavailable_reason": _json_str(usage.get("usage_unavailable_reason")),
        "model_call_count": _number(usage.get("model_call_count")),
        "total_tokens": _number(usage.get("total_tokens")),
        "cost_usd": _number(usage.get("cost_usd")),
    }


def _frontdesk_source_hashes(frontdesk: FrontDeskWorkspace) -> dict[str, JsonValue]:
    refs = [
        FRONTDESK_CLARIFICATION_SUMMARY_REF,
        FRONTDESK_RISK_REPORT_REF,
        FRONTDESK_BUDGET_REF,
        "frontdesk/core_need_brief.json",
        _SOLUTION_PLAN_REF,
        "frontdesk/draft_skill_spec.yaml",
        "frontdesk/acceptance_criteria.yaml",
    ]
    hashes: dict[str, JsonValue] = {}
    for ref in refs:
        try:
            hashes[ref] = sha256_file(frontdesk.workspace.resolve_path(ref, must_exist=True))
        except Exception:
            continue
    return hashes


def _read_frontdesk_config(frontdesk: FrontDeskWorkspace) -> FrontDeskConfig:
    try:
        path = frontdesk.workspace.resolve_path(FRONTDESK_BUDGET_REF, must_exist=True)
        return FrontDeskConfig.from_json(path.read_text(encoding="utf-8"))
    except Exception:
        return FrontDeskConfig()


def _read_frontdesk_config_for_governance(
    frontdesk: FrontDeskWorkspace,
) -> tuple[FrontDeskConfig, dict[str, JsonValue] | None]:
    try:
        path = frontdesk.workspace.resolve_path(FRONTDESK_BUDGET_REF, must_exist=True)
        return FrontDeskConfig.from_json(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return FrontDeskConfig(), _reason("frontdesk_budget_invalid", f"budget evidence missing or invalid: {exc}")


def _read_json_ref(frontdesk: FrontDeskWorkspace, ref: str) -> dict[str, Any]:
    try:
        path = frontdesk.workspace.resolve_path(ref, must_exist=True)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _reason(code: str, message: str) -> dict[str, JsonValue]:
    return {"code": code, "message": message}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _json_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _frontdesk_goal_id(job_id: str) -> str:
    return f"frontdesk-goal-{sha256_json({'job_id': job_id})[:16]}"


def _coerce_frontdesk(workspace: FrontDeskWorkspace | JobWorkspace) -> FrontDeskWorkspace:
    if isinstance(workspace, FrontDeskWorkspace):
        return workspace
    return FrontDeskWorkspace(workspace=workspace)
