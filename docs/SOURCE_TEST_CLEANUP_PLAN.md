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
  - Still used by CLI build/verify/register commands, ops tests, and
    deterministic offline fixtures.
- `src/skillfoundry/worker.py`
  - Old WorkerAdapter/CodexWorker/FakeWorker path.
  - Still used by legacy tests, offline compatibility, verifier fixtures, and
    some current bridge tests.
- `src/skillfoundry/context.py`
  - Old owned-call/context adapter.
  - Still referenced by FrontDesk and older LLM builder paths.
- `src/skillfoundry/feedback.py`, `src/skillfoundry/ops.py`, `src/skillfoundry/qa.py`
  - Product support surfaces from v0/WP phases.
  - Need per-module dependency checks.
- `src/skillfoundry/__init__.py`
  - Public export surface is still too broad.
  - Shrink after each legacy module is retired.

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
