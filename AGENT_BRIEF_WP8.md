# Agent Brief WP8: CodexWorker Pilot

## Mission

Implement SkillFoundry WP8: a real CodexWorker pilot boundary behind the existing `BuildWorker` / `WorkerAdapter` protocol.

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

Local Codex CLI appears available:

```bash
codex exec --help
```

WP8 must keep live Codex invocation **opt-in**. Default automated tests must not require network, provider availability, or a real Codex session.

## Scope

WP8 owns:

- Replacing the WP3 placeholder `CodexWorker` with a real adapter shape.
- Codex command assembly for `codex exec`.
- A deterministic command runner abstraction so tests can validate behavior without live Codex.
- Transcript capture.
- Timeout and nonzero-exit classification.
- Usage availability handling.
- Optional/manual pilot entrypoint or documented command.
- Tests proving command assembly, transcript handling, failure classification, and no Verifier/Registry bypass.

Recommended files:

- `src/skillfoundry/worker.py`
- `tests/test_codex_worker.py`
- optional `docs/CODEX_WORKER_PILOT.md`
- optional `examples/requirements/codex_pilot.md`
- tiny updates to `src/skillfoundry/__init__.py` if new public types are introduced.

## Non-goals

Do not implement:

- production sandbox;
- production queue;
- API/UI;
- marketplace;
- multi-tenant permissions;
- complete ActionRuntime;
- ContextForge replay of Codex internals;
- default pytest that invokes live Codex.

Do not bypass:

- `WorkerAdapter`;
- workspace path confinement;
- independent `Verifier`;
- `LocalSkillRegistry`;
- artifact refs and hashes.

CodexWorker self-report is not acceptance evidence.

## Required Behavior

`CodexWorker` should:

- implement the existing `BuildWorker` protocol;
- have a stable `worker_type`, for example `codex:exec`;
- assemble a `codex exec` command with:
  - `--cd <workspace root>`;
  - `--sandbox workspace-write` or a safer configured mode;
  - `--ask-for-approval never` for non-interactive pilot use;
  - optional `--model`;
  - optional `--profile`;
  - optional extra config flags if needed;
  - a prompt that tells Codex to write only under `package/` and current `attempts/<id>/`;
- pass the prompt through stdin or argument safely;
- capture stdout/stderr as transcript lines;
- map successful command completion to `WorkerExecutionOutcome(status="completed", exit_status="success", ...)`;
- map timeout to `status="failed"`, `exit_status="timeout"`;
- map nonzero exit to `status="failed"`, `exit_status="failure"`;
- map missing expected package files to failure;
- record `usage_available=False` and a clear `usage_unavailable_reason` unless reliable usage is available from the CLI boundary.

The adapter may not claim to control or replay Codex internal prompt planning, tool loop, compaction, cache, or cost.

## Required Tests

Automated tests must prove, without invoking live Codex:

- command assembly uses `codex exec` and the configured workspace root;
- prompt includes workspace write constraints and required package output;
- successful fake command creates a Verifier-valid package and can pass Verifier through `WorkerAdapter`;
- nonzero command exit creates a failed execution report and is not ready for verifier approval;
- timeout creates a failed execution report and records timeout classification;
- missing package output fails closed;
- usage unavailable reason is present;
- `WorkerAdapter(CodexWorker(...))` still writes standard attempt artifacts:
  - `attempts/<id>/input_manifest.json`
  - `attempts/<id>/execution_report.json`
  - `attempts/<id>/output_diff.patch`
  - `attempts/<id>/worker_transcript.log`
- no test requires network, live provider, or real Codex.

If an opt-in live pilot test is added, gate it behind an environment variable such as:

```bash
SKILLFOUNDRY_RUN_CODEX_PILOT=1
```

and skip by default.

## Optional Manual Pilot

Provide a clear command or doc section for a human/operator to run a real pilot after tests pass.

The pilot should:

- initialize a small job workspace;
- invoke `CodexWorker` through `WorkerAdapter`;
- run `Verifier`;
- register only if Verifier passes;
- produce a short pilot report or final report.

It is acceptable for WP8 to ship the opt-in pilot harness even if the live pilot is not executed during default automated validation.

## Acceptance Criteria

- `CodexWorker` is no longer a pure unsupported placeholder.
- Default tests validate the adapter behavior with a fake command runner.
- Full test suite passes:

```bash
.venv/bin/python -m pytest -q
```

- Live Codex invocation is opt-in, not default.
- Existing WP7 offline flow still passes.
- Verifier and Registry gates remain the final trust boundary.
- Docs explicitly state that Codex internals are external boundary evidence only.

## Expected Final Response From Worker

List:

- files changed;
- CodexWorker API/config shape;
- tests implemented;
- tests run and exact result;
- whether any live pilot was run;
- deviations or blockers.

