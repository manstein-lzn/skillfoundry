# SkillFoundry ForgeUnit Product Adapter Slice

Last updated: 2026-05-23

Status: first code integration slice

## Goal

This slice adds the first concrete bridge from SkillFoundry product semantics to
ForgeUnit v1.2:

```text
SkillFoundry JobWorkspace
  -> ForgeUnit task.yaml
  -> ForgeUnitNode("codex_exec")
  -> refs-only SkillFoundry v2 state
```

It is deliberately narrow. It does not replace the existing SkillFoundry v2
graph, verifier, registry, API, or Front Desk. It creates the product seam that
future work can route through.

## New Module

The implementation lives in:

```text
src/skillfoundry/forgeunit_adapter.py
```

It provides:

- `materialize_forgeunit_task_pack(workspace)`
- `run_forgeunit_codex_exec_node(workspace, dry_run=True, command=None)`
- `build_forgeunit_codex_exec_node(runs_root, dry_run=True, command=None)`
- `build_forgeunit_boundary_verification_node(runs_root)`
- `compile_forgeunit_pilot_graph(runs_root, dry_run=True, command=None)`
- `run_forgeunit_pilot_graph(runs_root, job_id, dry_run=True, command=None)`

The adapter depends on ForgeUnit v1.2. For local development with the sibling
checkout:

```bash
.venv/bin/python -m pip install -e ../ForgeUnit
```

With `uv`, the optional extra is declared as:

```bash
uv run --extra forgeunit --extra test pytest tests/test_forgeunit_adapter.py -q
```

## Task Pack Shape

The adapter writes `task.yaml` directly into the existing SkillFoundry job
workspace. That means the job workspace becomes the ForgeUnit task pack:

```text
runs/<job_id>/
  task.yaml
  build_contract.yaml
  skill_spec.yaml
  verification_spec.yaml
  worker_input.md
  package/
  evidence/
  .forgeunit/runs/<run_id>/
```

ForgeUnit inputs point at the existing locked SkillFoundry files. The task pack
does not inline the raw requirement body.

The current unit shape is:

```text
plan(fake)
  -> execute(codex_boundary / codex_exec adapter)
  -> verify(fake verifier placeholder)
```

The `execute` unit requires:

- `package/SKILL.md`
- `evidence/transcript.md`
- `evidence/manifest.json`
- a ForgeUnit `worker_result.json` written by the external worker

Default tests use `dry_run=True`, so no live Codex process is invoked.

## SkillFoundry v2 State

The node returned by `build_forgeunit_codex_exec_node()` updates only refs and
small IDs/status fields:

```text
refs.forgeunit_task_yaml
refs.forgeunit_run
refs.forgeunit_summary
refs.forgeunit_codex_exec_plan
hashes.forgeunit_task_yaml
hashes.forgeunit_summary
contextforge.forgeunit_run_id
contextforge.forgeunit_status
contextforge.forgeunit_route
contextforge.forgeunit_current_node
```

It does not place raw prompts, raw transcripts, package bodies, or raw user
requirements into graph state.

## What This Enables

This is now possible inside a product graph:

```python
from skillfoundry import build_forgeunit_codex_exec_node

build_node = build_forgeunit_codex_exec_node("runs", dry_run=True)
state = build_node({"job_id": "demo", "attempt_limit": 2})
```

The adapter now includes a dedicated pilot graph path:

```text
Initialized SkillFoundry JobWorkspace
  -> ForgeUnit codex_exec build
  -> ForgeUnit boundary verification
  -> human review
```

In dry-run mode this is intentionally not a successful build. It stops at human
review with:

```text
contextforge/forgeunit_boundary_verification.json
human_review/request.json
contextforge/forgeunit_pilot_graph_state.json
```

The boundary verification records:

```text
status: human_acceptance_required
boundary_status: dry_run_plan_ready
reason_code: forgeunit_codex_exec_dry_run_boundary_pending
```

It does not route to registry and does not write `final_report`.

Run it from Python:

```python
from skillfoundry import run_forgeunit_pilot_graph

state = run_forgeunit_pilot_graph("runs", "demo-job", dry_run=True)
```

## Non-Goals

This slice does not add:

- live Codex execution in tests;
- Codex SDK thread lifecycle;
- owned LLM worker execution;
- registry promotion through ForgeUnit;
- full replacement of `graph_v2.py`;
- long-term memory;
- a scheduler, queue, daemon, or worker pool.

## Verification

Focused tests:

```bash
.venv/bin/python -m pytest tests/test_forgeunit_adapter.py tests/test_graph_v2.py -q
```

The tests prove:

- a `JobWorkspace` can be materialized as a valid ForgeUnit task pack;
- the v2 node invokes ForgeUnit codex exec dry-run through ForgeUnit's public
  surface;
- the dedicated pilot graph routes ForgeUnit dry-run to human review instead of
  registry promotion;
- SkillFoundry graph state remains refs-only;
- raw requirement bodies are not inlined into state or summaries.
