# ForgeUnit SkillFoundry Composition Layer

Last updated: 2026-05-26

Status: clean vNext assembly slice with verified adaptive steering and configurable FrontDesk worker command boundary

## Purpose

This directory is the first clean product composition layer for the new
SkillFoundry direction:

```text
SkillFoundry product semantics
  + LangGraph / graph v2 refs-only state
  + ForgeUnit work-unit command boundary
  + ContextForge-style evidence discipline
  + SkillFoundry Verifier
  + SkillFoundry Registry
```

It deliberately avoids editing the legacy `src/skillfoundry/` product tree as
the primary place to assemble the new path. The old package remains valuable as
a library of stable primitives:

- `JobWorkspace`
- schema models
- locked input and artifact manifest handling
- `Verifier`
- `LocalSkillRegistry`
- ForgeUnit adapter pilots

The new package is:

```text
src/forgeunit_skillfoundry/
  __init__.py
  config.py      # validated SkillFactoryConfig and mode derivation
  engine.py      # ForgeUnit command/repair engine boundary
  graph.py       # thin LangGraph product-stage skeleton
  product.py     # thin public product entry
  report.py      # refs-only product evidence summary/read model
  state.py       # refs-only product state payload and writer
  testing.py     # deterministic fake command fixtures
  adapters/
    workspace.py # route an existing locked JobWorkspace into vNext
    frontdesk.py # route a frozen route_to_build FrontDesk job into vNext
```

The local script runner is:

```text
scripts/run_forgeunit_skill_factory.py
```

The FrontDesk API entry point now routes frozen jobs into this layer by default:

```text
POST /frontdesk/jobs/{job_id}/build
```

Worker command selection for this API route is deliberately small:

```text
request payload fake_mode -> deterministic fake command
request payload command / repair_command -> caller-provided command bridge
SkillFoundryAPI constructor forgeunit_command / forgeunit_repair_command -> configured command bridge
SKILLFOUNDRY_FORGEUNIT_COMMAND / SKILLFOUNDRY_FORGEUNIT_REPAIR_COMMAND -> deployment command bridge
nothing configured -> deterministic fake happy command
```

The fake fallback keeps local development and CI fully offline. A deployed
service can provide the real ForgeUnit/Codex command once at construction time
or via environment variables, without asking every build request to carry a
command string. If the vNext worker fails before producing a verified refs-only
result, or if the refs-only summary cannot be read afterward, the API returns a
redacted error instead of echoing lower-level exception text, command strings,
stdout/stderr, transcript markers, or worker details.

The manual FrontDesk API pilot sequence, worker protocol, and preflight
redaction checks are specified in:

```text
docs/FRONTDESK_FORGEUNIT_COMMAND_PILOT_RUNBOOK.md
```

The old graph v2 path remains available only by explicit compatibility request:

```json
{"build_mode": "graph_v2"}
```

The adaptive steering loop now sits alongside this composition layer as a
verified product-layer control primitive. Its stable fields are substrate
candidates, not just pilot-only state.

## Public Entry Points

```python
from forgeunit_skillfoundry import (
    SkillFactoryConfig,
    ForgeUnitSkillFactoryEngine,
    build_evidence_summary,
    compile_skill_factory_graph,
    prepare_skill_factory_workspace,
    read_evidence_summary,
    run_codex_skill_factory,
    run_existing_workspace_skill_factory,
    run_frozen_frontdesk_skill_factory,
    run_skill_factory_graph,
)
```

`prepare_skill_factory_workspace(...)` creates or reuses a locked
SkillFoundry `JobWorkspace`.

`run_skill_factory_graph(...)` runs the explicit LangGraph product skeleton.
`run_codex_skill_factory(...)` is the public product convenience entry and now
uses that graph path.

Both entries support two modes:

```text
command_bridge
  -> one explicit ForgeUnit command bridge
  -> SkillFoundry verifier
  -> registry

repair_command_bridge
  -> first explicit ForgeUnit command bridge
  -> verifier failure
  -> refs-only repair packet
  -> second explicit ForgeUnit command bridge
  -> verifier pass
  -> registry
```

Both modes write:

```text
contextforge/forgeunit_skillfoundry_product_state.json
contextforge/forgeunit_skillfoundry_graph_state.json
contextforge/forgeunit_skillfoundry_summary.json
```

That product state is refs-only. It records stage/status, selected evidence
refs, selected ContextForge status fields, registry result, and trust boundary
flags. It does not inline raw prompt, raw transcript, package body, or raw
worker input. The graph state artifact is also refs-only and explicitly records
that command strings are not included in persisted graph state. API responses
also do not return configured command strings.

The summary artifact is the product-facing read model for future API/UI,
reviewers, and CLI output. It contains job id, mode, stage/status, verification
status/ref, registry decision/entry refs, attempt refs, selected evidence refs,
and trust boundary flags. It does not inline artifact bodies.

## Adapters

Phase 5 adds thin routing adapters instead of migrating the legacy product tree:

```python
from forgeunit_skillfoundry import (
    run_existing_workspace_skill_factory,
    run_frozen_frontdesk_skill_factory,
)
```

`run_existing_workspace_skill_factory(workspace, ...)` accepts an already
initialized `JobWorkspace`, checks locked inputs, refuses to overwrite it, and
routes `workspace.root.parent / workspace.job_id` into the same vNext LangGraph
path.

`run_frozen_frontdesk_skill_factory(workspace, ...)` adds the FrontDesk build
gate:

```text
frontdesk/state.json readiness == frozen
frontdesk/state.json next_action == route_to_build
freeze_manifest_ref exists
freeze manifest validates
freeze manifest artifact refs exist
freeze manifest artifact hashes match
```

Only after that does it call the existing workspace adapter. This keeps the
FrontDesk-specific concern at the boundary rather than spreading it through the
vNext graph.

One integration detail is now handled in the ForgeUnit registry gate: frozen
FrontDesk workspaces include root `acceptance_criteria.yaml`, and the existing
registry requires deterministic acceptance coverage when that file exists.
The ForgeUnit registry node now writes:

```text
qa/acceptance_coverage_plan.json
qa/acceptance_coverage_result.json
```

after SkillFoundry verification passes and before registry approval. These refs
may appear in vNext product state, graph state, and summary, but only as refs and
hashes.

For FrontDesk workspaces with `frontdesk/conversation.jsonl`, the ForgeUnit
adapter also writes minimal ContextForge boundary evidence before running the
SkillFoundry verifier:

```text
contextforge/goal_harness_state.json
contextforge/ledger.sqlite3
```

This records the raw FrontDesk conversation as forbidden from the build prompt
context, satisfying the verifier check
`contextforge_raw_frontdesk_conversation_excluded` without placing the raw
conversation in vNext graph/product/summary state.

## CLI Runner

Run an offline deterministic happy-path smoke:

```bash
.venv/bin/python scripts/run_forgeunit_skill_factory.py \
  --runs-root runs \
  --job-id demo-skill-001 \
  --registry .local/forgeunit_skillfoundry_registry.json \
  --fake-mode happy \
  --version local-demo
```

Run an offline deterministic repair-path smoke:

```bash
.venv/bin/python scripts/run_forgeunit_skill_factory.py \
  --runs-root runs \
  --job-id demo-skill-002 \
  --registry .local/forgeunit_skillfoundry_registry.json \
  --fake-mode repair \
  --version local-repair-demo
```

Run with an explicit caller-provided command:

```bash
.venv/bin/python scripts/run_forgeunit_skill_factory.py \
  --runs-root runs \
  --job-id demo-skill-003 \
  --registry .local/forgeunit_skillfoundry_registry.json \
  --command "python my_worker.py" \
  --version local-command-demo
```

The script prints `contextforge/forgeunit_skillfoundry_summary.json` directly.
It does not maintain a separate summary builder, and it does not print command
strings, raw prompt, raw transcript, package body, or raw worker input.

## Kernel Boundaries

Phase 1 kept the package small but separated responsibilities. Phase 2 adds a
thin LangGraph product skeleton without changing ForgeUnit or verifier
semantics:

```text
config.py
  SkillFactoryConfig validates job_id, command strings, attempt limits,
  registry path, version, timestamp, and mode. Mode is derived from whether
  repair_command is present.

engine.py
  ForgeUnitSkillFactoryEngine calls the existing SkillFoundry ForgeUnit adapter.
  It supports command_bridge and repair_command_bridge only. It does not create
  workspaces, write product read models, or bypass verifier/registry gates.

graph.py
  compile_skill_factory_graph(...) builds a four-node product graph:
  prepare_workspace -> run_forgeunit_engine -> verify_product_state ->
  emit_product_report. SkillFactoryConfig is captured in node closures, so raw
  command strings do not enter graph state.

adapters/workspace.py
  run_existing_workspace_skill_factory(...) is the bridge from an existing
  locked JobWorkspace into the clean vNext graph. It does not recreate or
  overwrite the workspace.

adapters/frontdesk.py
  run_frozen_frontdesk_skill_factory(...) enforces frozen route_to_build state
  and freeze manifest/hash integrity before entering vNext.

report.py
  build_evidence_summary(...), write_evidence_summary(...), and
  read_evidence_summary(...) own the stable product evidence summary:
  contextforge/forgeunit_skillfoundry_summary.json. The graph writes it after
  product and graph state exist; the CLI prints it as stdout.

state.py
  build_product_state_payload(...) and write_product_state(...) own the stable
  product read model. They select known evidence refs and status fields, write
  contextforge/forgeunit_skillfoundry_product_state.json, and add its ref/hash
  to graph state.

product.py
  prepare_skill_factory_workspace(...) remains a convenience helper.
  run_codex_skill_factory(...) builds SkillFactoryConfig and delegates to
  run_skill_factory_graph(...).

scripts/run_forgeunit_skill_factory.py
  CLI runner for local smoke and manual explicit-command runs. Tests use
  --fake-mode happy and --fake-mode repair, so CI remains offline and
  deterministic.
```

## What This Is Not

This slice does not add:

- live Codex execution by default;
- Codex SDK thread lifecycle;
- full API/UI migration beyond the frozen FrontDesk build route;
- scheduler, daemon, queue, worker pool, or long-running service;
- long-term memory;
- a replacement for SkillFoundry verifier or registry;
- acceptance based on ForgeUnit worker self-report.

Live Codex remains an explicit command choice by the caller. Tests use only fake
local command scripts from `forgeunit_skillfoundry.testing`. The FrontDesk API
defaults to fake happy mode unless a payload, constructor, or environment
command is configured.

## Why This Shape

The old SkillFoundry repo has useful infrastructure but a noisy historical
product surface. This layer lets the new architecture move forward without
turning every step into a legacy migration.

The rule is:

```text
New directory = clean product path.
Old skillfoundry package = stable capability library.
```

When this layer proves itself against real product tasks, it can become the
default SkillFoundry vNext entry point. Until then, it stays small and
deterministic.

## Verification

Focused tests:

```bash
.venv/bin/python -m pytest tests/test_frontdesk_api.py tests/test_forgeunit_skillfoundry_adapters.py tests/test_forgeunit_skillfoundry_scripts.py tests/test_forgeunit_skillfoundry_composition.py tests/test_forgeunit_adapter.py -q
```

Full regression:

```bash
.venv/bin/python -m pytest -q
git diff --check
```
