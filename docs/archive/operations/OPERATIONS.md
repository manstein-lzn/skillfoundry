# SkillFoundry Operations

WP12 keeps SkillFoundry ready for small-scale internal beta use. The operations
surface is local, deterministic, and filesystem-backed; it does not add a
production queue, external service, database, auth platform, or marketplace.

## Filesystem Layout

Default local layout:

```text
runs/
  registry.json                 # JSON LocalSkillRegistry store
  .registry.json.lock           # sidecar registry write lock
  <job-id>/
    build_contract.yaml         # locked input
    skill_spec.yaml             # locked input
    verification_spec.yaml      # locked input
    worker_input.md             # locked input
    artifact_manifest.json      # provenance and hash manifest
    attempts/<id>/              # worker boundary artifacts
    package/                    # approved package root after registration
    verifier/verification_result.json
    qa/quality_report.json      # optional WP10 QA report
    final_report.json
```

Safe job ids are one path segment matching `^[A-Za-z0-9][A-Za-z0-9_.-]*$`.
The registry should be under the runs root or its owning project directory, and
must not be placed inside an individual job workspace.

## Running Tests

Default verification command:

```bash
.venv/bin/python -m pytest -q
```

Run only WP12 operations tests:

```bash
.venv/bin/python -m pytest tests/test_ops.py -q
```

The default tests are deterministic and offline. They use the offline worker,
Verifier, QA Lab, registry, and local filesystem only.

## Offline Build Loop

Run a single local build, verify, register, and final-report flow:

```bash
.venv/bin/python -m skillfoundry.cli build \
  --requirement requirement.md \
  --output runs/demo-001 \
  --registry runs/registry.json
```

The command exits `0` for `registered` or `reused` and exits `2` for fail-closed
or rejected outcomes. The machine-readable result is written to
`runs/<job-id>/final_report.json` and printed to stdout.

## Minimal API/UI

Run the WP9 minimal internal API/UI:

```bash
.venv/bin/python -m skillfoundry.cli serve \
  --runs-root runs \
  --registry runs/registry.json \
  --host 127.0.0.1 \
  --port 8765
```

Open `http://127.0.0.1:8765/` for the HTML UI. Legacy offline creation through
`POST /jobs` has been retired; current product builds use the FrontDesk
approved/frozen job flow and graph v2 build endpoint. The server does not
provide auth, multi-tenant isolation, a queue, or live worker scheduling.

Useful endpoints:

```text
GET  /
POST /jobs                         # retired; returns legacy_offline_jobs_retired
GET  /jobs
GET  /jobs/<job-id>
GET  /jobs/<job-id>/report
GET  /jobs/<job-id>/package.zip
GET  /registry
POST /frontdesk/jobs
POST /frontdesk/jobs/<job-id>/build
```

## Health and Readiness

Use the WP12 ops helper through Python:

```python
from skillfoundry import SkillFoundryOps

ops = SkillFoundryOps("runs", registry_path="runs/registry.json")
health = ops.health_check()
```

Or through the CLI:

```bash
.venv/bin/python -m skillfoundry.cli ops \
  --runs-root runs \
  --registry runs/registry.json \
  health
```

The health report is machine-readable JSON. It checks:

- runs root existence;
- runs root writability;
- registry path control;
- registry parseability when present;
- workspace path sanity;
- package import readiness;
- CLI import readiness;
- documented test command.

`ready` is true only when every error-severity check passes.

## Observability

Generate a local observability report:

```bash
.venv/bin/python -m skillfoundry.cli ops \
  --runs-root runs \
  --registry runs/registry.json \
  observability
```

Python API:

```python
report = SkillFoundryOps("runs").observability_report()
```

The report summarizes:

- job count and final status distribution;
- failed jobs and failure classes;
- attempt counts;
- verifier pass/fail/missing/invalid counts;
- QA pass/fail/missing/invalid counts;
- registry approved/quarantined/rejected counts;
- feedback records, repair plans, version-change reports, rollback events, and
  registry feedback-versioning provenance;
- duration availability and total duration when execution reports contain it;
- usage availability and unavailable reasons.

Usage is normally unavailable for deterministic offline workers because they do
not call model providers. CodexWorker pilot usage is also unavailable at the CLI
boundary unless a future worker boundary exposes reliable provider counters.

## Cleanup

Cleanup is intentionally conservative. It removes only known transient files and
directories:

- files ending in `.tmp`, `.temp`, `.bak`, `.swp`, `.pyc`, or `.pyo`;
- directories named `__pycache__`, `.pytest_cache`, `.mypy_cache`, or
  `.ruff_cache`;
- health probe temp files.

Dry-run is the default:

```bash
.venv/bin/python -m skillfoundry.cli ops \
  --runs-root runs \
  --registry runs/registry.json \
  cleanup
```

Apply cleanup explicitly:

```bash
.venv/bin/python -m skillfoundry.cli ops \
  --runs-root runs \
  --registry runs/registry.json \
  cleanup --apply
```

Python API:

```python
dry_run = SkillFoundryOps("runs").cleanup_artifacts(dry_run=True)
applied = SkillFoundryOps("runs").cleanup_artifacts(dry_run=False)
```

Cleanup preserves locked inputs, final reports, verifier results, QA reports,
registry evidence, approved packages, feedback/versioning reports, rollback
events, and attempt provenance files. Symlinks are skipped rather than followed.

## Concurrent Internal Runs

Historical note: `SkillFoundryOps.build_jobs_concurrently()` was retired during
source cleanup. The current ops surface is health, observability, and cleanup
for existing workspaces. Use explicit CLI/dev fixtures for deterministic
offline build compatibility.
