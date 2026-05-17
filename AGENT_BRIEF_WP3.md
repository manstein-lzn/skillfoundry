# Agent Brief WP3: WorkerAdapter + FakeWorker

## Mission

Implement SkillFoundry WP3: the external worker boundary and a deterministic `FakeWorker`.

This is an implementation task for a 5.5-xhigh worker. The architect will review independently.

## Context

Repository: `/home/mansteinl/skillfoundry`

Already completed:

- WP1: schema, workspace, artifact manifest, path confinement.
- WP2: LangGraph skeleton with refs-only state.

Read before editing:

- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `docs/WORK_PACKAGES.md`
- `docs/ACCEPTANCE_PLAN.md`
- `src/skillfoundry/schema.py`
- `src/skillfoundry/workspace.py`
- `src/skillfoundry/security.py`
- `src/skillfoundry/graph.py`

## Scope

WP3 owns:

- `BuildWorker` interface or protocol.
- `WorkerAdapter` data structures as needed.
- `FakeWorker`.
- `CodexWorker` placeholder or adapter skeleton that explicitly does not run real Codex yet.
- Worker invocation preparation.
- Attempt directory protocol.
- Input manifest generation.
- Transcript artifact.
- Output diff or deterministic summary patch.
- Execution report.
- Workspace hash before/after.
- Timeout and attempt-limit checks.
- Env allowlist and writable path allowlist representation.
- Usage availability fields.

Recommended files:

- `src/skillfoundry/worker.py`
- `tests/test_worker.py`
- update `src/skillfoundry/__init__.py`

## Non-goals

Do not implement:

- real Codex CLI/SDK invocation;
- full Verifier business rules;
- Registry approval or persistence;
- ContextForge integration;
- API/UI;
- real shell/MCP/action runtime;
- LLM calls.

Do not treat builder self-report as acceptance. WP3 may record worker status, but WP4 Verifier is still the quality gate.

## Required FakeWorker Fixtures

Implement deterministic modes or fixtures for:

- `minimal_success`: creates a minimal package with `package/SKILL.md`.
- `intentional_failure`: creates a structurally incomplete or obviously failing package but still writes boundary artifacts.
- `repair_success`: uses repair input or fixture mode to write a corrected package.
- `missing_report`: simulates a worker that does not produce `execution_report.json`; the adapter must classify this as failure and must not report a pass-equivalent result.
- `path_escape`: simulates a worker attempting to write outside allowed paths; the adapter must reject it.

## Boundary Requirements

Each worker invocation must record:

- invocation id;
- job id;
- attempt id;
- worker type;
- adapter version;
- input manifest hash;
- workspace hash before;
- workspace hash after;
- started/finished timestamps;
- duration;
- usage availability and unavailable reason;
- transcript ref;
- execution report ref;
- diff ref;
- exit status.

Each attempt should use:

```text
attempts/<attempt_id>/
  input_manifest.json
  execution_report.json
  output_diff.patch
  worker_transcript.log
```

The worker may write only:

- `package/`
- `attempts/<attempt_id>/`

All paths must go through WP1 path confinement helpers. Do not use raw path joins for untrusted relative paths.

## Acceptance Criteria

Automated tests must prove:

- FakeWorker `minimal_success` creates `package/SKILL.md`.
- FakeWorker `intentional_failure` creates a failing/incomplete package and records failure status.
- FakeWorker `repair_success` can repair after a previous failed attempt.
- `path_escape` is rejected and does not create files outside the job workspace.
- `missing_report` is classified as failure and does not produce a success result.
- Invocation records duration, exit status, refs, workspace before/after hash, input manifest hash, and usage unavailable reason.
- Attempt limit is enforced.
- Timeout behavior is represented and tested. It can be simulated deterministically; do not rely on slow sleeps.
- Output diff/transcript/execution report artifacts are written for normal worker runs.
- Tests demonstrate that worker outputs still require future Verifier approval and are not treated as final acceptance.

Required command:

```bash
.venv/bin/python -m pytest -q
```

## Implementation Notes

- Prefer deterministic local file writes over subprocesses.
- Keep the adapter API narrow and stable for WP8 CodexWorker pilot.
- If you add new schema classes, keep them JSON/YAML serializable and covered by tests.
- Do not make the worker modify locked inputs.
- Do not change `.metaloop/`, `.venv/`, caches, or unrelated files.

## Expected Final Response From Worker

List:

- files changed;
- worker API shape;
- FakeWorker fixtures implemented;
- tests run and exact result;
- any deviations.
