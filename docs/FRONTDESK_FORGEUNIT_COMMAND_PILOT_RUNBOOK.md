# FrontDesk ForgeUnit Command Pilot Runbook

Last updated: 2026-05-23

Status: manual pilot protocol, not default CI

## Purpose

This runbook is for the first real command-boundary pilot through the
FrontDesk API route:

```text
POST /frontdesk/jobs/{job_id}/build
```

The target path is:

```text
FrontDesk approved/frozen job
  -> ForgeUnit SkillFoundry vNext
  -> configured ForgeUnit/Codex command boundary
  -> package/evidence artifacts
  -> SkillFoundry Verifier
  -> acceptance coverage
  -> LocalSkillRegistry
  -> refs-only API/status/read models
```

The command result is never acceptance by itself. It is boundary evidence. The
Verifier and Registry remain the truth gates.

## Non-Goals

This pilot does not add:

- live Codex calls to pytest or default CI;
- scheduler, daemon, queue, or worker pool;
- Codex SDK thread lifecycle management;
- long-term memory;
- verifier or registry bypass;
- raw prompt, raw FrontDesk conversation, raw stdout/stderr, raw transcript, or
  package body in API responses.

## Configuration

The FrontDesk API vNext build command selection is:

```text
request payload fake_mode
request payload command / repair_command
SkillFoundryAPI(..., forgeunit_command=..., forgeunit_repair_command=...)
SKILLFOUNDRY_FORGEUNIT_COMMAND / SKILLFOUNDRY_FORGEUNIT_REPAIR_COMMAND
deterministic fake happy fallback
```

For a served process, use environment variables:

```bash
export SKILLFOUNDRY_FORGEUNIT_COMMAND=".venv/bin/python scripts/forgeunit_codex_exec_worker.py --codex-command 'codex exec'"

.venv/bin/python -m skillfoundry.cli serve \
  --runs-root runs \
  --registry .local/frontdesk_forgeunit_registry.json \
  --host 127.0.0.1 \
  --port 8765
```

For in-process Python tests or smoke scripts, prefer constructor injection:

```python
api = SkillFoundryAPI(
    "runs",
    forgeunit_command=".venv/bin/python scripts/forgeunit_codex_exec_worker.py --codex-command 'codex exec'",
)
```

Set `forgeunit_repair_command` or `SKILLFOUNDRY_FORGEUNIT_REPAIR_COMMAND` only
when intentionally testing the repair path. A successful command pilot should
run in `command_bridge` mode with no repair command configured.

## Worker Protocol

ForgeUnit runs the command with these environment variables:

```text
FORGEUNIT_TASK_DIR
FORGEUNIT_RUN_DIR
FORGEUNIT_UNIT
FORGEUNIT_TASK_PACKET
FORGEUNIT_WORKER_RESULT
```

The command must write these paths relative to `FORGEUNIT_TASK_DIR`:

```text
package/SKILL.md
evidence/transcript.md
evidence/manifest.json
```

It must also write the JSON file at `FORGEUNIT_WORKER_RESULT`, unless the
wrapper fills it in after validating the package/evidence files.

Minimum worker result shape:

```json
{
  "status": "completed",
  "output_artifacts": [
    {"path": "package/SKILL.md", "kind": "codex_skill", "summary": "Generated Codex Skill package."}
  ],
  "boundary_evidence": [
    {"path": "evidence/transcript.md", "kind": "transcript", "summary": "Boundary transcript summary."},
    {"path": "evidence/manifest.json", "kind": "worker_evidence_manifest", "summary": "Worker evidence manifest."}
  ],
  "changed_files": [
    "package/SKILL.md",
    "evidence/transcript.md",
    "evidence/manifest.json"
  ],
  "usage": null,
  "usage_unavailable_reason": "external_worker_no_provider_telemetry"
}
```

`package/SKILL.md` must satisfy the SkillFoundry verifier. At minimum it needs
these sections:

```text
Overview
When To Use
When Not To Use
Inputs
Outputs
Workflow
Safety
```

## Safe Failure Smoke

Before any live Codex pilot, run the deterministic local failing-command smoke:

```bash
.venv/bin/python -m pytest \
  tests/test_frontdesk_api.py::test_frontdesk_api_redacts_real_failing_subprocess_command_boundary \
  -q
```

This test executes an actual local subprocess through the ForgeUnit command
bridge. The subprocess writes stdout/stderr markers and a transcript marker to
local diagnostics/workspace files, then exits non-zero. The API must return only
a redacted `frontdesk_build_failed` response and must not return the command
string, script name, stdout/stderr markers, or transcript marker.

Expected result:

```text
1 passed
```

## Local Successful Pilot

Before replacing the deterministic command with live Codex, run the local
successful FrontDesk command pilot:

```bash
.venv/bin/python scripts/run_frontdesk_forgeunit_command_pilot.py \
  --runs-root .local/frontdesk_command_pilot_runs \
  --registry-path .local_registry/frontdesk_command_pilot_registry.json \
  --worker-dir .local/frontdesk_command_pilot_worker \
  --job-id frontdesk-local-command-pilot-001 \
  --overwrite
```

This script uses the same FrontDesk API flow as the manual server route:

```text
POST /frontdesk/jobs
POST /frontdesk/jobs/{job_id}/plan-review
POST /frontdesk/jobs/{job_id}/build
GET /jobs/{job_id}/contextforge
```

It writes a deterministic local subprocess worker, configures it as
`forgeunit_command`, and prints a refs-only pilot summary. It must complete with:

```text
status == registered
build_path.mode == forgeunit_skillfoundry_vnext
forgeunit_skillfoundry.mode == command_bridge
forgeunit_skillfoundry.verification_passed == true
forgeunit_skillfoundry.registry_approved == true
forgeunit_skillfoundry.command_string_included == false
```

The summary must not include the worker command, worker script path/name, raw
prompt, raw FrontDesk conversation, transcript body, worker input body, or
package body.

## Live Codex Exec Pilot

Status: completed once on 2026-05-23 through the in-process FrontDesk API pilot
script. This remains an explicit manual smoke, not pytest/default CI.

The completed pilot used the same route as the local successful pilot, with
`--command` set to the thin wrapper around live `codex exec`:

```bash
REPO_ROOT="$(pwd)"
PYTHON="$REPO_ROOT/.venv/bin/python"
WRAPPER="$REPO_ROOT/scripts/forgeunit_codex_exec_worker.py"

"$PYTHON" scripts/run_frontdesk_forgeunit_command_pilot.py \
  --runs-root .local/frontdesk_live_codex_pilot_runs \
  --registry-path .local_registry/frontdesk_live_codex_pilot_registry.json \
  --worker-dir .local/frontdesk_live_codex_pilot_worker \
  --job-id frontdesk-live-codex-pilot-001 \
  --version frontdesk-live-codex-pilot \
  --created-at 2026-05-23T00:00:00Z \
  --command "$PYTHON $WRAPPER --timeout 1800 --codex-command 'codex exec --sandbox workspace-write --skip-git-repo-check -'" \
  --overwrite
```

Observed refs-only result:

```text
status == registered
build_path.mode == forgeunit_skillfoundry_vnext
forgeunit_skillfoundry.mode == command_bridge
forgeunit_skillfoundry.verification_passed == true
forgeunit_skillfoundry.registry_approved == true
forgeunit_skillfoundry.registry_skill_id == frontdesk-governed-skill
forgeunit_skillfoundry.registry_version == frontdesk-live-codex-pilot
forgeunit_skillfoundry.command_string_included == false
forgeunit_skillfoundry.raw_prompt_included == false
forgeunit_skillfoundry.raw_transcript_included == false
forgeunit_skillfoundry.raw_worker_input_included == false
package_downloadable == true
```

Locked MetaLoop evidence for that run:

```text
.metaloop/phase8d_live_codex_pilot_summary.json
.local/frontdesk_live_codex_pilot_runs/frontdesk-live-codex-pilot-001/package/SKILL.md
.local/frontdesk_live_codex_pilot_runs/frontdesk-live-codex-pilot-001/evidence/transcript.md
.local/frontdesk_live_codex_pilot_runs/frontdesk-live-codex-pilot-001/evidence/manifest.json
.local/frontdesk_live_codex_pilot_runs/frontdesk-live-codex-pilot-001/contextforge/forgeunit_skillfoundry_summary.json
.local/frontdesk_live_codex_pilot_runs/frontdesk-live-codex-pilot-001/contextforge/forgeunit_skillfoundry_product_state.json
.local/frontdesk_live_codex_pilot_runs/frontdesk-live-codex-pilot-001/verifier/verification_result.json
.local/frontdesk_live_codex_pilot_runs/frontdesk-live-codex-pilot-001/registry/decision.json
.local/frontdesk_live_codex_pilot_runs/frontdesk-live-codex-pilot-001/registry/entry.json
.local/frontdesk_live_codex_pilot_runs/frontdesk-live-codex-pilot-001/final_report.json
```

The validation scanned the public pilot summary and product read models for the
wrapper script name/path, live command flags, ForgeUnit worker env names, and
the raw FrontDesk message; none were present. Lower-level diagnostics and raw
worker artifacts remain local files only and are not API/status output.

## Scenario Eval Harness

After the one-off live pilot succeeds, use the scenario eval harness to measure
repeatability across multiple FrontDesk tasks. This is still manual/operator
tooling and is not wired into pytest or default CI.

Offline smoke:

```bash
.venv/bin/python scripts/run_frontdesk_live_codex_eval.py \
  --runs-root .local/frontdesk_live_codex_eval_runs \
  --eval-id frontdesk-live-codex-eval-smoke \
  --registry-path .local_registry/frontdesk_live_codex_eval_registry.json \
  --fake-mode happy \
  --limit 2 \
  --overwrite
```

Manual live run:

```bash
REPO_ROOT="$(pwd)"
PYTHON="$REPO_ROOT/.venv/bin/python"
WRAPPER="$REPO_ROOT/scripts/forgeunit_codex_exec_worker.py"

"$PYTHON" scripts/run_frontdesk_live_codex_eval.py \
  --runs-root .local/frontdesk_live_codex_eval_runs \
  --eval-id frontdesk-live-codex-eval-001 \
  --registry-path .local_registry/frontdesk_live_codex_eval_registry.json \
  --command "$PYTHON $WRAPPER --timeout 1800 --codex-command 'codex exec --sandbox workspace-write --skip-git-repo-check -'" \
  --overwrite
```

The harness has built-in scenarios for pytest failure analysis, repository
handoff, API docs summarization, incident triage, and code review checklists.
Operators can replace them with a JSON scenario file:

```json
{
  "scenarios": [
    {
      "id": "pytest-failure",
      "message": "Build a governed Codex skill for analyzing pasted pytest failures."
    }
  ]
}
```

The output is written to:

```text
.local/frontdesk_live_codex_eval_runs/<eval-id>/eval_summary.json
```

The eval summary includes scenario ids, job ids, status, verification/registry
outcomes, duration, failure taxonomy, artifact refs, and redaction findings. It
does not include command strings, raw prompts, raw FrontDesk conversation, raw
worker input, raw transcripts, stdout/stderr, package bodies, or worker script
paths.

## Manual FrontDesk API Flow

Start the server with `SKILLFOUNDRY_FORGEUNIT_COMMAND` configured, then create a
FrontDesk job:

```bash
curl -s -X POST http://127.0.0.1:8765/frontdesk/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "job_id": "frontdesk-real-command-pilot-001",
    "message": "Build a governed Codex skill for analyzing pasted pytest failures."
  }'
```

Approve the generated plan:

```bash
curl -s -X POST http://127.0.0.1:8765/frontdesk/jobs/frontdesk-real-command-pilot-001/plan-review \
  -H 'Content-Type: application/json' \
  -d '{
    "decision": "approve",
    "reason": "Manual pilot plan approved."
  }'
```

Run the build:

```bash
curl -s -X POST http://127.0.0.1:8765/frontdesk/jobs/frontdesk-real-command-pilot-001/build \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Inspect refs-only status:

```bash
curl -s http://127.0.0.1:8765/jobs/frontdesk-real-command-pilot-001/contextforge
```

## Success Checks

The build response should include:

```text
status == registered
build_path.mode == forgeunit_skillfoundry_vnext
forgeunit_skillfoundry_summary.verification.passed == true
forgeunit_skillfoundry_summary.registry.approved == true
forgeunit_skillfoundry_summary.trust_boundaries.command_string_included == false
graph_v2_state_ref == null
```

Expected files:

```text
runs/frontdesk-real-command-pilot-001/package/SKILL.md
runs/frontdesk-real-command-pilot-001/evidence/transcript.md
runs/frontdesk-real-command-pilot-001/evidence/manifest.json
runs/frontdesk-real-command-pilot-001/contextforge/forgeunit_skillfoundry_summary.json
runs/frontdesk-real-command-pilot-001/contextforge/forgeunit_skillfoundry_product_state.json
runs/frontdesk-real-command-pilot-001/contextforge/forgeunit_skillfoundry_graph_state.json
runs/frontdesk-real-command-pilot-001/verifier/verification_result.json
runs/frontdesk-real-command-pilot-001/registry/decision.json
runs/frontdesk-real-command-pilot-001/registry/entry.json
runs/frontdesk-real-command-pilot-001/final_report.json
```

## Redaction Checks

API responses and `/jobs/{job_id}/contextforge` must not contain:

```text
SKILLFOUNDRY_FORGEUNIT_COMMAND value
script path or script name
raw prompt
raw FrontDesk conversation
raw worker input
raw stdout
raw stderr
raw transcript body
package/SKILL.md body
```

Failure responses should use fixed messages:

```text
frontdesk_build_failed:
frontdesk ForgeUnit vNext build failed before producing a verified refs-only result

frontdesk_build_missing_summary:
frontdesk ForgeUnit vNext build did not write a valid refs-only summary
```

Lower-level diagnostics may exist on disk under the workspace or `.forgeunit`
run directory, but they must not be returned through the API.

## When To Stop

Stop the pilot and inspect local diagnostics if:

- `frontdesk_build_failed` is returned;
- `frontdesk_build_missing_report` is returned;
- `frontdesk_build_missing_summary` is returned;
- verifier status is not `passed`;
- registry approval is not true;
- any API/status body includes command strings, raw stdout/stderr, transcript
  body, raw conversation, or package body.

Do not make the command more autonomous to bypass these failures. Fix the
worker protocol or package quality, then rerun the same FrontDesk build path.
