import json
from pathlib import Path
import shlex
import sys

from contextforge.schema import ModelResponse

from forgeunit_skillfoundry import (
    FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF,
    FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF,
    FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF,
    GRAPH_STATE_SCHEMA_VERSION,
)
from forgeunit_skillfoundry.testing import VALID_CODEX_SKILL
from skillfoundry.api import FORGEUNIT_COMMAND_ENV, SkillFoundryAPI
from skillfoundry.frontdesk_goal_runtime import (
    FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF,
    FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF,
    FRONTDESK_SPEC_AUDIT_RUNTIME_RESULT_REF,
)
from skillfoundry.graph_v2 import GRAPH_V2_STATE_REF, validate_v2_graph_state
from skillfoundry.frontdesk_schema import FrontDeskState
from skillfoundry.frontdesk_schema import FrontDeskConfig
from skillfoundry.schema import sha256_file
from skillfoundry.workspace import initialize_job_workspace


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


def _write_api_configured_worker(tmp_path: Path, *, transcript_marker: str) -> Path:
    script = tmp_path / "configured_forgeunit_worker.py"
    script.write_text(
        f"""
from pathlib import Path
import json
import os
import sys

_ = sys.stdin.read()
task_dir = Path(os.environ["FORGEUNIT_TASK_DIR"])
worker_result = Path(os.environ["FORGEUNIT_WORKER_RESULT"])
unit_id = os.environ["FORGEUNIT_UNIT"]

(task_dir / "package").mkdir(exist_ok=True)
(task_dir / "evidence").mkdir(exist_ok=True)
(task_dir / "package" / "SKILL.md").write_text({VALID_CODEX_SKILL!r}, encoding="utf-8")
(task_dir / "evidence" / "transcript.md").write_text({transcript_marker!r} + "\\n", encoding="utf-8")
(task_dir / "evidence" / "manifest.json").write_text(json.dumps({{
    "schema": "forgeunit.worker_evidence_manifest",
    "version": "0.6",
    "unit_id": unit_id,
    "status": "completed",
    "output_artifacts": [
        {{"path": "package/SKILL.md", "kind": "codex_skill", "summary": "configured fixture skill package"}}
    ],
    "evidence_artifacts": [
        {{"path": "evidence/transcript.md", "kind": "transcript", "summary": "configured fixture transcript"}}
    ],
    "changed_files": ["package/SKILL.md", "evidence/transcript.md", "evidence/manifest.json"],
    "commands": [{{"command": "configured test worker", "exit_code": 0, "summary": "configured worker passed"}}],
    "usage": None,
    "usage_unavailable_reason": "external_worker_no_provider_telemetry"
}}, indent=2), encoding="utf-8")
worker_result.write_text(json.dumps({{
    "status": "completed",
    "output_artifacts": [
        {{"path": "package/SKILL.md", "kind": "codex_skill", "summary": "configured fixture skill package"}}
    ],
    "boundary_evidence": [
        {{"path": "evidence/transcript.md", "kind": "transcript", "summary": "configured fixture transcript"}},
        {{"path": "evidence/manifest.json", "kind": "worker_evidence_manifest", "summary": "manifest"}}
    ],
    "changed_files": ["package/SKILL.md", "evidence/transcript.md", "evidence/manifest.json"],
    "usage": None,
    "usage_unavailable_reason": "external_worker_no_provider_telemetry"
}}, indent=2), encoding="utf-8")
""".strip(),
        encoding="utf-8",
    )
    return script


def _write_api_failing_worker(
    tmp_path: Path,
    *,
    stdout_marker: str,
    stderr_marker: str,
    transcript_marker: str,
) -> Path:
    script = tmp_path / "real_failing_forgeunit_worker.py"
    script.write_text(
        f"""
from pathlib import Path
import os
import sys

task_dir = Path(os.environ["FORGEUNIT_TASK_DIR"])
(task_dir / "evidence").mkdir(exist_ok=True)
(task_dir / "evidence" / "transcript.md").write_text({transcript_marker!r} + "\\n", encoding="utf-8")
print({stdout_marker!r})
print({stderr_marker!r}, file=sys.stderr)
raise SystemExit(17)
""".strip(),
        encoding="utf-8",
    )
    return script


def _create_and_approve_frontdesk_job(
    api: SkillFoundryAPI,
    job_id: str,
    *,
    message: str = "Build a governed status skill.",
) -> None:
    created = api.handle(
        "POST",
        "/frontdesk/jobs",
        body={"job_id": job_id, "message": message},
    ).json()
    assert created["status"] == "await_user_plan_review"

    approved = api.handle(
        "POST",
        f"/frontdesk/jobs/{job_id}/plan-review",
        body={"decision": "approve", "reason": "The governed plan is ready to build."},
    ).json()
    assert approved["status"] == "route_to_build"
    assert approved["state"]["readiness"] == "frozen"


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


def test_frontdesk_api_writes_inline_risk_policy_before_manifest_freeze(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = SkillFoundryAPI(tmp_path / "runs")
    job_id = "frontdesk-risk-policy"

    created = api.create_frontdesk_job(
        {
            "job_id": job_id,
            "message": "Build a privacy-sensitive local Codex skill.",
            "risk_policy": {
                "policy_id": "test-risk-policy",
                "raw_sensitive_payload_included": False,
                "required_controls": ["No raw transcript persistence", "Human review summary"],
            },
        }
    )

    assert created["state"]["frontdesk_budget_ref"] == "frontdesk/budget.json"
    run_root = tmp_path / "runs" / job_id
    risk_policy_path = run_root / "frontdesk" / "risk_policy.json"
    budget_path = run_root / "frontdesk" / "budget.json"
    assert risk_policy_path.is_file()
    budget = FrontDeskConfig.from_json(budget_path.read_text(encoding="utf-8"))
    assert budget.risk_policy_ref == "frontdesk/risk_policy.json"

    manifest = json.loads((run_root / "artifact_manifest.json").read_text(encoding="utf-8"))
    by_path = {record["path"]: record for record in manifest["artifacts"]}
    assert by_path["frontdesk/risk_policy.json"]["sha256"] == sha256_file(risk_policy_path)
    assert by_path["frontdesk/budget.json"]["sha256"] == sha256_file(budget_path)


def test_frontdesk_api_offline_goal_harness_preserves_request_semantics_in_frozen_inputs(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = SkillFoundryAPI(tmp_path / "runs")

    created = api.handle(
        "POST",
        "/frontdesk/jobs",
        body={
            "job_id": "frontdesk-semantic-request",
            "message": (
                "Build a governed Codex skill for analyzing pasted pytest failures and returning "
                "root cause, minimal fix, and verification steps."
            ),
        },
    ).json()

    assert created["status"] == "await_user_plan_review"
    run_root = tmp_path / "runs" / "frontdesk-semantic-request"
    brief = json.loads((run_root / "frontdesk" / "core_need_brief.json").read_text(encoding="utf-8"))
    draft_spec_text = (run_root / "frontdesk" / "draft_skill_spec.yaml").read_text(encoding="utf-8")
    solution_plan = json.loads((run_root / "frontdesk" / "solution_plan.json").read_text(encoding="utf-8"))

    for term in ("pytest", "failures", "root cause", "verification steps"):
        assert term in brief["problem_statement"]
        assert term in draft_spec_text
    assert "pytest" in solution_plan["proposed_skill_name"].lower()
    assert solution_plan["proposed_skill_name"] != "Governed Requirement Skill"

    approved = api.handle(
        "POST",
        "/frontdesk/jobs/frontdesk-semantic-request/plan-review",
        body={"decision": "approve", "reason": "The semantic plan matches the requested pytest workflow."},
    ).json()

    assert approved["status"] == "route_to_build"
    skill_spec_text = (run_root / "skill_spec.yaml").read_text(encoding="utf-8")
    worker_input = (run_root / "worker_input.md").read_text(encoding="utf-8")
    assert "pytest" in skill_spec_text
    assert "failures" in skill_spec_text
    assert "pytest" in worker_input
    assert "frontdesk-governed-skill" not in skill_spec_text


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


def test_frontdesk_api_builds_frozen_job_through_forgeunit_vnext_without_raw_leakage(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = SkillFoundryAPI(tmp_path / "runs")
    marker = "RAW_API_FORGEUNIT_VNEXT_MARKER_SHOULD_NOT_LEAK"
    job_id = "frontdesk-forgeunit-vnext-build"

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
    assert payload["build_path"]["mode"] == "forgeunit_skillfoundry_vnext"
    assert payload["build_path"]["canonical"] is True
    assert payload["forgeunit_skillfoundry_summary_ref"] == FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    assert payload["forgeunit_skillfoundry_graph_state_ref"] == FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF
    assert payload["forgeunit_skillfoundry_product_state_ref"] == FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF
    assert payload["graph_v2_state_ref"] is None
    assert payload["final_report"]["final_status"] == "registered"
    assert payload["forgeunit_skillfoundry_summary"]["stage"] == "emit_report"
    assert payload["forgeunit_skillfoundry_summary"]["status"] == "report_emitted"
    assert payload["forgeunit_skillfoundry_summary"]["verification"]["passed"] is True
    assert payload["forgeunit_skillfoundry_summary"]["registry"]["approved"] is True
    assert payload["forgeunit_skillfoundry_summary"]["trust_boundaries"]["command_string_included"] is False

    run_root = tmp_path / "runs" / job_id
    graph_state_path = run_root / FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF
    product_state_path = run_root / FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF
    summary_path = run_root / FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    assert graph_state_path.is_file()
    assert product_state_path.is_file()
    assert summary_path.is_file()
    persisted_state = json.loads(graph_state_path.read_text(encoding="utf-8"))
    assert persisted_state["schema_version"] == GRAPH_STATE_SCHEMA_VERSION
    assert persisted_state["trust_boundaries"]["command_string_included"] is False
    assert marker not in json.dumps(persisted_state, sort_keys=True)

    status = api.handle("GET", f"/jobs/{job_id}/contextforge").json()
    assert status["refs"]["forgeunit_skillfoundry_summary"]["exists"] is True
    assert status["refs"]["forgeunit_skillfoundry_graph_state"]["exists"] is True
    assert status["refs"]["forgeunit_skillfoundry_product_state"]["exists"] is True
    assert status["refs"]["graph_v2_state"]["exists"] is False
    assert status["status"]["forgeunit_skillfoundry"]["registry_approved"] is True
    assert status["status"]["forgeunit_skillfoundry"]["verification_status"] == "passed"
    assert status["status"]["graph"]["raw_frontdesk_conversation_forbidden"] is True
    assert status["status"]["registry"]["approved"] is True
    assert marker not in json.dumps(status, sort_keys=True)

    job = api.handle("GET", f"/jobs/{job_id}").json()
    assert job["status"] == "registered"
    assert job["build_path"]["mode"] == "forgeunit_skillfoundry_vnext"
    assert job["package_downloadable"] is True

    html_response = api.handle("GET", f"/jobs/{job_id}", headers={"Accept": "text/html"})
    html = html_response.body.decode("utf-8")
    assert html_response.status == 200
    assert html_response.content_type.startswith("text/html")
    assert "forgeunit_skillfoundry_vnext" in html
    assert "registered" in html
    assert "Download package" in html
    assert f"/jobs/{job_id}/package.zip" in html
    assert f"/jobs/{job_id}/contextforge" in html
    assert marker not in html
    assert "raw_provider_payload" not in html
    assert "worker_transcript" not in html


def test_frontdesk_api_uses_constructor_configured_forgeunit_command_without_leaking(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    transcript_marker = "CONFIGURED_CONSTRUCTOR_TRANSCRIPT_SHOULD_NOT_LEAK"
    script = _write_api_configured_worker(tmp_path, transcript_marker=transcript_marker)
    api = SkillFoundryAPI(tmp_path / "runs", forgeunit_command=f"{sys.executable} {script}")
    job_id = "frontdesk-constructor-forgeunit-command"

    api.handle(
        "POST",
        "/frontdesk/jobs",
        body={"job_id": job_id, "message": "Build a governed status skill."},
    )
    api.handle(
        "POST",
        f"/frontdesk/jobs/{job_id}/plan-review",
        body={"decision": "approve", "reason": "The governed plan is ready to build."},
    )

    build_response = api.handle("POST", f"/frontdesk/jobs/{job_id}/build", body={})

    assert build_response.status == 200
    serialized = build_response.body.decode("utf-8")
    assert script.as_posix() not in serialized
    assert script.name not in serialized
    assert transcript_marker not in serialized
    payload = build_response.json()
    assert payload["status"] == "registered"
    assert payload["build_path"]["mode"] == "forgeunit_skillfoundry_vnext"
    assert payload["forgeunit_skillfoundry_summary"]["mode"] == "command_bridge"
    assert payload["forgeunit_skillfoundry_summary"]["verification"]["passed"] is True
    assert payload["forgeunit_skillfoundry_summary"]["trust_boundaries"]["command_string_included"] is False

    status = api.handle("GET", f"/jobs/{job_id}/contextforge").json()
    status_serialized = json.dumps(status, sort_keys=True)
    assert status["status"]["forgeunit_skillfoundry"]["registry_approved"] is True
    assert script.as_posix() not in status_serialized
    assert script.name not in status_serialized
    assert transcript_marker not in status_serialized


def test_frontdesk_api_normalizes_relative_operator_forgeunit_command_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "scripts" / "relative_worker.py"
    script.parent.mkdir()
    script.write_text("print('worker')\n", encoding="utf-8")
    api = SkillFoundryAPI(
        tmp_path / "runs",
        forgeunit_command=f"{sys.executable} scripts/relative_worker.py --flag value",
    )
    workspace = initialize_job_workspace(api._runs_root_resolved, "frontdesk-relative-command")

    configured_command, _ = api._frontdesk_forgeunit_commands(workspace, {})
    payload_command, _ = api._frontdesk_forgeunit_commands(
        workspace,
        {"command": f"{sys.executable} scripts/relative_worker.py --flag value"},
    )

    assert shlex.split(configured_command)[1] == script.resolve().as_posix()
    assert shlex.split(payload_command)[1] == script.resolve().as_posix()


def test_frontdesk_api_explicit_fake_mode_happy_uses_offline_vnext_without_leaking(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = SkillFoundryAPI(tmp_path / "runs")
    job_id = "frontdesk-explicit-fake-happy"
    _create_and_approve_frontdesk_job(api, job_id)

    build_response = api.handle("POST", f"/frontdesk/jobs/{job_id}/build", body={"fake_mode": "happy"})

    assert build_response.status == 200
    serialized = build_response.body.decode("utf-8")
    assert "fake_api_codex_exec.py" not in serialized
    payload = build_response.json()
    assert payload["status"] == "registered"
    assert payload["build_path"]["mode"] == "forgeunit_skillfoundry_vnext"
    assert payload["forgeunit_skillfoundry_summary"]["mode"] == "command_bridge"
    assert payload["forgeunit_skillfoundry_summary"]["verification"]["passed"] is True
    assert payload["forgeunit_skillfoundry_summary"]["registry"]["approved"] is True
    assert payload["forgeunit_skillfoundry_summary"]["trust_boundaries"]["command_string_included"] is False


def test_frontdesk_api_explicit_fake_mode_repair_uses_offline_vnext_without_leaking(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = SkillFoundryAPI(tmp_path / "runs")
    job_id = "frontdesk-explicit-fake-repair"
    _create_and_approve_frontdesk_job(api, job_id)

    build_response = api.handle("POST", f"/frontdesk/jobs/{job_id}/build", body={"fake_mode": "repair"})

    assert build_response.status == 200
    serialized = build_response.body.decode("utf-8")
    assert "fake_api_bad_codex_exec.py" not in serialized
    assert "fake_api_repair_codex_exec.py" not in serialized
    payload = build_response.json()
    assert payload["status"] == "registered"
    assert payload["build_path"]["mode"] == "forgeunit_skillfoundry_vnext"
    assert payload["forgeunit_skillfoundry_summary"]["mode"] == "repair_command_bridge"
    assert payload["forgeunit_skillfoundry_summary"]["verification"]["passed"] is True
    assert payload["forgeunit_skillfoundry_summary"]["registry"]["approved"] is True
    assert payload["forgeunit_skillfoundry_summary"]["trust_boundaries"]["command_string_included"] is False


def test_frontdesk_api_redacts_forgeunit_vnext_build_failure_details(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    command_marker = "SECRET_CONFIGURED_COMMAND_SHOULD_NOT_LEAK"
    script_name = "secret_configured_worker.py"
    stdout_marker = "SECRET_STDOUT_SHOULD_NOT_LEAK"
    stderr_marker = "SECRET_STDERR_SHOULD_NOT_LEAK"
    transcript_marker = "SECRET_TRANSCRIPT_SHOULD_NOT_LEAK"
    api = SkillFoundryAPI(
        tmp_path / "runs",
        forgeunit_command=f"{sys.executable} {tmp_path / script_name} --token {command_marker}",
    )
    job_id = "frontdesk-vnext-failure-redaction"
    _create_and_approve_frontdesk_job(api, job_id)

    import forgeunit_skillfoundry

    seen: dict[str, str] = {}

    def fail_build(*_args, **kwargs):
        seen["command"] = str(kwargs.get("command"))
        raise RuntimeError(
            "worker failed with "
            f"{command_marker} {script_name} {stdout_marker} {stderr_marker} {transcript_marker}"
        )

    monkeypatch.setattr(forgeunit_skillfoundry, "run_frozen_frontdesk_skill_factory", fail_build)

    build_response = api.handle("POST", f"/frontdesk/jobs/{job_id}/build", body={})

    assert build_response.status == 500
    assert command_marker in seen["command"]
    payload = build_response.json()
    assert payload["error"]["code"] == "frontdesk_build_failed"
    assert payload["error"]["message"] == (
        "frontdesk ForgeUnit vNext build failed before producing a verified refs-only result"
    )
    serialized = build_response.body.decode("utf-8")
    assert command_marker not in serialized
    assert script_name not in serialized
    assert stdout_marker not in serialized
    assert stderr_marker not in serialized
    assert transcript_marker not in serialized


def test_frontdesk_api_redacts_real_failing_subprocess_command_boundary(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    command_marker = "SECRET_REAL_COMMAND_SHOULD_NOT_LEAK"
    stdout_marker = "SECRET_REAL_STDOUT_SHOULD_NOT_LEAK"
    stderr_marker = "SECRET_REAL_STDERR_SHOULD_NOT_LEAK"
    transcript_marker = "SECRET_REAL_TRANSCRIPT_SHOULD_NOT_LEAK"
    script = _write_api_failing_worker(
        tmp_path,
        stdout_marker=stdout_marker,
        stderr_marker=stderr_marker,
        transcript_marker=transcript_marker,
    )
    api = SkillFoundryAPI(
        tmp_path / "runs",
        forgeunit_command=f"{sys.executable} {script} --secret {command_marker}",
    )
    job_id = "frontdesk-real-failing-command"
    _create_and_approve_frontdesk_job(api, job_id)

    build_response = api.handle("POST", f"/frontdesk/jobs/{job_id}/build", body={})

    assert build_response.status == 500
    payload = build_response.json()
    assert payload["error"]["code"] == "frontdesk_build_failed"
    assert payload["error"]["message"] == (
        "frontdesk ForgeUnit vNext build failed before producing a verified refs-only result"
    )
    serialized = build_response.body.decode("utf-8")
    assert command_marker not in serialized
    assert script.as_posix() not in serialized
    assert script.name not in serialized
    assert stdout_marker not in serialized
    assert stderr_marker not in serialized
    assert transcript_marker not in serialized

    run_root = tmp_path / "runs" / job_id
    transcript = run_root / "evidence" / "transcript.md"
    assert transcript.read_text(encoding="utf-8").strip() == transcript_marker
    command_logs = list((run_root / ".forgeunit" / "runs").glob("*/workers/*_codex*_command_result.txt"))
    assert command_logs
    log_text = "\n".join(path.read_text(encoding="utf-8") for path in command_logs)
    assert stdout_marker in log_text
    assert stderr_marker in log_text


def test_frontdesk_api_redacts_forgeunit_vnext_missing_summary_details(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    summary_marker = "SECRET_SUMMARY_ERROR_SHOULD_NOT_LEAK"
    api = SkillFoundryAPI(tmp_path / "runs")
    job_id = "frontdesk-vnext-summary-redaction"
    _create_and_approve_frontdesk_job(api, job_id)

    import forgeunit_skillfoundry

    def fail_summary(_workspace):
        raise RuntimeError(f"summary reader exposed {summary_marker}")

    monkeypatch.setattr(forgeunit_skillfoundry, "read_evidence_summary", fail_summary)

    build_response = api.handle("POST", f"/frontdesk/jobs/{job_id}/build", body={})

    assert build_response.status == 500
    payload = build_response.json()
    assert payload["error"]["code"] == "frontdesk_build_missing_summary"
    assert payload["error"]["message"] == "frontdesk ForgeUnit vNext build did not write a valid refs-only summary"
    assert summary_marker not in build_response.body.decode("utf-8")


def test_frontdesk_api_uses_env_configured_forgeunit_command_without_leaking(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    transcript_marker = "CONFIGURED_ENV_TRANSCRIPT_SHOULD_NOT_LEAK"
    script = _write_api_configured_worker(tmp_path, transcript_marker=transcript_marker)
    monkeypatch.setenv(FORGEUNIT_COMMAND_ENV, f"{sys.executable} {script}")
    api = SkillFoundryAPI(tmp_path / "runs")
    job_id = "frontdesk-env-forgeunit-command"

    api.handle(
        "POST",
        "/frontdesk/jobs",
        body={"job_id": job_id, "message": "Build a governed status skill."},
    )
    api.handle(
        "POST",
        f"/frontdesk/jobs/{job_id}/plan-review",
        body={"decision": "approve", "reason": "The governed plan is ready to build."},
    )

    build_response = api.handle("POST", f"/frontdesk/jobs/{job_id}/build", body={})

    assert build_response.status == 200
    serialized = build_response.body.decode("utf-8")
    assert script.as_posix() not in serialized
    assert script.name not in serialized
    assert transcript_marker not in serialized
    payload = build_response.json()
    assert payload["status"] == "registered"
    assert payload["build_path"]["mode"] == "forgeunit_skillfoundry_vnext"
    assert payload["forgeunit_skillfoundry_summary"]["mode"] == "command_bridge"
    assert payload["forgeunit_skillfoundry_summary"]["verification"]["passed"] is True
    assert payload["forgeunit_skillfoundry_summary"]["trust_boundaries"]["command_string_included"] is False

    status = api.handle("GET", f"/jobs/{job_id}/contextforge").json()
    status_serialized = json.dumps(status, sort_keys=True)
    assert status["status"]["forgeunit_skillfoundry"]["registry_approved"] is True
    assert script.as_posix() not in status_serialized
    assert script.name not in status_serialized
    assert transcript_marker not in status_serialized


def test_frontdesk_api_can_opt_into_legacy_graph_v2_build(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = SkillFoundryAPI(tmp_path / "runs")
    job_id = "frontdesk-graph-v2-build"

    created = api.handle(
        "POST",
        "/frontdesk/jobs",
        body={"job_id": job_id, "message": "Build a governed status skill."},
    ).json()
    assert created["status"] == "await_user_plan_review"

    approved = api.handle(
        "POST",
        f"/frontdesk/jobs/{job_id}/plan-review",
        body={"decision": "approve", "reason": "The governed plan is ready to build."},
    ).json()
    assert approved["status"] == "route_to_build"

    build_response = api.handle(
        "POST",
        f"/frontdesk/jobs/{job_id}/build",
        body={"build_mode": "graph_v2"},
    )

    assert build_response.status == 200
    payload = build_response.json()
    assert payload["status"] == "registered"
    assert payload["build_path"]["mode"] == "graph_v2_goal_harness"
    assert payload["graph_v2_state_ref"] == GRAPH_V2_STATE_REF
    assert payload["graph_v2_state"]["stage"] == "emit_report"
    assert payload["graph_v2_state"]["status"] == "report_emitted"
    validate_v2_graph_state(payload["graph_v2_state"])


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
