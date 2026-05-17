# Agent Brief WP5: ContextForge Integration

## Mission

Implement SkillFoundry WP5: integrate ContextForge as the owned LLM context runtime and task-level evidence ledger boundary.

This is an implementation task for a 5.5-xhigh worker. The architect will review independently.

## Context

Repository: `/home/mansteinl/skillfoundry`

Related local dependency source:

- `/home/mansteinl/contextforge`

Already completed in SkillFoundry:

- WP1: schema, workspace, artifact manifest, path confinement.
- WP2: LangGraph skeleton with refs-only state.
- WP3: WorkerAdapter and deterministic FakeWorker fixtures.
- WP4: independent Verifier.

Read before editing:

- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `docs/WORK_PACKAGES.md`
- `docs/ACCEPTANCE_PLAN.md`
- `src/skillfoundry/schema.py`
- `src/skillfoundry/workspace.py`
- `src/skillfoundry/worker.py`
- `src/skillfoundry/verifier.py`
- `/home/mansteinl/contextforge/src/contextforge/schema.py`
- `/home/mansteinl/contextforge/src/contextforge/kernel.py`
- `/home/mansteinl/contextforge/src/contextforge/ledger.py`
- `/home/mansteinl/contextforge/src/contextforge/tools.py`

## Scope

WP5 owns:

- ContextForge dependency wiring.
- SkillFoundry-owned LLM call wrapper.
- Worker boundary evidence recorder.
- Verifier result/log governance for prompt-safe summaries.
- Job-level context audit/report.
- Replay coverage calculation that distinguishes owned calls from external worker boundaries.
- Usage unavailable reason handling.

Recommended files:

- `src/skillfoundry/context.py`
- `tests/test_context.py`
- update `src/skillfoundry/__init__.py`
- update `pyproject.toml` to depend on local ContextForge or import it in tests through a controlled path, whichever is cleaner.

## Non-goals

Do not implement:

- ContextForge internals;
- Codex Worker internal prompt/tool-loop/cache/cost control;
- external worker replay as owned LLM replay;
- real model provider calls;
- real Codex Worker integration;
- shell/MCP/action runtime;
- sandbox;
- queue;
- permissions system;
- UI/API;
- Registry write/approval.

## Required Boundaries

Owned LLM calls are calls made by SkillFoundry nodes such as clarify/spec/route/failure-analysis/report-summary.

Owned LLM calls must have:

- `ContextRequest`
- `PromptView`
- `ModelCallEnvelope`
- `ModelCallRecord` or error record
- replay artifact reference where ContextForge provides it
- usage record or explicit unavailable/unsupported reason

External worker invocation is not owned LLM replay.

External worker boundary records may include:

- input manifest ref/hash;
- worker invocation record fields;
- transcript ref;
- diff ref;
- execution report ref;
- verifier result ref/hash;
- usage availability/unavailable reason;
- duration;
- failure class.

But they must not include:

- Codex internal prompt;
- Codex internal tool loop;
- Codex context compaction;
- Codex cache details;
- fake cost/cached-token telemetry.

## Acceptance Criteria

Automated tests must prove:

- owned LLM call goes through ContextForge and produces PromptView + ModelCallEnvelope + ModelCallRecord or error record;
- owned LLM replay artifact/reference is locatable;
- worker invocation is recorded as boundary evidence, not as owned LLM replay;
- verifier result/log governance creates bounded prompt-safe content and does not inject raw verifier logs directly;
- metrics include attempt count, verification status, worker duration, usage availability, and usage unavailable reason when applicable;
- replay coverage excludes external worker internals and does not overclaim Codex Worker replay;
- audit/report clearly separates owned LLM calls and external worker boundary records;
- no provider usage is fabricated when unavailable;
- tests include forbidden assertions/negative checks for overclaim strings such as “controls Codex internal prompt/tool loop/cache/cost”.

Required command:

```bash
.venv/bin/python -m pytest -q
```

## Implementation Notes

- Prefer a thin adapter around ContextForge rather than copying ContextForge code.
- If importing local ContextForge from `/home/mansteinl/contextforge`, update project config in a way that works in this local repo.
- Use ContextForge `ContextLedger`, `ContextKernel`, `FakeModelClient`, schema records, and `ToolOutputGovernor` where useful.
- Keep all SkillFoundry records JSON-compatible.
- It is acceptable to create a deterministic fake model path for tests.
- Do not modify `.metaloop/`, `.venv/`, caches, unrelated docs, or previous WP behavior unless integration requires tiny exports/config updates.

## Expected Final Response From Worker

List:

- files changed;
- ContextForge adapter API shape;
- owned-call behavior;
- worker-boundary evidence behavior;
- tests run and exact result;
- any deviations.
