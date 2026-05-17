import pytest
from langgraph.checkpoint.memory import InMemorySaver

from skillfoundry import (
    Route,
    Stage,
    StateValidationError,
    WorkflowStatus,
    compile_skillfoundry_graph,
    validate_graph_state,
)


def run_graph(initial_state, *, checkpointer=None, thread_id="test-thread", **compile_kwargs):
    graph = compile_skillfoundry_graph(checkpointer=checkpointer, **compile_kwargs)
    config = {"configurable": {"thread_id": thread_id}} if checkpointer is not None else None
    if config is None:
        return graph.invoke(initial_state)
    return graph.invoke(initial_state, config=config)


def test_build_new_terminal_path_reaches_report_emitted():
    result = run_graph(
        {
            "job_id": "build-001",
            "route": Route.BUILD_NEW.value,
            "attempt_limit": 1,
        }
    )

    validate_graph_state(result)
    assert result["route"] == Route.BUILD_NEW.value
    assert result["stage"] == Stage.EMIT_REPORT.value
    assert result["status"] == WorkflowStatus.REPORT_EMITTED.value
    assert result["attempt_count"] == 1
    assert result["build_count"] == 1
    assert result["repair_count"] == 0
    assert result["refs"]["current_skill"] == "package/SKILL.md"
    assert result["refs"]["registry_entry"] == "registry/entry.json"
    assert result["refs"]["final_report"] == "verifier/final_report.json"


def test_reuse_existing_does_not_build_new_package():
    result = run_graph(
        {
            "job_id": "reuse-001",
            "route": Route.REUSE_EXISTING.value,
            "reuse_existing_ref": "registry/approved/demo-skill.json",
        }
    )

    validate_graph_state(result)
    assert result["route"] == Route.REUSE_EXISTING.value
    assert result["stage"] == Stage.EMIT_REPORT.value
    assert result["status"] == WorkflowStatus.REPORT_EMITTED.value
    assert result["build_count"] == 0
    assert result["attempt_count"] == 0
    assert result["refs"]["registry_entry"] == "registry/approved/demo-skill.json"
    assert "current_skill" not in result["refs"]
    assert "package_hash" not in result["hashes"]


def test_reject_unsafe_stops_before_build():
    result = run_graph(
        {
            "job_id": "unsafe-001",
            "route": Route.REJECT_UNSAFE.value,
        }
    )

    validate_graph_state(result)
    assert result["route"] == Route.REJECT_UNSAFE.value
    assert result["stage"] == Stage.SAFE_STOP.value
    assert result["status"] == WorkflowStatus.REJECTED.value
    assert result["failure_class"] == "unsafe_requirement"
    assert result["build_count"] == 0
    assert result["attempt_count"] == 0
    assert result["human_review_required"] is False
    assert "current_attempt" not in result["refs"]
    assert result["refs"]["safety_report"] == "verifier/safety_stop.json"


def test_ask_clarifying_question_reaches_human_review_placeholder():
    result = run_graph(
        {
            "job_id": "clarify-001",
            "route": Route.ASK_CLARIFYING_QUESTION.value,
        }
    )

    validate_graph_state(result)
    assert result["route"] == Route.ASK_CLARIFYING_QUESTION.value
    assert result["stage"] == Stage.HUMAN_REVIEW.value
    assert result["status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED.value
    assert result["human_review_required"] is True
    assert result["build_count"] == 0
    assert result["refs"]["clarification_request"] == "human_review/clarification_request.json"
    assert result["refs"]["human_review_request"] == "human_review/request.json"
    assert "current_attempt" not in result["refs"]


def test_failed_verify_routes_to_repair_when_attempts_remain():
    result = run_graph(
        {
            "job_id": "repair-001",
            "route": Route.BUILD_NEW.value,
            "attempt_limit": 2,
            "fail_verify_until_attempt": 1,
        }
    )

    validate_graph_state(result)
    assert result["stage"] == Stage.EMIT_REPORT.value
    assert result["status"] == WorkflowStatus.REPORT_EMITTED.value
    assert result["attempt_count"] == 2
    assert result["build_count"] == 2
    assert result["repair_count"] == 1
    assert result["failure_class"] is None
    assert result["refs"]["repair_instructions"] == "attempts/002/repair_instructions.md"
    assert result["refs"]["repair_basis"] == "verifier/verification_result_attempt_001.json"
    assert result["refs"]["current_attempt"] == "attempts/002"
    assert result["refs"]["registry_entry"] == "registry/entry.json"


def test_failed_verify_at_attempt_limit_routes_fail_closed_human_review():
    result = run_graph(
        {
            "job_id": "limit-001",
            "route": Route.BUILD_NEW.value,
            "attempt_limit": 1,
            "verification_passed": False,
        }
    )

    validate_graph_state(result)
    assert result["stage"] == Stage.HUMAN_REVIEW.value
    assert result["status"] == WorkflowStatus.FAIL_CLOSED.value
    assert result["failure_class"] == "stub_verification_failure"
    assert result["human_review_required"] is True
    assert result["attempt_count"] == 1
    assert result["repair_count"] == 0
    assert result["next_action"] is None
    assert result["refs"]["human_review_request"] == "human_review/request.json"
    assert "registry_entry" not in result["refs"]


@pytest.mark.parametrize(
    "bad_state",
    [
        {"job_id": "bad-001", "raw_worker_transcript": "raw"},
        {"job_id": "bad-001", "refs": {"raw_tool_logs": "attempts/001/tool.log"}},
        {"job_id": "bad-001", "skill_package": {"SKILL.md": "content"}},
    ],
)
def test_state_validator_rejects_forbidden_raw_fields(bad_state):
    with pytest.raises(StateValidationError):
        validate_graph_state(bad_state)


def test_state_validator_rejects_oversized_inline_strings():
    with pytest.raises(StateValidationError):
        validate_graph_state({"job_id": "large-001", "next_action": "x" * 1025})


def test_state_validator_accepts_refs_and_hashes_only_state():
    state = {
        "job_id": "valid-001",
        "stage": Stage.BUILD.value,
        "status": WorkflowStatus.BUILT.value,
        "route": Route.BUILD_NEW.value,
        "attempt_count": 1,
        "attempt_limit": 2,
        "refs": {"worker_transcript_ref": "attempts/001/worker_transcript.log"},
        "hashes": {"package_hash": "a" * 64},
        "human_review_required": False,
        "next_action": "verify",
    }

    validate_graph_state(state)


def test_graph_compiles_with_in_memory_saver_and_thread_id():
    checkpointer = InMemorySaver()
    graph = compile_skillfoundry_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "checkpoint-thread"}}

    result = graph.invoke(
        {
            "job_id": "checkpoint-001",
            "route": Route.BUILD_NEW.value,
        },
        config=config,
    )
    snapshot = graph.get_state(config)

    validate_graph_state(result)
    assert result["status"] == WorkflowStatus.REPORT_EMITTED.value
    assert snapshot.values["job_id"] == "checkpoint-001"
    assert snapshot.values["refs"]["final_report"] == "verifier/final_report.json"


def test_checkpoint_resume_smoke_continues_by_refs_only_state():
    checkpointer = InMemorySaver()
    graph = compile_skillfoundry_graph(
        checkpointer=checkpointer,
        interrupt_after=[Stage.PREPARE_WORKSPACE.value],
    )
    config = {"configurable": {"thread_id": "resume-thread"}}

    first = graph.invoke(
        {
            "job_id": "resume-001",
            "route": Route.BUILD_NEW.value,
        },
        config=config,
    )
    snapshot = graph.get_state(config)

    validate_graph_state(first)
    assert first["stage"] == Stage.PREPARE_WORKSPACE.value
    assert first["refs"]["build_contract"] == "build_contract.yaml"
    assert first["refs"]["worker_input"] == "worker_input.md"
    assert "current_attempt" not in first["refs"]
    assert snapshot.next == (Stage.BUILD.value,)

    resumed = graph.invoke(None, config=config)

    validate_graph_state(resumed)
    assert resumed["stage"] == Stage.EMIT_REPORT.value
    assert resumed["status"] == WorkflowStatus.REPORT_EMITTED.value
    assert resumed["refs"]["build_contract"] == "build_contract.yaml"
    assert resumed["refs"]["current_attempt"] == "attempts/001"
    assert resumed["refs"]["final_report"] == "verifier/final_report.json"
    assert "raw_worker_transcript" not in resumed
    assert "worker_transcript" not in resumed
