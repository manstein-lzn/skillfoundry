# SkillFoundry ForgeUnit Product Adapter Slice

Last updated: 2026-05-23

Status: first code integration slice plus offline command-bridge pilot

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
- `bridge_forgeunit_success_to_skillfoundry_attempt(workspace, state)`
- `build_forgeunit_skillfoundry_verification_node(runs_root)`
- `build_forgeunit_registry_gate_node(runs_root, registry_path=...)`
- `compile_forgeunit_pilot_graph(runs_root, dry_run=True, command=None)`
- `run_forgeunit_pilot_graph(runs_root, job_id, dry_run=True, command=None)`
- `compile_forgeunit_command_bridge_pilot_graph(runs_root, registry_path=..., command=...)`
- `run_forgeunit_command_bridge_pilot_graph(runs_root, job_id, registry_path=..., command=...)`

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

Default tests use either `dry_run=True` or an explicit local fake command, so no
live Codex process is invoked.

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

The command-bridge path also adds only refs:

```text
refs.forgeunit_attempt_input_manifest
refs.forgeunit_attempt_execution_report
refs.forgeunit_attempt_transcript
refs.forgeunit_attempt_diff
refs.skillfoundry_verification_result
refs.registry_decision
refs.registry_entry
refs.final_report
```

It does not place raw prompts, raw transcripts, package bodies, raw worker
input, or raw user requirements into graph state.

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

The adapter also includes an offline command-bridge success path:

```text
Initialized SkillFoundry JobWorkspace
  -> ForgeUnit task.yaml
  -> ForgeUnit codex_exec adapter with explicit local command
  -> package/SKILL.md + evidence/manifest.json + evidence/transcript.md
  -> attempts/001 SkillFoundry evidence bridge
  -> Verifier().verify(...)
  -> LocalSkillRegistry.add_verified(...)
  -> final_report.json
```

This path is intentionally deterministic in tests. The command is a local fake
script that behaves like a Codex exec boundary worker by writing:

```text
package/SKILL.md
evidence/manifest.json
evidence/transcript.md
.forgeunit/runs/<run_id>/workers/execute_codex_exec_worker_result.json
```

The worker result is still not acceptance. It is only converted into
SkillFoundry-compatible evidence:

```text
attempts/001/input_manifest.json
attempts/001/execution_report.json
attempts/001/worker_transcript.log
attempts/001/output_diff.patch
```

Only after that does the independent SkillFoundry verifier write
`verifier/verification_result.json`, and only a passing verifier result can enter
the registry gate.

For a manual real Codex exec probe, see:

```text
docs/FORGEUNIT_REAL_CODEX_EXEC_PILOT.md
scripts/forgeunit_codex_exec_worker.py
scripts/run_forgeunit_real_codex_exec_pilot.py
```

That pilot wraps a real `codex exec` or explicit fake command, but it is not part
of default pytest and does not change the offline deterministic test policy.

## Non-Goals

This slice does not add:

- live Codex execution in tests;
- Codex SDK thread lifecycle;
- owned LLM worker execution;
- live registry promotion based solely on ForgeUnit worker self-report;
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
- the offline command-bridge pilot can run a local fake Codex command through
  ForgeUnit, bridge the result into SkillFoundry verifier evidence, and register
  only after `Verifier` passes;
- SkillFoundry graph state remains refs-only;
- raw requirement bodies, raw prompts, raw transcripts, and package bodies are
  not inlined into state or summaries.
