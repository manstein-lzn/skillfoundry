# Agent Brief WP7: Offline E2E MVP

## Mission

Implement SkillFoundry WP7: an offline end-to-end MVP that runs the local Codex Skill factory loop with no network and no real Codex Worker.

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

Read before editing:

- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `docs/WORK_PACKAGES.md`
- `docs/ACCEPTANCE_PLAN.md`
- `src/skillfoundry/workspace.py`
- `src/skillfoundry/graph.py`
- `src/skillfoundry/worker.py`
- `src/skillfoundry/verifier.py`
- `src/skillfoundry/context.py`
- `src/skillfoundry/registry.py`

## Scope

WP7 owns:

- Offline build/verify/register/report orchestration.
- A minimal CLI or equivalent command entrypoint.
- Sample requirements.
- E2E fixture cases.
- Repair loop using deterministic local worker behavior.
- Final report generation.
- Resume support using workspace refs and existing artifacts.
- E2E smoke tests.

Recommended files:

- `src/skillfoundry/offline.py`
- `src/skillfoundry/cli.py`
- `tests/test_offline.py`
- `examples/requirements/pytest_repair.md`
- update `src/skillfoundry/__init__.py`
- update `pyproject.toml` with a `skillfoundry` console script if a CLI is implemented.

## Non-goals

Do not implement:

- real Codex Worker;
- production queue;
- network dependency;
- full API/UI;
- marketplace;
- multi-tenant permissions;
- production sandbox;
- real model provider calls.

Do not bypass Verifier or Registry gates. Worker self-report is still not acceptance evidence.

## Required E2E Scenarios

Automated tests must prove:

- `build_new` normal path creates a package, verifier passes, registry entry is approved, final report exists.
- `reuse_existing` routes to an existing approved registry entry without building a new package.
- `reject_unsafe` rejects before build and does not write an approved registry entry.
- ambiguous requirement triggers clarification/human-review placeholder.
- first attempt intentionally fails, repair attempt passes verifier, registry accepts repaired package.
- path traversal fixture fails and does not register.
- attempt limit exceeded routes fail-closed or human review and does not register.
- resume can continue a partially completed workspace/job by reading refs/artifacts, not large transcript state.
- registry accepts only hash-matching package and final report links core evidence refs.

## Required Offline Commands

The exact CLI shape may differ, but tests must demonstrate equivalent command behavior. Suggested:

```bash
skillfoundry build --requirement examples/requirements/pytest_repair.md --output runs/demo-001
skillfoundry verify --job runs/demo-001
skillfoundry registry add --job runs/demo-001 --registry runs/registry.json
skillfoundry report --job runs/demo-001
```

If implementing an internal function API instead of shelling out in tests, still expose enough CLI code for a user to run the smoke locally.

## Required Final Report

Write a machine-readable final report, for example:

```text
runs/<job_id>/final_report.json
```

It must include refs or hashes for:

- build contract;
- skill spec;
- worker input;
- attempts;
- latest execution report;
- verifier result;
- registry entry when approved;
- artifact manifest;
- package hash;
- final status.

## Acceptance Criteria

- `src/skillfoundry/offline.py` exists.
- CLI or equivalent command entrypoint exists.
- `tests/test_offline.py` exists.
- sample requirement exists under `examples/requirements/`.
- Full offline happy path passes with Fake/local deterministic workers.
- repair-after-failure path passes and registers repaired package.
- failure scenarios fail closed and do not register.
- resume smoke passes.
- final report links core evidence refs.
- Registry entry hash matches package hash.
- No real Codex, network, real provider, API/UI, queue, or production sandbox is used.

Required command:

```bash
.venv/bin/python -m pytest -q
```

## Implementation Notes

- It is acceptable to define a WP7-only deterministic worker in `offline.py` or tests that produces a Verifier-valid package. Do not change WP3 FakeWorker semantics unless absolutely necessary.
- Prefer small explicit orchestration code over a large framework.
- Use existing WP1-WP6 public APIs.
- Keep state refs-only; large artifacts should remain files in the workspace.
- Use ContextForge adapter where useful for final evidence, but do not make WP7 depend on real LLM calls.
- Do not modify `.metaloop/`, `.venv/`, caches, unrelated docs, or previous WP behavior unless integration requires tiny exports/config updates.

## Expected Final Response From Worker

List:

- files changed;
- offline API/CLI shape;
- E2E scenarios implemented;
- tests run and exact result;
- any deviations.
