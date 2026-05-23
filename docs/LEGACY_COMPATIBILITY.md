# SkillFoundry Legacy Compatibility

This page names the remaining compatibility islands in SkillFoundry. These
modules and documents may still be useful for deterministic fixtures,
maintenance, and historical understanding, but they do not define the current
product mainline.

## Current Mainline

The current SkillFoundry product path is:

```text
FrontDesk
  -> ContextForge Goal Runtime
  -> ForgeUnit SkillFoundry vNext
  -> Codex exec / deterministic fake command boundary
  -> SkillFoundry Verifier
  -> Registry
```

Build new product behavior against that path first. Use compatibility islands
only when a test, CLI fixture, migration check, or explicit maintenance task
requires them.

## Compatibility Islands

### `skillfoundry.offline`

Status:

- Legacy deterministic offline builder compatibility.
- `build_offline` and `OfflineWorkerMode` remain package-root compatibility
  entrypoints because CLI/dev fixtures still use them directly.
- Other offline internals are module-scoped.

Allowed uses:

- CLI/dev deterministic fixtures.
- Migration coverage for the old offline happy path and fail-closed path.
- Tests that prove retired API/UI surfaces do not accidentally recreate legacy
  offline jobs.

Not allowed:

- New product build orchestration through retired `POST /jobs` offline
  creation.
- New current architecture docs that describe the offline builder as the
  product mainline.

### `skillfoundry.worker`

Status:

- Legacy `WorkerAdapter`, `FakeWorker`, and `CodexWorker` compatibility module.
- Worker internals are no longer package-root exports.

Allowed uses:

- Deterministic legacy worker fixture tests.
- Archived CodexWorker pilot maintenance.
- Verifier or workspace fixture construction where the old adapter is the
  explicit behavior under test.

Not allowed:

- Treating `WorkerAdapter` as the current worker abstraction for new
  ForgeUnit-backed product work.
- Claiming the old `CodexWorker` path controls Codex internal prompt, tool
  loop, compaction, cache, or cost.

### `skillfoundry.context`

Status:

- Legacy FrontDesk owned-call/context adapter compatibility module.
- Context adapter internals are no longer package-root exports.

Allowed uses:

- Existing owned-call FrontDesk fixture tests.
- Maintenance of old deterministic model-call adapters.

Not allowed:

- Building new ContextForge context-management features inside the old
  `context.py` adapter.
- Describing `skillfoundry.context` as the current context manager. Current
  context boundary work belongs to ContextForge contracts, ledgers, cache
  plans, checkpoints, and refs-only evidence.

### `skillfoundry.graph_v2`

Status:

- Legacy v2 LangGraph compatibility spine.
- Graph state types, routes, node builders, compilers, and validators are
  module-scoped.
- FrontDesk build defaults now route through ForgeUnit SkillFoundry vNext, not
  direct graph v2.

Allowed uses:

- Compatibility graph tests.
- ForgeUnit bridge maintenance where graph v2 state validation is still part
  of the adapter contract.
- Explicit `build_mode="graph_v2"` style compatibility requests.

Not allowed:

- Presenting graph v2 as the new-user default product composition layer.
- Promoting graph v2 helper symbols back to package root without updating
  `docs/PUBLIC_API.md` and the public API tests.

### `skillfoundry.goal_runtime`

Status:

- Direct ContextForge Goal Runtime runner/state helper module.
- Direct build/repair verified runner helpers are module-scoped compatibility
  and maintenance surfaces.
- `seed_goal_harness_context` remains package-root because it is a small current
  refs-only evidence helper.

Allowed uses:

- Runtime-focused tests.
- ForgeUnit bridge and graph v2 maintenance.
- Explicit inspection of ContextForge ledger, runtime result, and verified
  runtime result artifacts.

Not allowed:

- Using direct runner helpers as the product approval boundary when the current
  path should pass through ForgeUnit, verifier, and registry gates.
- Treating worker self-report from the runtime as acceptance.

### `skillfoundry.feedback`

Status:

- WP11 feedback/versioning support surface.
- Module-scoped after Phase 13I.

Allowed uses:

- Feedback/versioning fixture tests.
- Local support workflows that create repair/version plans from approved
  source versions.

Not allowed:

- Treating feedback/versioning support as the current package-root construction
  API.

### `skillfoundry.qa`

Status:

- WP10 deterministic QA Lab support surface.
- Module-scoped after Phase 13I.

Allowed uses:

- Deterministic QA support tests.
- Local acceptance hardening and historical QA evidence.

Not allowed:

- Treating QA Lab as a replacement for the current verifier, acceptance
  coverage, and registry gates.

### `skillfoundry.ops`

Status:

- WP12 local operations support surface.
- Reduced to local health, observability, and cleanup helpers.
- Module-scoped after Phase 13I.

Allowed uses:

- Local health checks.
- Local observability summaries.
- Safe cleanup of known transient artifacts.

Not allowed:

- Reintroducing hidden offline job creation helpers.
- Treating local ops helpers as production deployment, queueing, auth, or
  tenancy infrastructure.

### Archived CodexWorker and WP Documents

Status:

- Historical WP0-WP17 roadmaps, agent briefs, pilots, and operations notes live
  under `docs/archive/`.
- They explain where the system came from. They are not the current
  implementation contract.

Allowed uses:

- Historical context.
- Recovering product lessons and constraints.
- Understanding why compatibility modules exist.

Not allowed:

- Using archived WP roadmaps as current task ordering.
- Following archived agent briefs as implementation instructions without first
  checking `README.md`, `docs/README.md`, `docs/PUBLIC_API.md`, and
  `HANDOFF.md`.

## Cleanup Rule

Before deleting a compatibility island, audit all of these:

- source imports;
- test imports;
- CLI/script usage;
- current docs;
- archived docs that might still be linked from current docs;
- package-root exports;
- deterministic validation gates.

Deletion is allowed only when the behavior is unused or replaced, the default
offline gates still pass, and new-user docs no longer point at the removed
surface.
