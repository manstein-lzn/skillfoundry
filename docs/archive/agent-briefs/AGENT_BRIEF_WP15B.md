# AGENT BRIEF WP15B: Front Desk LangGraph Loop

You are implementing WP15B in `/home/mansteinl/skillfoundry`.

## Goal

Turn the existing Front Desk parts into a deterministic, testable, refs-only multi-round loop:

```text
ask_user/new conversation
  -> RequirementsElicitor
  -> draft artifact materialization
  -> SpecAuditor
  -> FrontDeskFreezeGate
  -> freeze | ask_user | human_review | reject | fail_closed
```

WP13-WP15 are already implemented. Do not redo them. Build the smallest production-shaped loop around them.

## Current Building Blocks

Existing code:

- `src/skillfoundry/frontdesk.py`
  - `RequirementsElicitor`
  - `SpecAuditor`
  - `FrontDeskFreezeGate`
  - constants for report refs and frozen refs
- `src/skillfoundry/frontdesk_schema.py`
  - `FrontDeskState`
  - `FrontDeskConfig`
  - `ElicitationReport`
  - `AcceptanceCriteriaSet`
  - `SpecAuditReport`
  - `FeasibilityReport`
- `src/skillfoundry/frontdesk_workspace.py`
  - `FrontDeskWorkspace`
  - `initialize_frontdesk_workspace`
  - conversation and frontdesk artifact helpers
- Existing tests:
  - `tests/test_frontdesk_schema.py`
  - `tests/test_frontdesk_workspace.py`
  - `tests/test_frontdesk_elicitor.py`
  - `tests/test_frontdesk_auditor.py`
  - `tests/test_frontdesk_freeze_gate.py`

Roadmap:

- `docs/FRONT_DESK_AGENT_ROADMAP.md`
- `docs/FRONT_DESK_ROADMAP_AUDIT.md`

## Required Deliverables

Implement these deliverables only:

1. A Front Desk loop orchestration API.
   - Preferred: `src/skillfoundry/frontdesk_loop.py`.
   - It may use LangGraph if practical, but must expose a simple deterministic Python API that tests can call without a running server.
   - Suggested public objects:
     - `FrontDeskLoop`
     - `FrontDeskLoopResult`
     - `run_frontdesk_round(...)`
     - optional `build_frontdesk_graph(...)` / `compile_frontdesk_graph(...)`

2. Refs-only state handling.
   - Use `FrontDeskState` or extend it conservatively if needed.
   - Do not store raw conversation, raw prompt, raw model output, full transcript, or large text in graph/state objects.
   - State should store only round number, readiness, next action, booleans, and artifact refs.

3. Draft artifact materialization.
   - After a successful `RequirementsElicitor` round:
     - Write `frontdesk/draft_skill_spec.yaml` when `draft_skill_spec` is present.
     - Write `frontdesk/acceptance_criteria.yaml` when `draft_acceptance_criteria` is present.
   - Validate artifacts with existing schema objects where possible.
   - Fail closed if the report claims `ready_for_audit` but required draft artifacts are missing or invalid.

4. Round routing.
   - If elicitation fails closed: write/update state to `failed` / `fail_closed`.
   - If elicitor returns `needs_clarification`: route to `ask_user`, do not audit or freeze.
   - If elicitor returns `ready_for_audit`: materialize drafts, run `SpecAuditor`, then run `FrontDeskFreezeGate`.
   - If auditor fails closed: route to `failed` / `fail_closed`.
   - If freeze gate returns:
     - `freeze`: state readiness `frozen`, next action `route_to_build`, frozen refs set.
     - `ask_user`: state readiness `needs_clarification`, next action `ask_user`.
     - `human_review_required`: state readiness `human_review_required`, next action `human_review`, `human_review_required=True`.
     - `reject`: state readiness `rejected`, next action `reject`.

5. Round limit / human gate.
   - Respect `FrontDeskConfig.max_clarification_rounds`.
   - At or beyond the round limit, route to human review rather than starting another model loop.

6. Tests.
   - Add `tests/test_frontdesk_loop.py`.
   - Cover at least:
     - fuzzy need -> elicitor asks questions -> state `needs_clarification`, next action `ask_user`, no audit/freeze.
     - clear need -> draft materialized -> audit -> freeze -> state `frozen`, next action `route_to_build`, frozen refs present.
     - auditor approved but freeze gate blocks -> state routes back to `ask_user` or human review, no build route.
     - high risk/human review audit/freeze path -> state `human_review_required`.
     - round limit -> human review, no model call when starting from a state already at/over max rounds if applicable.
     - provider/schema failure -> fail closed.
     - state rejects raw `conversation`, `raw_prompt`, `raw_model_output` fields.
     - loop uses fake/scripted model clients only.

7. Exports.
   - Export new public API from `src/skillfoundry/__init__.py`.

## Non-Goals

Do not implement:

- WP16 acceptance coverage result/registry gate.
- WP17 real builder.
- Live OpenAI provider integration.
- Live Codex or CodexAgentThreadWorker.
- UI/API server changes.
- Registry evaluation logic.
- ContextForge internals.
- Full redaction/retention subsystem.

## Hard Constraints

- Default tests must be deterministic/offline.
- No network calls.
- No real provider calls.
- No live Codex calls.
- Do not claim ContextForge controls Codex internals.
- Do not let the LLM auditor freeze a spec; only `FrontDeskFreezeGate` can freeze.
- Do not put full conversation or raw model payloads into LangGraph/FrontDesk state.
- Keep changes narrowly scoped.

## Acceptance Commands

Run:

```bash
.venv/bin/python -m pytest tests/test_frontdesk_loop.py -q
.venv/bin/python -m pytest tests/test_frontdesk_schema.py tests/test_frontdesk_workspace.py tests/test_frontdesk_elicitor.py tests/test_frontdesk_auditor.py tests/test_frontdesk_freeze_gate.py tests/test_frontdesk_loop.py -q
.venv/bin/python -m pytest -q
git diff --check
```

## Final Response Required From Worker

Report:

- files changed;
- public API added;
- test commands run and results;
- any tradeoffs or remaining limitations.

