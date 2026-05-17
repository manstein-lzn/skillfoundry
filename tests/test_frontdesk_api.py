import json

from contextforge.schema import ModelResponse

from skillfoundry.api import SkillFoundryAPI


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
        "spec_auditor": [_approved_audit_payload(), _approved_audit_payload()],
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
    assert advanced["status"] == "route_to_build"
    assert advanced["state"]["readiness"] == "frozen"
    assert advanced["state"]["skill_spec_ref"] == "skill_spec.yaml"

    fetched = api.get_frontdesk_job("frontdesk-api-demo")
    assert fetched["turn_count"] == 2
    assert fetched["state"]["readiness"] == "frozen"


def test_frontdesk_api_requires_live_key_without_injected_client(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = SkillFoundryAPI(tmp_path / "runs")

    result = api.handle(
        "POST",
        "/frontdesk/jobs",
        body={"job_id": "frontdesk-no-key", "message": "Build a skill."},
    )

    assert result.status == 503
    assert result.json()["error"]["code"] == "openai_api_key_missing"
