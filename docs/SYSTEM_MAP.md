# SkillFoundry System Map

This is the compact map for the current SkillFoundry system. It describes the
implementation path a new contributor should understand before reading archived
WP documents.

## Current Mainline

```text
FrontDesk
  -> ContextForge Goal Runtime
  -> ForgeUnit SkillFoundry vNext
     -> validated adaptive steering loop
  -> Codex exec / deterministic fake command boundary
  -> SkillFoundry Verifier
  -> Registry
```

The current mainline is not the old WP0-WP17 prototype path. Historical modules
and docs remain for compatibility, fixtures, and product memory, but new
product behavior should start from the mainline above.

The adaptive steering loop is now a verified product-layer control primitive,
not a temporary experiment. Its stable artifacts are candidates for future
substate extraction into ContextForge / ForgeUnit.

## 10-Minute Reading Path

Read in this order:

1. `README.md`
   Repo purpose, installation, and default validation commands.
2. `docs/SYSTEM_MAP.md`
   This current architecture map.
3. `docs/FORGEUNIT_SKILLFOUNDRY_COMPOSITION.md`
   The clean ForgeUnit-backed composition layer.
4. `docs/PUBLIC_API.md`
   What belongs at package root and what is module-scoped.
5. `docs/LEGACY_COMPATIBILITY.md`
   Which old surfaces remain and why they are not the product mainline.
6. `tests/README.md`
   Which tests protect current behavior versus compatibility and script smoke.
7. `docs/DEVELOPMENT_WORKFLOW.md`
   Local commands and validation discipline.

After that, use `HANDOFF.md` for current operational state and
`docs/archive/` only for historical context.

## Package Boundaries

Current composition:

- `src/forgeunit_skillfoundry/`
  Current clean product composition layer.
- `src/skillfoundry/adaptive.py`, `src/skillfoundry/adaptive_workspace.py`
  Verified adaptive schema and workspace artifact helpers.
- `src/forgeunit_skillfoundry/adaptive_graph.py`,
  `src/forgeunit_skillfoundry/adaptive_benchmark.py`
  Deterministic adaptive steering loop and baseline/upgraded pressure benchmark.
- `src/skillfoundry/api.py`
  FrontDesk API and product read models.
- `src/skillfoundry/frontdesk*.py`
  FrontDesk schemas, workspace, loop, governance, and Goal Runtime slices.
- `src/skillfoundry/forgeunit_adapter.py`
  Bridge from SkillFoundry job/workspace evidence into ForgeUnit task packs and
  command-boundary execution.
- `src/skillfoundry/contracts.py`
  ContextForge contract artifacts.
- `src/skillfoundry/verification_bridge.py`
  SkillFoundry verifier evidence bridged into ContextForge verification
  records.
- `src/skillfoundry/final_report.py`
  Current final-report evidence envelope.
- `src/skillfoundry/verifier.py`, `src/skillfoundry/registry.py`,
  `src/skillfoundry/workspace.py`, `src/skillfoundry/schema.py`,
  `src/skillfoundry/security.py`
  Durable gates, workspace rules, schemas, and path safety.

Compatibility and support modules:

- `src/skillfoundry/offline.py`
- `src/skillfoundry/worker.py`
- `src/skillfoundry/context.py`
- `src/skillfoundry/graph_v2.py`
- `src/skillfoundry/goal_runtime.py`
- `src/skillfoundry/feedback.py`
- `src/skillfoundry/qa.py`
- `src/skillfoundry/ops.py`

Read `docs/LEGACY_COMPATIBILITY.md` before building on any of those modules.

## Runtime Boundary

Default validation uses deterministic fake command boundaries. It must not call
live Codex.

Adaptive steering has its own locked regression gate:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_adaptive_schema.py \
  tests/test_adaptive_workspace.py \
  tests/test_adaptive_graph.py \
  tests/test_forgeunit_skillfoundry_composition.py \
  tests/test_adaptive_steering_benchmark.py -q
```

Live Codex is explicit and manual:

```bash
make live-semantic-eval-help
```

The current code can route through a command boundary for Codex exec or another
external worker, but acceptance still comes from verifier, acceptance coverage,
ContextForge evidence, and registry gates. Worker self-report is never
acceptance.

## Validation Gates

Default local gates:

```bash
make focused
make test
```

New-user reproducibility gate:

```bash
make fresh-clone-smoke
```

These are cleanup and deterministic quality gates. Real product validation with
live Codex scenarios is a later, separate plan.

## Compatibility Boundaries

Compatibility modules may remain because they still protect deterministic
fixtures, historical pilots, migration behavior, or bridge maintenance.

Do not treat compatibility success as a reason to:

- build new product features on retired API/UI `POST /jobs` offline creation;
- promote module-scoped compatibility helpers back to package root;
- use the old worker/context adapter as the current worker or context manager;
- treat graph v2 as the default current composition layer;
- claim control over Codex internals such as prompt assembly, tool loop,
  compaction, cache, or cost.

When in doubt, use the current mainline first, then document any compatibility
exception in `docs/LEGACY_COMPATIBILITY.md` and `docs/PUBLIC_API.md`.
