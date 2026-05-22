import json

from contextforge.schema import ModelResponse

from skillfoundry.api import SkillFoundryAPI
from skillfoundry import GRAPH_V2_STATE_REF, validate_v2_graph_state
from skillfoundry.frontdesk_goal_runtime import (
    FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF,
    FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF,
    FRONTDESK_SPEC_AUDIT_RUNTIME_RESULT_REF,
)
from skillfoundry.frontdesk_schema import FrontDeskState
from skillfoundry.frontdesk_schema import FrontDeskConfig


class ScriptedModelClient:
    def __init__(self, payload):
        self.payload = payload
        self.invocations = []

    def invoke(self, messages, model, params, tools=None):
        self.invocations.append({"messages": messages, "model": model, "params": params, "tools": tools})
        return (
            ModelResponse(
                text=json.dumps(self.payload, sort_keys=True),
                raw_response_artifact_ref=None,
                finish_reason="stop",
                metadata={"scripted": True},
            ),
            None,
            None,
        )


def _needs_clarification_payload():
    return {
        "readiness_guess": "needs_clarification",
        "current_understanding": "The user wants a skill, but the input boundary is unclear.",
        "known_fields": {"domain": "engineering"},
        "missing_fields": ["input.source"],
        "risk_flags": ["input_boundary_unknown"],
        "next_questions": [
            {
                "question_id": "Q-001",
                "text": "What exact input should the skill consume?",
                "missing_field_path": "input.source",
                "reason": "The skill needs a concrete input contract before build.",
                "priority": "must",
                "answer_type": "free_text",
                "blocks_build": True,
            }
        ],
        "draft_skill_spec": {"name": "debug-helper", "description": "Help debug failed tests."},
        "draft_acceptance_criteria": [
            {
                "id": "AC-001",
                "description": "The skill asks for the input boundary before building.",
            }
        ],
        "assumptions": ["The user will provide logs."],
    }


def _ready_payload():
    return {
        "readiness_guess": "ready_for_audit",
        "current_understanding": "The user wants a skill that analyzes pasted pytest failure logs.",
        "known_fields": {"input": {"source": "pasted pytest logs"}, "output": {"format": "markdown"}},
        "missing_fields": [],
        "risk_flags": [],
        "next_questions": [],
        "draft_skill_spec": {
            "skill_id": "pytest-failure-debugger",
            "title": "Pytest Failure Debugger",
            "description": "Analyze pasted pytest failure logs and suggest fixes.",
            "trigger_scenarios": ["The user asks for help with pytest failures."],
            "non_trigger_scenarios": ["The request requires reading external systems."],
            "required_inputs": ["Pasted pytest failure log."],
            "expected_outputs": ["Markdown diagnosis with likely cause, files to inspect, and fix steps."],
            "constraints": ["Use only pasted logs.", "Do not read external systems."],
            "acceptance_criteria": ["Output includes likely cause, files to inspect, and fix steps."],
            "reference_materials": [],
            "security_notes": ["No external data access is permitted."],
        },
        "draft_acceptance_criteria": [
            {
                "id": "AC-001",
                "description": "The skill diagnoses pasted pytest failures without external access.",
                "source_requirement": "Analyze pasted pytest failure logs.",
                "source_turn_ids": ["turn-001", "turn-002"],
                "requirement_id": "REQ-001",
                "test_method": "fixture",
                "pass_condition": "Output includes likely cause, files to inspect, and fix steps.",
                "failure_examples": ["Claims it inspected files that were not provided."],
                "required_evidence": ["fixture-output.md"],
                "evidence_kind": "file",
                "priority": "must",
                "risk_tags": [],
                "data_sensitivity": "internal",
                "coverage_status": "planned",
                "fixture_ref": "frontdesk/fixtures/pytest-log.md",
            }
        ],
        "assumptions": ["The user pastes the failure log."],
    }


def _approved_audit_payload():
    return {
        "spec_audit_report": {
            "decision": "approved",
            "clarity_score": 0.93,
            "feasibility_score": 0.9,
            "testability_score": 0.9,
            "risk_score": 0.1,
            "missing_requirements": [],
            "unsafe_assumptions": [],
            "required_followup_questions": [],
            "spec_patch_suggestions": [],
            "routing_recommendation": "codex_worker",
            "approval_rationale": "The spec is clear and testable.",
        },
        "feasibility_report": {
            "decision": "feasible",
            "feasibility_score": 0.9,
            "risk_score": 0.1,
            "routing_recommendation": "codex_worker",
            "required_capabilities": ["markdown_generation"],
            "missing_capabilities": [],
            "constraints": ["No external access."],
            "risks": [],
            "assumptions": ["The user pastes logs."],
            "human_review_reasons": [],
        },
    }


def test_frontdesk_api_runs_multi_round_loop_with_injected_clients(tmp_path):
    payloads = {
        "requirements_elicitor": [_needs_clarification_payload(), _ready_payload()],
        "spec_auditor": [_approved_audit_payload(), _approved_audit_payload(), _approved_audit_payload()],
    }

    def factory(role, _job_id, _round_index):
        return ScriptedModelClient(payloads[role].pop(0))

    api = SkillFoundryAPI(tmp_path / "runs", frontdesk_client_factory=factory)

    created = api.create_frontdesk_job({"job_id": "frontdesk-api-demo", "message": "Build me a pytest helper skill."})
    assert created["status"] == "ask_user"
    assert created["state"]["readiness"] == "needs_clarification"
    assert created["next_questions"][0]["question_id"] == "Q-001"

    advanced = api.append_frontdesk_message(
        "frontdesk-api-demo",
        {"message": "The input is pasted pytest failure logs. Do not read the repo automatically."},
    )
    assert advanced["status"] == "await_user_plan_review"
    assert advanced["phase"] == "user_review"
    assert advanced["state"]["readiness"] == "awaiting_plan_review"
    assert advanced["state"]["solution_plan_ref"] == "frontdesk/solution_plan.json"
    assert advanced["solution_plan"]["proposed_skill_name"] == "Pytest Failure Debugger"
    assert {action["decision"] for action in advanced["review_actions"]} == {
        "approve",
        "human_review",
        "request_revision",
        "reject",
    }

    plan = api.handle("GET", "/frontdesk/jobs/frontdesk-api-demo/solution-plan").json()
    assert plan["plan_id"] == "solution-plan-002"

    approved = api.handle(
        "POST",
        "/frontdesk/jobs/frontdesk-api-demo/plan-review",
        body={"decision": "approve", "reason": "This plan matches the desired workflow."},
    ).json()
    assert approved["status"] == "route_to_build"
    assert approved["state"]["readiness"] == "frozen"
    assert approved["state"]["skill_spec_ref"] == "skill_spec.yaml"
    assert approved["state"]["latest_plan_review_ref"] == "frontdesk/plan_review_002.json"
    assert approved["state"]["latest_audit_report_ref"] == "frontdesk/spec_audit_report_002.json"
    runtime_result_path = tmp_path / "runs" / "frontdesk-api-demo" / FRONTDESK_SPEC_AUDIT_RUNTIME_RESULT_REF
    runtime_result = json.loads(runtime_result_path.read_text(encoding="utf-8"))
    assert runtime_result["refs"]["plan_review"] == "frontdesk/plan_review_002.json"
    assert runtime_result["refs"]["spec_audit_report"] == "frontdesk/spec_audit_report_002.json"
    assert runtime_result["trust_boundaries"]["raw_conversation_included"] is False

    fetched = api.get_frontdesk_job("frontdesk-api-demo")
    assert fetched["turn_count"] == 2
    assert fetched["state"]["readiness"] == "frozen"


def test_frontdesk_plan_review_revision_feeds_next_planning_round(tmp_path):
    revised = _ready_payload()
    revised["current_understanding"] = "The user wants a skill that explains pasted pytest failures for junior developers."
    revised["draft_skill_spec"]["title"] = "Junior Pytest Failure Coach"
    payloads = {
        "requirements_elicitor": [_ready_payload(), revised],
        "spec_auditor": [_approved_audit_payload(), _approved_audit_payload()],
    }

    def factory(role, _job_id, _round_index):
        return ScriptedModelClient(payloads[role].pop(0))

    api = SkillFoundryAPI(tmp_path / "runs", frontdesk_client_factory=factory)
    created = api.create_frontdesk_job(
        {"job_id": "frontdesk-api-revision", "message": "Build a skill from pasted pytest logs."}
    )
    assert created["state"]["readiness"] == "awaiting_plan_review"

    revised_payload = api.handle(
        "POST",
        "/frontdesk/jobs/frontdesk-api-revision/plan-review",
        body={
            "decision": "request_revision",
            "reason": "Make the audience junior developers and explain concepts more explicitly.",
        },
    ).json()

    assert revised_payload["status"] == "await_user_plan_review"
    assert revised_payload["state"]["readiness"] == "awaiting_plan_review"
    assert revised_payload["state"]["plan_revision_count"] == 1
    assert revised_payload["turn_count"] == 2
    assert revised_payload["solution_plan"]["proposed_skill_name"] == "Junior Pytest Failure Coach"


def test_frontdesk_plan_revision_limit_persists_human_review_state(tmp_path):
    revised = _ready_payload()
    revised["draft_skill_spec"]["title"] = "Revised Pytest Helper"
    payloads = {
        "requirements_elicitor": [_ready_payload(), revised],
        "spec_auditor": [_approved_audit_payload(), _approved_audit_payload()],
    }

    def factory(role, _job_id, _round_index):
        return ScriptedModelClient(payloads[role].pop(0))

    api = SkillFoundryAPI(tmp_path / "runs", frontdesk_client_factory=factory)
    created = api.create_frontdesk_job({"job_id": "frontdesk-revision-limit", "message": "Build a pytest helper."})
    assert created["state"]["readiness"] == "awaiting_plan_review"

    budget_path = tmp_path / "runs" / "frontdesk-revision-limit" / "frontdesk" / "budget.json"
    budget = FrontDeskConfig.from_json(budget_path.read_text(encoding="utf-8"))
    budget.max_plan_revision_rounds = 1
    budget_path.write_text(budget.to_json(), encoding="utf-8")

    first_revision = api.handle(
        "POST",
        "/frontdesk/jobs/frontdesk-revision-limit/plan-review",
        body={"decision": "request_revision", "reason": "First revision."},
    ).json()
    assert first_revision["state"]["readiness"] == "awaiting_plan_review"
    assert first_revision["state"]["plan_revision_count"] == 1

    exceeded = api.handle(
        "POST",
        "/frontdesk/jobs/frontdesk-revision-limit/plan-review",
        body={"decision": "request_revision", "reason": "Second revision should hit the limit."},
    ).json()
    assert exceeded["state"]["readiness"] == "human_review_required"
    assert exceeded["state"]["next_action"] == "human_review"
    assert exceeded["state"]["plan_revision_count"] == 2

    fetched = api.get_frontdesk_job("frontdesk-revision-limit")
    assert fetched["state"]["readiness"] == "human_review_required"
    assert fetched["state"]["plan_revision_count"] == 2


def test_frontdesk_api_defaults_to_offline_goal_harness_without_live_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = SkillFoundryAPI(tmp_path / "runs")
    marker = "RAW_API_FRONTDESK_MARKER_SHOULD_NOT_LEAK"

    created_response = api.handle(
        "POST",
        "/frontdesk/jobs",
        body={"job_id": "frontdesk-no-key", "message": f"Build a governed skill. {marker}"},
    )

    assert created_response.status == 201
    created = created_response.json()
    assert created["status"] == "await_user_plan_review"
    assert created["phase"] == "user_review"
    assert created["state"]["readiness"] == "awaiting_plan_review"
    assert created["state"]["latest_elicitation_report_ref"] == "frontdesk/elicitation_report_001.json"
    assert created["state"]["solution_plan_ref"] == "frontdesk/solution_plan.json"
    assert marker not in created_response.body.decode("utf-8")

    run_root = tmp_path / "runs" / "frontdesk-no-key"
    core_runtime = json.loads((run_root / FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF).read_text(encoding="utf-8"))
    plan_runtime = json.loads((run_root / FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF).read_text(encoding="utf-8"))
    assert core_runtime["trust_boundaries"]["raw_conversation_included"] is False
    assert plan_runtime["trust_boundaries"]["raw_conversation_included"] is False
    assert marker not in json.dumps(core_runtime, sort_keys=True)
    assert marker not in json.dumps(plan_runtime, sort_keys=True)

    approved = api.handle(
        "POST",
        "/frontdesk/jobs/frontdesk-no-key/plan-review",
        body={"decision": "approve", "reason": "Offline Goal Harness plan is acceptable."},
    ).json()
    assert approved["status"] == "route_to_build"
    assert approved["state"]["readiness"] == "frozen"
    assert approved["state"]["latest_plan_review_ref"] == "frontdesk/plan_review_001.json"
    assert approved["state"]["latest_audit_report_ref"] == "frontdesk/spec_audit_report_001.json"
    audit_runtime = json.loads((run_root / FRONTDESK_SPEC_AUDIT_RUNTIME_RESULT_REF).read_text(encoding="utf-8"))
    assert audit_runtime["refs"]["plan_review"] == "frontdesk/plan_review_001.json"
    assert audit_runtime["refs"]["spec_audit_report"] == "frontdesk/spec_audit_report_001.json"
    assert audit_runtime["trust_boundaries"]["raw_conversation_included"] is False


def test_frontdesk_api_rejects_build_before_freeze(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = SkillFoundryAPI(tmp_path / "runs")

    created = api.handle(
        "POST",
        "/frontdesk/jobs",
        body={"job_id": "frontdesk-build-too-early", "message": "Build a governed skill."},
    ).json()
    assert created["state"]["readiness"] == "awaiting_plan_review"

    response = api.handle("POST", "/frontdesk/jobs/frontdesk-build-too-early/build", body={})

    assert response.status == 409
    assert response.json()["error"]["code"] == "frontdesk_build_not_ready"


def test_frontdesk_api_requires_consistent_frozen_route_to_build_state(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = SkillFoundryAPI(tmp_path / "runs")
    job_id = "frontdesk-build-gate"
    api.handle(
        "POST",
        "/frontdesk/jobs",
        body={"job_id": job_id, "message": "Build a governed skill."},
    )
    run_root = tmp_path / "runs" / job_id
    state_path = run_root / "frontdesk" / "state.json"
    original = json.loads(state_path.read_text(encoding="utf-8"))

    frozen_wrong_action = FrontDeskState.from_dict(
        {
            **original,
            "readiness": "frozen",
            "next_action": "freeze_spec",
        }
    )
    state_path.write_text(frozen_wrong_action.to_json(), encoding="utf-8")
    response = api.handle("POST", f"/frontdesk/jobs/{job_id}/build", body={})
    html = api.handle("GET", f"/frontdesk/jobs/{job_id}", headers={"Accept": "text/html"}).body.decode("utf-8")
    assert response.status == 409
    assert response.json()["error"]["code"] == "frontdesk_build_not_ready"
    assert "/build" not in html

    wrong_readiness_route = FrontDeskState.from_dict(
        {
            **original,
            "readiness": "plan_approved",
            "next_action": "route_to_build",
        }
    )
    state_path.write_text(wrong_readiness_route.to_json(), encoding="utf-8")
    response = api.handle("POST", f"/frontdesk/jobs/{job_id}/build", body={})
    html = api.handle("GET", f"/frontdesk/jobs/{job_id}", headers={"Accept": "text/html"}).body.decode("utf-8")
    assert response.status == 409
    assert response.json()["error"]["code"] == "frontdesk_build_not_ready"
    assert "/build" not in html


def test_frontdesk_api_builds_frozen_job_through_graph_v2_without_raw_leakage(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = SkillFoundryAPI(tmp_path / "runs")
    marker = "RAW_API_GRAPH_V2_MARKER_SHOULD_NOT_LEAK"
    job_id = "frontdesk-graph-v2-build"

    created = api.handle(
        "POST",
        "/frontdesk/jobs",
        body={"job_id": job_id, "message": f"Build a governed status skill. {marker}"},
    ).json()
    assert created["status"] == "await_user_plan_review"

    approved = api.handle(
        "POST",
        f"/frontdesk/jobs/{job_id}/plan-review",
        body={"decision": "approve", "reason": "The governed plan is ready to build."},
    ).json()
    assert approved["status"] == "route_to_build"
    assert approved["state"]["readiness"] == "frozen"

    build_response = api.handle("POST", f"/frontdesk/jobs/{job_id}/build", body={})

    assert build_response.status == 200
    assert marker not in build_response.body.decode("utf-8")
    payload = build_response.json()
    assert payload["schema_version"] == "skillfoundry.api.frontdesk_build.v1"
    assert payload["status"] == "registered"
    assert payload["build_path"]["mode"] == "graph_v2_goal_harness"
    assert payload["build_path"]["canonical"] is True
    assert payload["graph_v2_state_ref"] == GRAPH_V2_STATE_REF
    assert payload["final_report"]["final_status"] == "registered"
    assert payload["graph_v2_state"]["stage"] == "emit_report"
    assert payload["graph_v2_state"]["status"] == "report_emitted"
    assert payload["graph_v2_state"]["contextforge"]["registry_approved"] is True
    validate_v2_graph_state(payload["graph_v2_state"])

    run_root = tmp_path / "runs" / job_id
    graph_state_path = run_root / GRAPH_V2_STATE_REF
    assert graph_state_path.is_file()
    persisted_state = json.loads(graph_state_path.read_text(encoding="utf-8"))
    validate_v2_graph_state(persisted_state)
    assert marker not in json.dumps(persisted_state, sort_keys=True)

    status = api.handle("GET", f"/jobs/{job_id}/contextforge").json()
    assert status["refs"]["graph_v2_state"]["exists"] is True
    assert status["refs"]["verified_runtime_result"]["exists"] is True
    assert status["status"]["graph_v2"]["registry_approved"] is True
    assert status["status"]["graph_v2"]["last_verification_status"] == "passed"
    assert status["status"]["registry"]["approved"] is True
    assert marker not in json.dumps(status, sort_keys=True)

    job = api.handle("GET", f"/jobs/{job_id}").json()
    assert job["status"] == "registered"
    assert job["build_path"]["mode"] == "graph_v2_goal_harness"
    assert job["package_downloadable"] is True


def test_frontdesk_retry_upgrades_legacy_low_model_call_budget(tmp_path):
    payloads = {
        "requirements_elicitor": [_needs_clarification_payload(), _needs_clarification_payload()],
        "spec_auditor": [_approved_audit_payload(), _approved_audit_payload()],
    }

    def factory(role, _job_id, _round_index):
        return ScriptedModelClient(payloads[role].pop(0))

    api = SkillFoundryAPI(tmp_path / "runs", frontdesk_client_factory=factory)
    api.create_frontdesk_job({"job_id": "frontdesk-retry-budget", "message": "Build a skill."})

    budget_path = tmp_path / "runs" / "frontdesk-retry-budget" / "frontdesk" / "budget.json"
    budget_path.write_text(FrontDeskConfig(max_frontdesk_model_calls=1).to_json(), encoding="utf-8")

    retried = api.retry_frontdesk_job("frontdesk-retry-budget")
    budget = FrontDeskConfig.from_json(budget_path.read_text(encoding="utf-8"))

    assert retried["status"] == "ask_user"
    assert budget.max_frontdesk_model_calls == FrontDeskConfig().max_frontdesk_model_calls
