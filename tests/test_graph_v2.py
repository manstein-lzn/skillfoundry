from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from skillfoundry.graph_v2 import (
    V2Route,
    V2Stage,
    V2StateValidationError,
    V2Status,
    compile_skillfoundry_v2_graph,
    route_after_verification,
    validate_v2_graph_state,
)


def _state(
    *,
    verification_status: str,
    attempt_count: int = 1,
    attempt_limit: int = 2,
) -> dict:
    return {
        "job_id": "graph-v2-001",
        "attempt_count": attempt_count,
        "attempt_limit": attempt_limit,
        "refs": {
            "ledger": "contextforge/ledger.sqlite3",
            "goal_contract": "contextforge/goal_contract.json",
            "build_node_contract": "contextforge/build_node_contract.json",
            "verification_gate": "contextforge/verification_gate.json",
        },
        "hashes": {
            "goal_contract": "sha256:" + "a" * 64,
            "build_node_contract": "sha256:" + "b" * 64,
            "verification_gate": "sha256:" + "c" * 64,
        },
        "contextforge": {
            "last_goal_run_id": "goal-run-001",
            "last_worker_run_id": "worker-run-001",
            "last_context_view_id": "context-view-001",
            "last_prompt_cache_plan_id": "cache-plan-001",
            "last_verification_result_id": "verification-result-001",
            "last_verification_status": verification_status,
        },
    }


@pytest.mark.parametrize(
    ("verification_status", "route"),
    [
        ("passed", V2Route.REGISTRY_GATE.value),
        ("failed", V2Route.REPAIR_GOAL_NODE.value),
        ("review_required", V2Route.HUMAN_REVIEW.value),
        ("human_acceptance_required", V2Route.HUMAN_REVIEW.value),
        ("unsupported_verification_spec", V2Route.REDESIGN.value),
    ],
)
def test_route_after_verification_reads_contextforge_status(verification_status: str, route: str) -> None:
    assert route_after_verification(_state(verification_status=verification_status)) == route


def test_failed_verification_routes_to_human_review_when_attempts_are_exhausted() -> None:
    state = _state(verification_status="failed", attempt_count=2, attempt_limit=2)

    assert route_after_verification(state) == V2Route.HUMAN_REVIEW.value


@pytest.mark.parametrize(
    "bad_state",
    [
        {"job_id": "bad", "raw_conversation": "raw"},
        {"job_id": "bad", "contextforge": {"prompt": "raw prompt"}},
        {"job_id": "bad", "refs": {"worker_transcript": "attempts/001/raw.log"}},
        {"job_id": "bad", "skill_package": {"SKILL.md": "contents"}},
    ],
)
def test_v2_validator_rejects_raw_state_fields(bad_state: dict) -> None:
    with pytest.raises(V2StateValidationError):
        validate_v2_graph_state(bad_state)


def test_v2_validator_accepts_refs_ids_and_resume_checkpoint_refs() -> None:
    state = _state(verification_status="failed")
    state["contextforge"]["last_checkpoint_id"] = "checkpoint-001"
    state["contextforge"]["checkpoint_ids"] = ["checkpoint-001", "checkpoint-002"]
    state["refs"]["resume_brief"] = "resume_brief.md"

    validate_v2_graph_state(state)


def test_v2_graph_success_route_reaches_registry_and_report() -> None:
    graph = compile_skillfoundry_v2_graph()

    result = graph.invoke(_state(verification_status="passed"))

    validate_v2_graph_state(result)
    assert result["stage"] == V2Stage.EMIT_REPORT.value
    assert result["status"] == V2Status.REPORT_EMITTED.value
    assert result["refs"]["registry_decision"] == "registry/decision.json"
    assert result["refs"]["final_report"] == "contextforge/final_report.json"
    assert result["human_review_required"] is False


def test_v2_graph_repair_route_stops_with_repair_refs() -> None:
    graph = compile_skillfoundry_v2_graph()

    result = graph.invoke(_state(verification_status="failed"))

    validate_v2_graph_state(result)
    assert result["stage"] == V2Stage.REPAIR_GOAL_NODE.value
    assert result["status"] == V2Status.REPAIR_PLANNED.value
    assert result["refs"]["repair_instructions"] == "attempts/002/repair_instructions.md"
    assert result["human_review_required"] is False


def test_v2_graph_human_review_and_redesign_routes_keep_refs_only() -> None:
    graph = compile_skillfoundry_v2_graph()

    human = graph.invoke(_state(verification_status="review_required"))
    redesign = graph.invoke(_state(verification_status="unsupported_verification_spec"))

    validate_v2_graph_state(human)
    validate_v2_graph_state(redesign)
    assert human["stage"] == V2Stage.HUMAN_REVIEW.value
    assert human["refs"]["human_review_request"] == "human_review/request.json"
    assert redesign["stage"] == V2Stage.REDESIGN.value
    assert redesign["refs"]["redesign_report"] == "contextforge/redesign_required.json"


def test_v2_graph_checkpoint_resume_keeps_contextforge_ids_only() -> None:
    checkpointer = InMemorySaver()
    graph = compile_skillfoundry_v2_graph(
        checkpointer=checkpointer,
        interrupt_after=[V2Stage.VERIFY.value],
    )
    config = {"configurable": {"thread_id": "graph-v2-resume"}}

    first = graph.invoke(_state(verification_status="passed"), config=config)
    snapshot = graph.get_state(config)
    resumed = graph.invoke(None, config=config)

    validate_v2_graph_state(first)
    validate_v2_graph_state(resumed)
    assert first["stage"] == V2Stage.VERIFY.value
    assert snapshot.next == (V2Stage.ROUTE_AFTER_VERIFICATION.value,)
    assert resumed["stage"] == V2Stage.EMIT_REPORT.value
    assert resumed["contextforge"]["last_goal_run_id"] == "goal-run-001"
    assert "prompt" not in resumed["contextforge"]
