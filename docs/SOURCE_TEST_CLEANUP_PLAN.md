# Source/Test Cleanup Plan

This document tracks the cleanup of SkillFoundry's source and test surface after
the repository documentation cleanup.

## Goal

Keep the current product path small and readable:

```text
FrontDesk
  -> ForgeUnit SkillFoundry vNext
  -> ContextForge / graph_v2 refs
  -> SkillFoundry Verifier
  -> Registry
```

Historical source should remain only when the current path still depends on it.
Tests should protect current behavior, not preserve old work-package scaffolding
after it has been retired.

## Cleanup Rules

- Keep `src/forgeunit_skillfoundry/` as the current composition layer.
- Keep `frontdesk`, `workspace`, `verifier`, `registry`, `acceptance`,
  `forgeunit_adapter`, `graph_v2`, `goal_runtime`, and `verification_bridge`
  until replacement evidence exists.
- Delete a legacy module only after imports, public exports, docs, and tests no
  longer depend on it.
- Keep default validation deterministic/offline.
- Do not make live Codex part of cleanup validation.

## Phase 13A

Status: implemented in this cleanup slice.

Retired:

- `src/skillfoundry/graph.py`
- `tests/test_graph.py`

Rationale:

- `src/skillfoundry/graph.py` was the old WP2 deterministic LangGraph skeleton.
- The current product graph is `src/forgeunit_skillfoundry/graph.py`.
- The current compatibility/product state contract is `src/skillfoundry/graph_v2.py`.
- The old graph tests only protected the WP2 skeleton, not the current
  ForgeUnit + FrontDesk vNext path.

Dependency fix:

- `Route` and `WorkflowStatus` moved into `src/skillfoundry/offline.py` as
  explicit legacy offline compatibility values.
- `goal_runtime.py` no longer imports status values from the retired graph.
- The public package no longer exports the retired WP2 graph compile/build
  helpers, state validator, state type, stage enum, or graph-specific
  validation error.

## Phase 13B

Status: implemented in this cleanup slice.

Retired:

- `src/skillfoundry/llm_builder.py`
- `tests/test_llm_builder.py`

Rationale:

- `src/skillfoundry/llm_builder.py` was the old WP17 owned-LLM builder pilot
  built on the legacy `WorkerAdapter` path and hand-written prompt assembly.
- The current owned LLM worker surface is
  `src/skillfoundry/workers_v2.py::OwnedLLMSkillBuilderWorker`.
- Current graph v2 and API tests use `workers_v2.OwnedLLMSkillBuilderWorker`,
  not the retired `LLMSkillBuilderWorker`.

Dependency fix:

- The public package no longer exports the retired `LLMSkillBuilderWorker` or
  `LLM_SKILL_BUILDER_*` constants.
- `workers_v2.OwnedLLMSkillBuilderWorker` remains exported and tested.

## Phase 13C

Status: implemented in this cleanup slice.

Extracted:

- `src/skillfoundry/final_report.py`

Rationale:

- `src/skillfoundry/offline.py` was carrying two responsibilities: the legacy
  deterministic offline builder and the current `final_report.json` evidence
  envelope used by v2/runtime paths.
- `final_report.json` is still current because graph v2, ForgeUnit adapter,
  API status reads, CLI report refresh, and registry gates use it as a compact
  evidence index.
- The old offline builder can now be audited or retired later without making
  current ForgeUnit/graph_v2 paths import the legacy builder module for final
  report helpers.

Dependency fix:

- `goal_runtime.py`, `graph_v2.py`, `forgeunit_adapter.py`, `api.py`,
  `cli.py`, and public package exports now import `emit_final_report` /
  `read_final_report` from `final_report.py`.
- `offline.py` keeps importing those helpers for legacy compatibility, so the
  public API and old offline tests continue to work during the transition.

## Phase 13D

Status: implemented in this cleanup slice.

Retired from API/UI:

- Legacy `POST /jobs` offline build creation.
- `SkillFoundryAPI(..., allow_legacy_offline_jobs=...)`.
- `SKILLFOUNDRY_ALLOW_LEGACY_OFFLINE_JOBS`.
- `skillfoundry serve --allow-legacy-offline-jobs`.
- The server-rendered legacy offline factory form.

Rationale:

- New product creation must enter through FrontDesk and
  `/frontdesk/jobs/{job_id}/build`.
- Direct `build_offline` remains available as deterministic developer
  compatibility for tests, ops, and migration fixtures, but it is no longer an
  API/UI product entrypoint.

Dependency fix:

- `api.py` no longer imports `build_offline` or `OfflineWorkerMode`.
- `POST /jobs` returns `legacy_offline_jobs_retired` and never writes a job.
- Existing `GET /jobs`, report, package, human-review, and ContextForge status
  endpoints remain because current FrontDesk build responses still link to
  those evidence views.

## Phase 13E

Status: implemented in this cleanup slice.

Retired:

- `SkillFoundryOps.build_jobs_concurrently(...)`
- `OPS_CONCURRENT_BUILD_REPORT_VERSION`

Rationale:

- The ops surface should report health, observability, and cleanup status for
  existing workspaces.
- A hidden ops method that creates deterministic offline builds was another
  legacy build entrypoint after API/UI `POST /jobs` was retired.
- Direct `build_offline` and CLI `skillfoundry build` remain available as
  explicit deterministic compatibility fixtures.

Dependency fix:

- `src/skillfoundry/ops.py` no longer imports or calls `build_offline`.
- Ops tests now keep the registry concurrency check without relying on an ops
  offline build method.

## Phase 13F

Status: implemented in this cleanup slice.

Narrowed:

- Top-level `skillfoundry` no longer exports legacy `worker.py` internals:
  `WorkerAdapter`, `FakeWorker`, `FakeWorkerMode`, `CodexWorker`, command-runner
  helpers, and worker boundary result types.
- Top-level `skillfoundry` no longer exports legacy offline helper internals:
  `prepare_offline_workspace`, `run_offline_attempt`, `verify_offline`,
  `register_offline`, `Route`, `WorkflowStatus`, and offline fixture classes.

Kept:

- `skillfoundry.build_offline`
- `skillfoundry.OfflineWorkerMode`
- `skillfoundry.offline.*` module-level compatibility for explicit tests and
  CLI/dev fixtures.
- `skillfoundry.worker.*` module-level compatibility for legacy fixture tests
  and the archived CodexWorker pilot.

Rationale:

- `offline.py` and `worker.py` still have useful deterministic fixture coverage
  and CLI compatibility, so deleting them would be premature.
- Keeping their internals off the package root reduces new-user API noise and
  makes the current product surface easier to scan.

Dependency fix:

- Legacy worker/offline tests import old internals from `skillfoundry.worker`
  and `skillfoundry.offline` directly.
- Public-package checks assert that the legacy internals no longer leak through
  `skillfoundry.__all__` or top-level attributes.

## Phase 13G

Status: implemented in this cleanup slice.

Narrowed:

- Top-level `skillfoundry` no longer exports legacy `context.py` adapter
  internals:
  `SkillFoundryContextAdapter`, `CONTEXT_ADAPTER_VERSION`,
  `OwnedLLMCallResult`, `ContextAuditReport`, `SkillFoundryContextMetrics`,
  `ReplayCoverageReport`, `VerifierPromptEvidence`,
  `WorkerBoundaryEvidence`, and `audit_report_to_json`.

Kept:

- `skillfoundry.context.*` module-level compatibility for legacy FrontDesk
  owned-call/context adapter fixtures.
- Current ContextForge contract helpers remain top-level:
  `build_goal_contract`, `build_agent_node_contract`, and related contract
  bridge helpers.
- Current FrontDesk conversation helpers remain top-level:
  `ConversationTurn`, `append_conversation_turn`, and
  `read_conversation_turns`.
- `seed_goal_harness_context` remains top-level because it belongs to the
  current Goal Runtime / refs-only ContextForge evidence path.

Rationale:

- `frontdesk.py` still imports `SkillFoundryContextAdapter` internally for
  deterministic owned-call fixtures, so deleting `context.py` would be
  premature.
- The package root should not suggest that the old Context Adapter is the
  current context-management abstraction.

Dependency fix:

- Legacy context and FrontDesk owned-call tests import the old adapter directly
  from `skillfoundry.context`.
- Public-package checks assert that legacy context adapter internals no longer
  leak through `skillfoundry.__all__` or top-level attributes.

## Phase 13H

Status: implemented in this cleanup slice.

Added:

- `docs/PUBLIC_API.md`, the package-root public API contract for the cleanup
  period.
- `tests/test_public_api.py`, static checks for current package-root
  entrypoints, explicit compatibility entrypoints, and denied internal leaks.

Narrowed:

- Top-level `skillfoundry` no longer exports FrontDesk Goal Runtime fake worker
  classes and result dataclasses.
- Top-level `skillfoundry` no longer exports Goal Runtime result/factory
  dataclasses.

Kept:

- Current top-level run functions and evidence helpers remain available.
- The removed types remain module-scoped in `skillfoundry.frontdesk_goal_runtime`
  and `skillfoundry.goal_runtime` for maintenance and focused tests.

Rationale:

- Fake worker/result/factory types are implementation details, not package-root
  API.
- A documented API contract is now available before the broader support-surface
  and graph/runtime export audits in Phases 13I and 13J.

## Current Keep List

Keep as current mainline or current dependency:

- `src/forgeunit_skillfoundry/`
- `src/skillfoundry/api.py`
- `src/skillfoundry/frontdesk.py`
- `src/skillfoundry/frontdesk_loop.py`
- `src/skillfoundry/frontdesk_schema.py`
- `src/skillfoundry/frontdesk_workspace.py`
- `src/skillfoundry/frontdesk_goal_runtime.py`
- `src/skillfoundry/frontdesk_v2.py`
- `src/skillfoundry/forgeunit_adapter.py`
- `src/skillfoundry/graph_v2.py`
- `src/skillfoundry/goal_runtime.py`
- `src/skillfoundry/contracts.py`
- `src/skillfoundry/verification_bridge.py`
- `src/skillfoundry/final_report.py`
- `src/skillfoundry/acceptance.py`
- `src/skillfoundry/verifier.py`
- `src/skillfoundry/registry.py`
- `src/skillfoundry/workspace.py`
- `src/skillfoundry/schema.py`
- `src/skillfoundry/security.py`

## Next Candidates

These modules need a separate audit before deletion or shrinking:

- `src/skillfoundry/offline.py`
  - Legacy deterministic offline CLI/test compatibility.
  - Final-report helpers have been extracted.
  - API/UI no longer create offline builds through `POST /jobs`.
  - `ops.py` no longer creates offline builds.
  - Still used by CLI build/verify/register commands and deterministic offline
    fixtures.
- `src/skillfoundry/worker.py`
  - Old WorkerAdapter/CodexWorker/FakeWorker path.
  - Still used by legacy tests, offline compatibility, verifier fixtures, and
    some current bridge tests.
  - No longer exported from the top-level package; import explicitly from
    `skillfoundry.worker` when maintaining legacy fixtures.
- `src/skillfoundry/context.py`
  - Old owned-call/context adapter.
  - Still referenced by FrontDesk and older LLM builder paths.
  - No longer exported from the top-level package; import explicitly from
    `skillfoundry.context` when maintaining legacy owned-call fixtures.
- `src/skillfoundry/feedback.py`, `src/skillfoundry/ops.py`, `src/skillfoundry/qa.py`
  - Product support surfaces from v0/WP phases.
  - Audited in Phase 13I and kept as module-scoped support surfaces.
  - Do not promote their support-only APIs back to the package root without
    updating `docs/PUBLIC_API.md`.
- `src/skillfoundry/__init__.py`
  - Public export surface is still broad, but legacy worker internals, offline
    helper internals, and legacy context adapter internals have been removed
    from the package root.
  - Phase 13H added a public API contract and removed obvious internal
    fake-worker/result/factory exports.
  - Phase 13I removed feedback/QA/ops support-only exports from the package
    root.
  - Phase 13J removed direct Goal Runtime and graph v2 compatibility helper
    exports from the package root, while keeping `seed_goal_harness_context`.
  - Continue shrinking after each legacy module is retired.

## Phase 13I

Status: implemented in this cleanup slice.

Classified:

- `src/skillfoundry/feedback.py` is a module-scoped WP11
  feedback/versioning support surface.
- `src/skillfoundry/qa.py` is a module-scoped WP10 deterministic QA support
  surface.
- `src/skillfoundry/ops.py` is a module-scoped WP12 local operations support
  surface for health, observability, and cleanup.

Narrowed:

- Top-level `skillfoundry` no longer exports feedback/versioning support names.
- Top-level `skillfoundry` no longer exports deterministic QA support names.
- Top-level `skillfoundry` no longer exports local ops support names.

Kept:

- Module-level imports from `skillfoundry.feedback`, `skillfoundry.qa`, and
  `skillfoundry.ops` remain available for focused tests, compatibility
  fixtures, and maintainers.
- Default deterministic validation remains unchanged.

Rationale:

- Feedback, QA, and local ops are useful support modules, but they are not the
  current package-root product construction path.
- Keeping them module-scoped reduces new-user confusion while preserving all
  tested behavior.

## Phase 13J

Status: implemented in this cleanup slice.

Classified:

- `src/skillfoundry/goal_runtime.py` remains the explicit module for direct
  Goal Runtime runners, state helpers, result refs, and compatibility helper
  functions.
- `src/skillfoundry/graph_v2.py` remains the explicit module for the legacy v2
  LangGraph compatibility spine, state shape, routes, node builders, compilers,
  and validators.
- `seed_goal_harness_context` remains top-level because it is a small current
  ContextForge evidence helper used by worker/context tests and belongs to the
  refs-only evidence path.

Narrowed:

- Top-level `skillfoundry` no longer exports direct Goal Runtime runner/state
  helper names.
- Top-level `skillfoundry` no longer exports graph v2 state, route, node,
  compiler, or validator names.

Kept:

- Module-level imports from `skillfoundry.goal_runtime` and
  `skillfoundry.graph_v2` remain available for ForgeUnit bridge maintenance,
  compatibility graph tests, and explicit runtime inspection.
- Current ForgeUnit and FrontDesk build behavior remains unchanged.

Rationale:

- Direct Goal Runtime runners and graph v2 helpers are powerful compatibility
  surfaces, but they are not the package-root entrypoint a new user should
  build against.
- Keeping these APIs module-scoped reduces package-root noise without hiding or
  deleting working runtime code.

## Phase 13K

Status: implemented in this cleanup slice.

Added:

- `docs/LEGACY_COMPATIBILITY.md`, a single index for remaining compatibility
  islands and archived WP/CodexWorker material.

Indexed:

- `skillfoundry.offline`
- `skillfoundry.worker`
- `skillfoundry.context`
- `skillfoundry.graph_v2`
- `skillfoundry.goal_runtime`
- `skillfoundry.feedback`
- `skillfoundry.qa`
- `skillfoundry.ops`
- archived WP0-WP17 roadmaps, agent briefs, pilots, and operations notes

Linked:

- `docs/README.md`
- `HANDOFF.md`

Rationale:

- Compatibility code should be visible and explainable before it is deleted.
- New users need one page that distinguishes current mainline, allowed
  maintenance/fixture uses, and forbidden new-product uses.

## Phase 13L

Status: implemented in this cleanup slice.

Added:

- `tests/README.md`, the test ownership map.

Classified:

- Current mainline tests.
- Compatibility tests.
- Legacy fixture tests.
- Script smoke tests.
- Live opt-in support.

Linked:

- `docs/README.md`
- `HANDOFF.md`

Rationale:

- The test suite intentionally keeps deterministic compatibility coverage, but
  those tests should not be mistaken for current architecture guidance.
- `make test` remains the full deterministic/offline gate and does not call live
  Codex.

## Test Ownership

Current mainline tests:

- `tests/test_forgeunit_skillfoundry_*.py`
- `tests/test_frontdesk_*.py`
- `tests/test_forgeunit_adapter.py`
- `tests/test_final_report.py`
- `tests/test_verification_bridge.py`
- `tests/test_registry.py`
- `tests/test_acceptance_coverage.py`
- `tests/test_graph_v2*.py`
- `tests/test_api.py`

Legacy/compatibility tests to audit next:

- `tests/test_offline.py`
- `tests/test_worker.py`
- `tests/test_codex_worker.py`
- `tests/test_context.py`
- `tests/test_feedback.py`
- `tests/test_ops.py`
- `tests/test_qa.py`

## Validation For Each Cleanup Slice

Run:

```bash
git diff --check
make focused
make test
```

Run fresh clone smoke before claiming a cleanup slice is ready for a new user:

```bash
make fresh-clone-smoke
```
