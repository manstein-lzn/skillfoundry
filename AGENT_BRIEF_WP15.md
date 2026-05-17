# Agent Brief WP15: Spec Auditor + FrontDeskFreezeGate

## Mission

Implement SkillFoundry WP15: the Spec Auditor Agent boundary plus deterministic FrontDeskFreezeGate.

This is an implementation task for a `gpt-5.5` / `xhigh` worker. The main Codex thread will review independently as architect.

## Context

Repository: `/home/mansteinl/skillfoundry`

Read first:

- `docs/FRONT_DESK_AGENT_ROADMAP.md`
- `AGENT_BRIEF_WP13.md`
- `AGENT_BRIEF_WP14.md`
- `src/skillfoundry/frontdesk_schema.py`
- `src/skillfoundry/frontdesk_workspace.py`
- `src/skillfoundry/frontdesk.py`
- `src/skillfoundry/schema.py`
- `src/skillfoundry/workspace.py`
- `tests/test_frontdesk_elicitor.py`

Current state:

- WP13 schema/workspace foundation is complete.
- WP14 Requirements Elicitor is complete.
- WP15 must add Spec Auditor and deterministic FreezeGate.
- WP16 acceptance criteria to QA/Verifier remains future.
- WP17 real builder remains future.

## Scope

WP15 owns:

- Spec Auditor prompt/input construction.
- ContextForge owned LLM invocation for audit.
- Structured JSON parsing into `SpecAuditReport` and `FeasibilityReport`.
- Deterministic fail-closed behavior for audit failures.
- Deterministic `FrontDeskFreezeGate` that decides whether specs can be frozen.
- Writing root-level frozen inputs:
  - `skill_spec.yaml`
  - `acceptance_criteria.yaml`
  - `verification_spec.yaml`
  - `worker_input.md`
  - `build_contract.yaml`
- Writing:
  - `frontdesk/spec_audit_report_<round>.json`
  - `frontdesk/feasibility_report.json`
  - `frontdesk/freeze_gate_result.json`
  - `frontdesk/freeze_manifest.json`
- Updating `artifact_manifest.json` with locked records for frozen inputs and provenance records for frontdesk artifacts.
- Tests using deterministic fake/model clients only.

Recommended files:

- update `src/skillfoundry/frontdesk.py`
- `tests/test_frontdesk_auditor.py`
- `tests/test_frontdesk_freeze_gate.py`
- update `src/skillfoundry/__init__.py` exports if useful

Touch WP13 schema/workspace only for small compatibility fixes if strictly required.

## Non-goals

Do not implement:

- direct OpenAI SDK integration;
- real network/provider calls in tests;
- QA coverage computation;
- Registry gate changes;
- CodexWorker/CodexAgentThreadWorker integration;
- actual builder invocation;
- UI.

## Required Spec Auditor Behavior

Implement an API equivalent to:

```python
from skillfoundry import SpecAuditor

result = SpecAuditor().audit(
    workspace,
    round_index=1,
    client=scripted_model_client,
)
```

The exact names may vary, but equivalent behavior must exist.

The Auditor must read:

- `frontdesk/conversation.jsonl`;
- `frontdesk/elicitation_report_<round>.json`;
- `frontdesk/acceptance_criteria.yaml` when present;
- `frontdesk/draft_skill_spec.yaml` when present;
- `frontdesk/clarification_summary.md`;
- platform boundary instructions.

The Auditor call must go through:

```text
SkillFoundryContextAdapter.call_owned_llm(...)
```

Required metadata:

- agent role: `spec_auditor`;
- round index;
- job id;
- output schema names: `SpecAuditReport` and `FeasibilityReport`;
- frontdesk artifact refs;
- trust boundary note.

The model response may be a JSON object containing:

```json
{
  "spec_audit_report": {...},
  "feasibility_report": {...}
}
```

or direct report fields if simpler. The implementation must validate and write both reports.

Fail closed on provider error, invalid JSON, invalid schema, invalid score, unknown decision, or mismatched refs. Do not fake an approval.

## Required FreezeGate Behavior

Implement an API equivalent to:

```python
from skillfoundry import FrontDeskFreezeGate

result = FrontDeskFreezeGate().evaluate_and_freeze(workspace, round_index=1)
```

The gate is deterministic and must not call any model.

Inputs:

- latest ElicitationReport;
- latest SpecAuditReport;
- FeasibilityReport;
- AcceptanceCriteriaSet;
- draft skill spec artifact;
- FrontDeskConfig;
- root workspace.

Minimum freeze requirements:

- Elicitation report exists and has `readiness_guess == "ready_for_audit"`;
- SpecAuditReport exists and has `decision == "approved"`;
- clarity, feasibility, and testability scores meet `FrontDeskConfig` thresholds;
- FeasibilityReport exists and is not infeasible/human-review-required;
- no unresolved missing requirements;
- no unsafe assumptions;
- `AcceptanceCriteriaSet` has unique criteria IDs;
- every `must` criterion has required evidence or a manual/human-review path;
- no `must` criterion relies only on `llm_judge`;
- no `manual_check` / `human_review` must criterion can freeze without human review authority;
- `draft_skill_spec.yaml` can be converted to a valid `SkillSpec`;
- generated `VerificationSpec` is valid;
- generated `BuildContract` is valid and includes locked input hashes;
- all frozen artifacts are written and represented in manifest/hash records.

When the gate passes:

- write root-level:
  - `skill_spec.yaml`
  - `acceptance_criteria.yaml`
  - `verification_spec.yaml`
  - `worker_input.md`
  - `build_contract.yaml`
- write `frontdesk/freeze_gate_result.json` with `decision == "freeze"`;
- write `frontdesk/freeze_manifest.json`;
- update `artifact_manifest.json`;
- keep existing `workspace.check_locked_inputs()` passing.

When the gate fails:

- write `frontdesk/freeze_gate_result.json` with `decision`:
  - `ask_user`
  - `human_review_required`
  - `reject`
- include machine-readable `blocking_reasons`;
- do not write or overwrite root frozen inputs;
- do not trigger builder.

## Required Tests

Automated tests must prove:

- `SpecAuditor` API is exported if intended.
- Auditor uses ContextForge owned LLM call and replay artifact.
- Auditor writes `frontdesk/spec_audit_report_001.json` and `frontdesk/feasibility_report.json`.
- Auditor provider exception fails closed and writes `frontdesk/spec_audit_failure_001.json`.
- Auditor invalid JSON/schema fails closed and does not write successful audit.
- FreezeGate freezes a happy-path approved spec and writes all root frozen artifacts.
- FreezeGate writes `freeze_manifest.json` with refs/hashes.
- FreezeGate updates artifact manifest with locked records for frozen inputs.
- FreezeGate keeps existing locked input tamper checks working.
- FreezeGate blocks when Auditor is not approved.
- FreezeGate blocks when score thresholds are not met.
- FreezeGate blocks when must criteria lack evidence.
- FreezeGate blocks when a must criterion uses only `llm_judge`.
- FreezeGate sends manual/human-review must criteria to human review.
- FreezeGate does not call model clients.
- Full `.venv/bin/python -m pytest -q` passes.

## Acceptance Criteria

- `SpecAuditor` or equivalent exists.
- `FrontDeskFreezeGate` or equivalent exists.
- `tests/test_frontdesk_auditor.py` exists.
- `tests/test_frontdesk_freeze_gate.py` exists.
- Auditor uses `SkillFoundryContextAdapter.call_owned_llm`.
- FreezeGate is deterministic and makes no model calls.
- Default tests remain deterministic/offline.
- No direct OpenAI SDK dependency is introduced.
- No QA coverage, Registry gate, real builder, or UI implementation is introduced.
- Full pytest suite passes.

## Expected Final Response From Worker

List:

- files changed;
- Auditor API shape;
- FreezeGate API shape;
- ContextForge evidence behavior;
- freeze/fail behavior;
- tests added;
- tests run and exact result;
- any deviations or blockers.
