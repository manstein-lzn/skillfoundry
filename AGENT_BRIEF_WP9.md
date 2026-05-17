# Agent Brief WP9: Minimal API/UI

## Mission

Implement SkillFoundry WP9: a minimal internal API/UI entry for the existing offline Skill factory.

This is an implementation task for a 5.5-xhigh worker. The architect will review independently.

## Context

Repository: `/home/mansteinl/skillfoundry`

Already completed:

- WP1: workspace, schema, artifact manifest, path confinement.
- WP2: LangGraph skeleton and refs-only state.
- WP3: WorkerAdapter and FakeWorker boundary.
- WP4: independent Verifier.
- WP5: ContextForge evidence boundary.
- WP6: local verified Skill Registry.
- WP7: offline E2E MVP with CLI, final report, repair loop, resume, and Registry gate.
- WP8: optional CodexWorker pilot adapter. Live Codex remains opt-in and must not be required by WP9 tests.

WP9 should expose the existing offline flow to an internal user without turning the project into a production platform.

## Scope

WP9 owns:

- Minimal create-job API.
- Minimal list/get-job API.
- Final report view.
- Registry query API.
- Approved package download API.
- Minimal HTML UI or static report page.
- Optional `skillfoundry serve` CLI entrypoint.
- Tests for request handling, package download gates, and path safety.

Recommended files:

- `src/skillfoundry/api.py`
- `tests/test_api.py`
- update `src/skillfoundry/cli.py` if adding `serve`
- update `src/skillfoundry/__init__.py` for public API exports if needed
- optional `docs/API_UI.md`

Prefer standard library HTTP server or very small dependencies. Do not add a heavy frontend framework.

## Non-goals

Do not implement:

- production queue;
- marketplace;
- multi-tenant permission system;
- full auth platform;
- production deployment stack;
- WP10 QA Lab;
- WP11 feedback/versioning;
- live Codex invocation by default.

Do not expose:

- files outside configured runs root;
- unverified package downloads as approved;
- Codex internal prompt/tool-loop/cache/cost as replayable ContextForge evidence.

## Required Behavior

API capabilities:

- create a synchronous job from JSON requirement text:
  - `POST /jobs`
  - body may include `job_id`, `requirement`, optional `worker_mode`, optional `attempt_limit`
  - writes requirement under the configured runs root, calls `build_offline`, returns final report summary
- list jobs:
  - `GET /jobs`
  - returns known jobs from `runs_root`
- get one job:
  - `GET /jobs/<job_id>`
  - returns final report if present, otherwise a safe status object
- get final report:
  - `GET /jobs/<job_id>/report`
- query registry:
  - `GET /registry`
  - returns approved, non-quarantined entries by default
- download approved package:
  - `GET /jobs/<job_id>/package.zip`
  - only works when the job has a final report with `final_status == "registered"` and registry entry approval is `approved`
  - archive must contain files under `package/` only
  - verifier-failed, rejected, human-review, reused-without-local-package, or missing package jobs must not download as approved
- minimal UI:
  - `GET /`
  - show job list, registry summary, links to reports/downloads when approved

Implementation shape can be direct function calls around a standard-library request handler. Tests do not need to start a persistent server if an in-process client/helper is cleaner.

## Security Requirements

- `job_id` must be a safe path segment.
- API must reject `..`, absolute paths, and unknown artifact paths.
- Package download must zip only files below `job_root/package`.
- API responses must not leak arbitrary local files.
- UI must not show verifier-failed packages as approved.

## Required Tests

Automated tests must prove:

- `POST /jobs` or equivalent handler creates a job, returns `registered`, writes `final_report.json`.
- `GET /jobs` lists created jobs.
- `GET /jobs/<job_id>/report` returns final report.
- `GET /registry` returns approved registry entries.
- approved job package download returns a zip containing `package/SKILL.md`.
- rejected/unsafe or failed job package download is denied.
- path traversal job id or artifact path is rejected.
- HTML UI renders job/report/registry links and does not mark failed jobs as approved.
- default tests do not require live Codex or network.

## Acceptance Criteria

- `src/skillfoundry/api.py` exists.
- `tests/test_api.py` exists.
- Full test suite passes:

```bash
.venv/bin/python -m pytest -q
```

- API/UI is explicitly minimal/internal.
- No production queue or multi-tenant permission system is introduced.
- Approved download gate is covered by tests.
- Existing WP7 CLI and WP8 CodexWorker tests still pass.

## Expected Final Response From Worker

List:

- files changed;
- API routes and UI shape;
- tests implemented;
- tests run and exact result;
- deviations or blockers.

