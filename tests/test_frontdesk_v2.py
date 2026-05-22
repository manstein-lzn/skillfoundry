from __future__ import annotations

import json

from contextforge import AgentNodeContract, GoalContract

import skillfoundry
from skillfoundry import (
    CORE_NEED_DISCOVERY_NODE_ID,
    FRONTDESK_V2_GOAL_CONTRACT_REF,
    FRONTDESK_V2_GOVERNANCE_REPORT_REF,
    FRONTDESK_V2_MANIFEST_REF,
    FRONTDESK_V2_NODE_IDS,
    SOLUTION_PLANNER_NODE_ID,
    SPEC_AUDITOR_NODE_ID,
    evaluate_frontdesk_v2_governance,
    initialize_frontdesk_workspace,
    initialize_job_workspace,
    write_frontdesk_artifact,
    write_frontdesk_v2_contract_artifacts,
)


CREATED_AT = "2026-05-22T00:00:00Z"


def make_frontdesk(tmp_path, *, job_id: str = "frontdesk-v2"):
    workspace = initialize_job_workspace(tmp_path / "runs", job_id)
    frontdesk = initialize_frontdesk_workspace(workspace)
    write_risk_report(frontdesk)
    write_solution_plan(frontdesk, status="approved")
    return workspace, frontdesk


def write_risk_report(
    frontdesk,
    *,
    redaction_status: str = "complete",
    provider_usage: dict | None = None,
) -> None:
    write_frontdesk_artifact(
        frontdesk,
        "risk_report.json",
        {
            "schema_version": "skillfoundry.frontdesk_risk_report.v1",
            "risk_flags": [],
            "redaction_status": redaction_status,
            "data_sensitivity": "internal",
            "provider_usage": provider_usage
            or {
                "usage_available": False,
                "usage_unavailable_reason": "Fixture frontdesk run does not expose aggregate provider usage.",
            },
        },
    )


def write_solution_plan(frontdesk, *, status: str) -> None:
    write_frontdesk_artifact(
        frontdesk,
        "solution_plan.json",
        {
            "schema_version": "skillfoundry.solution_plan.v1",
            "plan_id": "plan-001",
            "status": status,
            "summary": "Build a governed local skill.",
        },
    )


def read_json(workspace, ref: str):
    return json.loads(workspace.resolve_path(ref, must_exist=True).read_text(encoding="utf-8"))


def reason_codes(report):
    return {item["code"] for item in report["blocking_reasons"]}


def test_frontdesk_v2_api_is_exported() -> None:
    assert skillfoundry.write_frontdesk_v2_contract_artifacts is write_frontdesk_v2_contract_artifacts
    assert skillfoundry.evaluate_frontdesk_v2_governance is evaluate_frontdesk_v2_governance
    assert skillfoundry.FRONTDESK_V2_NODE_IDS == FRONTDESK_V2_NODE_IDS


def test_writes_contextforge_contracts_for_frontdesk_nodes_without_raw_conversation(tmp_path) -> None:
    workspace, frontdesk = make_frontdesk(tmp_path)

    artifacts = write_frontdesk_v2_contract_artifacts(frontdesk, created_at=CREATED_AT)

    assert artifacts.goal_contract_ref == FRONTDESK_V2_GOAL_CONTRACT_REF
    assert set(artifacts.node_contract_refs) == set(FRONTDESK_V2_NODE_IDS)
    goal = GoalContract.from_dict(read_json(workspace, FRONTDESK_V2_GOAL_CONTRACT_REF))
    assert goal.metadata["raw_conversation_included"] is False

    for node_id, ref in artifacts.node_contract_refs.items():
        node = AgentNodeContract.from_dict(read_json(workspace, ref))
        visible_values = {selector.value for selector in node.visible_context}
        forbidden_values = {selector.value for selector in node.forbidden_context}
        assert node.node_id == node_id
        assert "frontdesk/conversation.jsonl" not in visible_values
        assert "frontdesk/conversation.jsonl" in forbidden_values
        assert node.metadata["raw_conversation_included"] is False

    governance = read_json(workspace, FRONTDESK_V2_GOVERNANCE_REPORT_REF)
    manifest = read_json(workspace, FRONTDESK_V2_MANIFEST_REF)
    assert governance["status"] == "ready_for_freeze"
    assert governance["raw_conversation_included"] is False
    assert manifest["raw_conversation_included"] is False


def test_frontdesk_v2_contracts_cover_expected_nodes(tmp_path) -> None:
    _workspace, frontdesk = make_frontdesk(tmp_path)

    nodes = skillfoundry.build_frontdesk_node_contracts(frontdesk)

    assert set(nodes) == {
        CORE_NEED_DISCOVERY_NODE_ID,
        SOLUTION_PLANNER_NODE_ID,
        SPEC_AUDITOR_NODE_ID,
    }
    assert nodes[CORE_NEED_DISCOVERY_NODE_ID].role == "core_need_discovery"
    assert nodes[SOLUTION_PLANNER_NODE_ID].role == "solution_planner"
    assert nodes[SPEC_AUDITOR_NODE_ID].role == "spec_auditor"
    solution_visible = {selector.value: selector.required for selector in nodes[SOLUTION_PLANNER_NODE_ID].visible_context}
    spec_visible = {selector.value: selector.required for selector in nodes[SPEC_AUDITOR_NODE_ID].visible_context}
    assert solution_visible["frontdesk/core_need_brief.json"] is True
    assert spec_visible["frontdesk/core_need_brief.json"] is True
    assert spec_visible["frontdesk/solution_plan.json"] is True


def test_governance_blocks_when_redaction_is_incomplete(tmp_path) -> None:
    _workspace, frontdesk = make_frontdesk(tmp_path)
    write_risk_report(frontdesk, redaction_status="not_started")

    report = evaluate_frontdesk_v2_governance(frontdesk, created_at=CREATED_AT)

    assert report["status"] == "blocked"
    assert "redaction_not_complete" in reason_codes(report)


def test_governance_blocks_without_approved_plan(tmp_path) -> None:
    _workspace, frontdesk = make_frontdesk(tmp_path)
    write_solution_plan(frontdesk, status="draft")

    report = evaluate_frontdesk_v2_governance(frontdesk, created_at=CREATED_AT)

    assert report["status"] == "blocked"
    assert "approved_plan_required" in reason_codes(report)


def test_governance_blocks_when_frontdesk_budget_is_exceeded(tmp_path) -> None:
    _workspace, frontdesk = make_frontdesk(tmp_path)
    write_risk_report(
        frontdesk,
        provider_usage={
            "usage_available": True,
            "model_call_count": 999,
            "total_tokens": 999_999,
            "cost_usd": 999.0,
        },
    )

    report = evaluate_frontdesk_v2_governance(frontdesk, created_at=CREATED_AT)

    assert report["status"] == "blocked"
    assert "frontdesk_model_call_budget_exceeded" in reason_codes(report)
    assert "frontdesk_token_budget_exceeded" in reason_codes(report)
    assert "frontdesk_cost_budget_exceeded" in reason_codes(report)


def test_governance_records_provider_usage_unavailable_reason(tmp_path) -> None:
    _workspace, frontdesk = make_frontdesk(tmp_path)
    write_risk_report(
        frontdesk,
        provider_usage={
            "usage_available": False,
            "usage_unavailable_reason": "Offline fixture does not expose provider usage.",
        },
    )

    report = evaluate_frontdesk_v2_governance(frontdesk, created_at=CREATED_AT)

    assert report["status"] == "ready_for_freeze"
    assert report["provider_usage"]["usage_available"] is False
    assert report["provider_usage"]["usage_unavailable_reason"] == "Offline fixture does not expose provider usage."


def test_governance_blocks_when_usage_available_metrics_are_missing(tmp_path) -> None:
    _workspace, frontdesk = make_frontdesk(tmp_path)
    write_risk_report(frontdesk, provider_usage={"usage_available": True})

    report = evaluate_frontdesk_v2_governance(frontdesk, created_at=CREATED_AT)

    assert report["status"] == "blocked"
    assert "frontdesk_usage_metrics_missing" in reason_codes(report)


def test_governance_blocks_when_provider_usage_unavailable_reason_is_missing(tmp_path) -> None:
    _workspace, frontdesk = make_frontdesk(tmp_path)
    write_risk_report(frontdesk, provider_usage={"usage_available": False})

    report = evaluate_frontdesk_v2_governance(frontdesk, created_at=CREATED_AT)

    assert report["status"] == "blocked"
    assert "frontdesk_usage_unavailable_reason_missing" in reason_codes(report)


def test_governance_blocks_when_budget_artifact_is_invalid(tmp_path) -> None:
    _workspace, frontdesk = make_frontdesk(tmp_path)
    write_frontdesk_artifact(frontdesk, "budget.json", {"max_total_tokens": 0})

    report = evaluate_frontdesk_v2_governance(frontdesk, created_at=CREATED_AT)

    assert report["status"] == "blocked"
    assert "frontdesk_budget_invalid" in reason_codes(report)
