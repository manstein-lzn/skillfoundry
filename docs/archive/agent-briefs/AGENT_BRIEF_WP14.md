# Agent Brief WP14: LLM Requirements Elicitor Agent

## Mission

Implement SkillFoundry WP14: a real Requirements Elicitor Agent boundary that uses SkillFoundry-owned LLM calls through ContextForge, while keeping default tests deterministic and offline.

This is an implementation task for a `gpt-5.5` / `xhigh` worker. The main Codex thread will review independently as architect.

## Context

Repository: `/home/mansteinl/skillfoundry`

Read first:

- `docs/FRONT_DESK_AGENT_ROADMAP.md`
- `AGENT_BRIEF_WP13.md`
- `src/skillfoundry/frontdesk_schema.py`
- `src/skillfoundry/frontdesk_workspace.py`
- `src/skillfoundry/context.py`
- `tests/test_context.py`
- `tests/test_frontdesk_schema.py`
- `tests/test_frontdesk_workspace.py`

Current state:

- WP13 schema/workspace foundation is complete.
- WP14 must implement the Elicitor only.
- WP15 will implement Spec Auditor and deterministic FrontDeskFreezeGate.
- WP16 will bridge Acceptance Criteria to QA/Verifier.
- WP17 will integrate a real builder.

## Scope

WP14 owns:

- Requirements Elicitor prompt/input construction.
- ContextForge owned LLM invocation for elicitation.
- Structured JSON response parsing into `ElicitationReport`.
- Deterministic fail-closed behavior on provider error, invalid JSON, invalid schema, or policy/budget violations.
- Writing elicitation reports and failure artifacts under `frontdesk/`.
- Tests using deterministic fake/model clients only.

Recommended files:

- `src/skillfoundry/frontdesk.py`
- `tests/test_frontdesk_elicitor.py`
- update `src/skillfoundry/__init__.py` exports if useful

Only touch WP13 schema/workspace files if a small, clearly required compatibility fix is necessary.

## Non-goals

Do not implement:

- direct OpenAI SDK integration;
- real network/provider calls in tests;
- Spec Auditor;
- FrontDeskFreezeGate decision logic;
- QA coverage computation;
- Registry gate changes;
- CodexWorker/CodexAgentThreadWorker integration;
- UI.

The Elicitor may accept an injected ContextForge-compatible model client. That client can later be backed by OpenAI API, but WP14 should not hard-code an OpenAI dependency.

## Required Behavior

Implement an API equivalent to:

```python
from skillfoundry import RequirementsElicitor

elicitor = RequirementsElicitor()
result = elicitor.elicit(
    workspace,
    round_index=1,
    client=scripted_model_client,
)
```

The exact names may vary, but equivalent behavior must exist.

### Prompt/Input Construction

The Elicitor must read:

- `frontdesk/conversation.jsonl`;
- `frontdesk/clarification_summary.md`;
- `frontdesk/budget.json` or `FrontDeskConfig`;
- platform boundary instructions from code constants or a small template;
- optional registry summary only as a clearly labeled trusted/untrusted block if implemented.

It must build a prompt/input text that explicitly separates:

- platform/developer instructions;
- schema/output contract;
- trusted SkillFoundry capability boundary;
- untrusted user conversation content;
- previous clarification summary.

Raw user text must not be treated as system/developer instruction.

### ContextForge Invocation

The Elicitor call must go through:

```text
SkillFoundryContextAdapter.call_owned_llm(...)
```

Required metadata:

- agent role: `requirements_elicitor`;
- round index;
- job id;
- output schema name;
- frontdesk artifact refs;
- trust boundary note.

The call must produce a ContextForge model call record and replay artifact.

### Structured Output

The model response text must be parsed as JSON and converted to `ElicitationReport`.

Required response shape:

```json
{
  "readiness_guess": "needs_clarification | ready_for_audit",
  "current_understanding": "...",
  "known_fields": {},
  "missing_fields": [],
  "risk_flags": [],
  "next_questions": [
    {
      "question_id": "Q-001",
      "text": "...",
      "missing_field_path": "input.source",
      "reason": "...",
      "priority": "must",
      "answer_type": "free_text",
      "blocks_build": true
    }
  ],
  "draft_skill_spec": {},
  "draft_acceptance_criteria": [],
  "assumptions": []
}
```

The implementation must:

- validate with `ElicitationReport`;
- set or verify `conversation_ref`;
- set `round_index`;
- enforce `max_followup_questions_per_round`;
- reject empty/generic questions such as a single vague "please provide more details" pattern where practical;
- ensure every question has a non-empty `missing_field_path`;
- write `frontdesk/elicitation_report_<round>.json` only after validation succeeds.

### Fail-Closed Behavior

On provider error, invalid JSON, schema validation failure, too many questions, or missing required question structure:

- do not write a successful elicitation report;
- write a machine-readable failure artifact such as `frontdesk/elicitation_failure_<round>.json`;
- return a result with status `fail_closed` or equivalent;
- preserve ContextForge replay evidence when a provider call occurred;
- do not generate a fake spec.

### Deterministic Tests

Tests must use scripted fake clients only. They must not call real providers, network, Codex, or external services.

## Required Tests

Automated tests must prove:

- API is exported if intended.
- Vague user request produces targeted `needs_clarification` questions.
- Clear request can produce `ready_for_audit`.
- Question count is capped by config.
- Every question is tied to a missing field path.
- Elicitation output is written to `frontdesk/elicitation_report_001.json` and manifest is updated.
- ContextForge records an owned model call and replay artifact for the Elicitor.
- Provider exception fails closed and writes failure artifact.
- Invalid JSON fails closed and does not write successful report.
- Schema-invalid JSON fails closed and does not write successful report.
- Prompt/input text clearly labels untrusted conversation and platform boundary.
- Full `.venv/bin/python -m pytest -q` passes.

## Acceptance Criteria

- `src/skillfoundry/frontdesk.py` exists.
- `tests/test_frontdesk_elicitor.py` exists.
- Elicitor uses `SkillFoundryContextAdapter.call_owned_llm`.
- Default tests remain deterministic/offline.
- No direct OpenAI SDK dependency is introduced.
- No Spec Auditor, FreezeGate, QA coverage, Registry gate, or real builder implementation is introduced.
- Full pytest suite passes.

## Expected Final Response From Worker

List:

- files changed;
- Elicitor API shape;
- ContextForge call/evidence behavior;
- failure behavior;
- tests added;
- tests run and exact result;
- any deviations or blockers.
