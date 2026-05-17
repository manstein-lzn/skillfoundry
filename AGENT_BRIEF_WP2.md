# Agent Brief WP2: LangGraph Skeleton

## Mission

Implement SkillFoundry WP2: a minimal LangGraph workflow skeleton on top of the WP1 schema/workspace foundation.

This is an implementation task for a 5.5-xhigh worker. The architect will review the result independently.

## Context

Current repository: `/home/mansteinl/skillfoundry`

Already completed:

- WP0 design baseline and roadmap.
- WP1 schema, workspace initializer, artifact manifest, path confinement, locked input checks.

Key docs to read before editing:

- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `docs/WORK_PACKAGES.md`
- `docs/ACCEPTANCE_PLAN.md`
- `src/skillfoundry/schema.py`
- `src/skillfoundry/workspace.py`

Official LangGraph API notes used by the architect:

- Use `StateGraph` from `langgraph.graph`.
- Use `START` / `END` edges where appropriate.
- Use `InMemorySaver` from `langgraph.checkpoint.memory` for tests.
- When a graph is compiled with a checkpointer, invocation needs a config containing `{"configurable": {"thread_id": "..."}}`.

## Scope

WP2 owns:

- Minimal workflow graph.
- Route enum.
- Stage/status enums or constants.
- Refs-only state model.
- State validation that rejects large inline text and forbidden raw artifact fields.
- Stub nodes for the main flow.
- Checkpoint/resume smoke support.
- Repair loop and attempt-limit routing.
- Human review placeholder.

Recommended files:

- `src/skillfoundry/graph.py`
- `tests/test_graph.py`
- update `src/skillfoundry/__init__.py`
- update `pyproject.toml` dependencies if needed

## Non-goals

Do not implement:

- real Codex Worker invocation;
- FakeWorker from WP3;
- full Verifier business rules from WP4;
- Registry persistence from WP6;
- ContextForge integration from WP5;
- API/UI;
- real model calls;
- shell/MCP/action runtime.

Builder self-report is still not acceptance evidence. WP2 only creates the graph skeleton.

## Required Workflow Shape

The graph should support this conceptual path:

```text
intake
  -> clarify
  -> spec_generate
  -> route
  -> prepare_workspace
  -> build
  -> verify
  -> repair_or_register
  -> emit_report
```

The implementation can use compact node names, but tests must prove the main route behavior.

## State Contract

State must be refs-only. It may contain:

- `job_id`
- `stage`
- `status`
- `route`
- `attempt_count`
- `attempt_limit`
- `failure_class`
- `refs`
- `hashes`
- `next_action`
- `human_review_required`
- compact booleans or small enums needed by tests

State must not contain:

- full Skill package content;
- raw worker transcript;
- raw tool logs;
- full replay bundle;
- large prompt text;
- full verification logs;
- arbitrary large strings.

Add a validator or helper that fails when forbidden keys or oversized string values appear in state.

## Required Routes

At minimum cover:

- `build_new`
- `reuse_existing`
- `reject_unsafe`
- `ask_clarifying_question`

The graph should also represent repair and register decisions internally.

## Acceptance Criteria

Automated tests must prove:

- workflow can run with stub nodes;
- `build_new` can reach a registered or report-emitted terminal status;
- `reuse_existing` does not build a new package;
- `reject_unsafe` stops safely;
- `ask_clarifying_question` reaches a clarification or human-review placeholder;
- failed verification with attempts remaining routes to repair;
- failed verification at attempt limit routes fail-closed or human review;
- state validator rejects large inline text and forbidden raw log/package/transcript fields;
- graph can compile with an `InMemorySaver` checkpointer and run with a `thread_id`;
- checkpoint/resume smoke test proves state can be recovered or continued by refs, without storing large artifacts.

Required command:

```bash
.venv/bin/python -m pytest -q
```

## Implementation Notes

- Prefer simple, explicit Python over clever abstractions.
- Keep node behavior deterministic and test-fixture driven.
- Store only small refs and hashes in state.
- Do not create real workspace artifacts beyond what tests explicitly need.
- If `langgraph` is not installed, add it to `pyproject.toml` and install/update the local `.venv` as needed.
- Do not edit `.metaloop/`, `.venv/`, caches, or unrelated docs.

## Expected Final Response From Worker

List:

- files changed;
- route behaviors implemented;
- tests run and exact result;
- any deviations from this brief.
