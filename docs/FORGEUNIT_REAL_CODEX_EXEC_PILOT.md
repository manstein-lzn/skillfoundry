# ForgeUnit Real Codex Exec Manual Pilot

Last updated: 2026-05-23

Status: manual integration pilot, not default CI

## Purpose

This pilot checks whether a real Codex-compatible command can work inside the
ForgeUnit boundary contract and still be judged by SkillFoundry's existing
Verifier and LocalSkillRegistry gates.

The expected path is:

```text
SkillFoundry JobWorkspace
  -> ForgeUnit task.yaml
  -> ForgeUnit codex_exec adapter
  -> scripts/forgeunit_codex_exec_worker.py
  -> real codex exec or explicit fake command
  -> package/SKILL.md
  -> evidence/transcript.md
  -> evidence/manifest.json
  -> ForgeUnit worker_result.json
  -> SkillFoundry attempts/001 evidence bridge
  -> Verifier
  -> LocalSkillRegistry
  -> final_report.json
```

The worker result is not acceptance. It is only boundary evidence for ForgeUnit
ingest. The independent SkillFoundry verifier and registry gate remain the
truth gates.

## Non-Goals

This pilot does not add:

- live Codex calls to default pytest;
- CI dependency on local Codex CLI credentials;
- Codex SDK thread lifecycle;
- repair loop;
- scheduler, daemon, queue, or worker pool;
- long-term memory;
- SkillFoundry full migration to ForgeUnit;
- verifier bypass based on worker self-report.

## Wrapper

The boundary wrapper is:

```text
scripts/forgeunit_codex_exec_worker.py
```

ForgeUnit invokes it through the `command=` parameter. The wrapper reads the
ForgeUnit environment:

```text
FORGEUNIT_TASK_DIR
FORGEUNIT_RUN_DIR
FORGEUNIT_UNIT
FORGEUNIT_WORKER_RESULT
FORGEUNIT_CODEX_EXEC_PROMPT
FORGEUNIT_EVIDENCE_MANIFEST
```

It then invokes a Codex-compatible command. Command selection order:

```text
--codex-command
FORGEUNIT_CODEX_COMMAND
codex exec
```

The command receives the ForgeUnit prompt plus an appended boundary contract on
stdin. The wrapper does not write the raw prompt, raw command stdout, or raw
command stderr into graph state.

## Required Outputs

The Codex-compatible command should write:

```text
package/SKILL.md
evidence/transcript.md
evidence/manifest.json
$FORGEUNIT_WORKER_RESULT
```

The wrapper will fail if `package/SKILL.md` is missing. It can write a minimal
`evidence/transcript.md`, `evidence/manifest.json`, and worker result when the
Codex-compatible command produced the package but did not write those protocol
files itself.

`package/SKILL.md` must satisfy the SkillFoundry verifier sections:

```text
Overview
When To Use
When Not To Use
Inputs
Outputs
Workflow
Safety
```

## Manual Run

From the repository root:

```bash
.venv/bin/python scripts/run_forgeunit_real_codex_exec_pilot.py --overwrite
```

To pass a specific command:

```bash
.venv/bin/python scripts/run_forgeunit_real_codex_exec_pilot.py \
  --overwrite \
  --codex-command "codex exec"
```

You can also use an environment variable:

```bash
FORGEUNIT_CODEX_COMMAND="codex exec" \
.venv/bin/python scripts/run_forgeunit_real_codex_exec_pilot.py --overwrite
```

The runner initializes:

```text
runs/forgeunit-real-codex-pilot-001/
.local/forgeunit_codex_pilot_registry.json
```

It prints a refs-only summary:

```json
{
  "job_id": "forgeunit-real-codex-pilot-001",
  "stage": "emit_report",
  "status": "report_emitted",
  "last_verification_status": "passed",
  "registry_approved": true
}
```

## Expected Artifacts

On success:

```text
runs/forgeunit-real-codex-pilot-001/package/SKILL.md
runs/forgeunit-real-codex-pilot-001/evidence/manifest.json
runs/forgeunit-real-codex-pilot-001/evidence/transcript.md
runs/forgeunit-real-codex-pilot-001/attempts/001/input_manifest.json
runs/forgeunit-real-codex-pilot-001/attempts/001/execution_report.json
runs/forgeunit-real-codex-pilot-001/verifier/verification_result.json
runs/forgeunit-real-codex-pilot-001/registry/decision.json
runs/forgeunit-real-codex-pilot-001/registry/entry.json
runs/forgeunit-real-codex-pilot-001/final_report.json
```

## Failure Diagnostics

The wrapper is designed to fail with actionable messages for protocol errors:

```text
codex command missing
codex command is empty
codex exec command failed
package/SKILL.md was not produced
evidence/manifest.json has invalid schema
worker_result is missing output artifact
worker_result is missing boundary evidence
changed file outside package/evidence write scope
```

Wrapper diagnostics are written under:

```text
.forgeunit/runs/<run_id>/workers/forgeunit_codex_exec_worker_result.json
```

This diagnostic JSON records command status and byte counts only. It does not
store raw prompt, stdout, or stderr.

## Default Test Policy

Default tests remain offline and deterministic. They use fake Codex commands to
exercise the wrapper and the ForgeUnit command bridge.

Run the focused tests:

```bash
.venv/bin/python -m pytest \
  tests/test_forgeunit_adapter.py \
  tests/test_graph_v2.py \
  tests/test_registry.py \
  tests/test_verifier.py \
  tests/test_forgeunit_real_codex_pilot_scripts.py \
  -q
```

Run all tests:

```bash
.venv/bin/python -m pytest -q
```

Live Codex is only used when an operator explicitly runs the manual pilot.
