# Agent Brief WP13: Front Desk Schema + Workspace

## Mission

Implement SkillFoundry WP13: Front Desk schema and workspace foundation for the future real LLM requirements clarification layer.

This is an implementation task for a `gpt-5.5` / `xhigh` worker. The main Codex thread will review independently as architect.

## Context

Repository: `/home/mansteinl/skillfoundry`

Read first:

- `docs/FRONT_DESK_AGENT_ROADMAP.md`
- `src/skillfoundry/schema.py`
- `src/skillfoundry/workspace.py`
- `tests/test_schema.py`
- `tests/test_workspace.py`

Current state:

- WP0-WP12 are complete.
- WP13 must create schema/workspace foundations only.
- WP14 will implement the LLM Requirements Elicitor.
- WP15 will implement Spec Auditor and deterministic FrontDeskFreezeGate.

## Scope

WP13 owns:

- Front Desk dataclass-backed schema models.
- Deterministic validation for those schema models.
- Front Desk workspace artifact layout under `runs/<job_id>/frontdesk/`.
- Conversation append helper.
- Front Desk artifact manifest registration.
- Tests for schema round-trip, validation, path safety, manifest coverage, and refs-only state.

Recommended files:

- `src/skillfoundry/frontdesk_schema.py`
- `src/skillfoundry/frontdesk_workspace.py`
- `tests/test_frontdesk_schema.py`
- `tests/test_frontdesk_workspace.py`
- update `src/skillfoundry/__init__.py` exports if useful

Keep changes narrow. Do not implement real provider calls, LLM prompts, Auditor logic, FreezeGate logic, QA coverage, or real builder integration.

## Required Schema

Implement schema objects equivalent to:

- `ConversationTurn`
- `StructuredQuestion`
- `ElicitationReport`
- `AcceptanceCriterion`
- `AcceptanceCriteriaSet`
- `FeasibilityReport`
- `SpecAuditReport`
- `FreezeManifest`
- `FrontDeskState`
- `FrontDeskConfig`

Use the repo's existing schema style:

- dataclass models;
- strict JSON compatibility;
- `to_dict`, `from_dict`, `to_json`, `from_json`, YAML helpers where appropriate;
- unknown fields rejected;
- deterministic validation;
- no broad ad hoc string parsing.

Validation expectations:

- score fields must be finite numbers in `[0.0, 1.0]`;
- IDs and refs must be non-empty strings;
- enum-like fields must reject unknown values;
- `AcceptanceCriteriaSet` must reject duplicate criterion IDs;
- `ConversationTurn` must reject empty role/content and invalid roles;
- `FrontDeskState` must store refs only, not raw conversation/model output;
- `FrontDeskConfig` must validate positive budget/limit values;
- `FreezeManifest` must validate artifact refs and hashes.

## Required Workspace Behavior

Implement helpers that can:

- initialize `frontdesk/` inside an existing `JobWorkspace`;
- create these files:

```text
frontdesk/conversation.jsonl
frontdesk/clarification_summary.md
frontdesk/budget.json
frontdesk/risk_report.json
```

- append a `ConversationTurn` to `conversation.jsonl`;
- read conversation turns back;
- write frontdesk artifacts such as:

```text
frontdesk/elicitation_report_001.json
frontdesk/spec_audit_report_001.json
frontdesk/draft_skill_spec.yaml
frontdesk/acceptance_criteria.yaml
frontdesk/feasibility_report.json
frontdesk/freeze_gate_result.json
frontdesk/freeze_manifest.json
```

- add frontdesk artifact records to the existing `artifact_manifest.json`;
- preserve existing locked input behavior;
- reject path traversal and absolute paths through existing security helpers.

The frontdesk files do not become locked inputs in WP13 unless explicitly intended. They must be recorded as artifacts/provenance.

## Non-goals

Do not implement:

- OpenAI API calls;
- ContextForge LLM invocation;
- Requirements Elicitor prompt logic;
- Spec Auditor prompt logic;
- FrontDeskFreezeGate decision logic;
- acceptance coverage computation;
- Registry gate changes;
- CodexWorker or CodexAgentThreadWorker integration;
- web UI.

## Required Tests

Automated tests must prove:

- every new schema can JSON round-trip;
- unknown fields fail;
- invalid enum values fail;
- invalid score values fail;
- duplicate acceptance criterion IDs fail;
- `FrontDeskState` rejects raw conversation/model output fields and stores refs only;
- frontdesk workspace initialization creates the expected files/directories;
- appending conversation turns preserves order and validates each turn;
- frontdesk artifact writes update `artifact_manifest.json`;
- frontdesk path traversal is rejected;
- existing locked input tamper checks still pass after frontdesk initialization.

Full test suite must pass:

```bash
.venv/bin/python -m pytest -q
```

## Acceptance Criteria

- `src/skillfoundry/frontdesk_schema.py` exists.
- `src/skillfoundry/frontdesk_workspace.py` exists.
- `tests/test_frontdesk_schema.py` exists.
- `tests/test_frontdesk_workspace.py` exists.
- Full pytest suite passes.
- Default tests remain deterministic/offline.
- No external provider, network, or live Codex dependency is introduced.
- Existing WP0-WP12 behavior remains compatible.

## Expected Final Response From Worker

List:

- files changed;
- schema objects implemented;
- workspace helpers implemented;
- tests added;
- tests run and exact result;
- any deviations or blockers.
