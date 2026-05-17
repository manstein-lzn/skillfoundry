# Agent Brief WP12: Production Hardening

## Mission

Implement SkillFoundry WP12: production hardening for small-scale internal beta readiness.

This is an implementation task for a 5.5-xhigh worker. The architect will review independently.

## Context

Repository: `/home/mansteinl/skillfoundry`

Already completed:

- WP7: offline E2E build/verify/repair/register/report.
- WP8: optional CodexWorker pilot boundary.
- WP9: minimal internal API/UI.
- WP10: QA Lab quality report.
- WP11: feedback-driven version governance.

WP12 should harden the existing loop. It should not expand product scope into a full production platform.

## Scope

WP12 owns:

- Small-scale concurrency safety.
- Registry write hardening.
- Artifact retention/cleanup.
- Observability reports.
- Health/readiness checks.
- Security checklist.
- Performance/migration report.
- Production readiness report.
- Tests proving core hardening behavior.

Recommended files:

- `src/skillfoundry/ops.py`
- `tests/test_ops.py`
- `docs/OPERATIONS.md`
- `docs/SECURITY_CHECKLIST.md`
- `docs/PRODUCTION_READINESS.md`
- optional updates to `src/skillfoundry/__init__.py`
- optional updates to CLI for an `ops` or `health` command if small and useful

## Non-goals

Do not implement:

- full production queue;
- marketplace;
- multi-tenant permission platform;
- full auth system;
- external service dependency;
- Rust rewrite;
- database migration implementation.

Default tests must stay deterministic and offline.

## Required Behavior

Provide operations/hardening helpers such as:

```python
from skillfoundry import (
    SkillFoundryOps,
)

ops = SkillFoundryOps(runs_root, registry_path=...)
health = ops.health_check()
observability = ops.observability_report()
cleanup = ops.cleanup_artifacts(...)
```

Names may vary, but equivalent behavior must exist.

### Concurrency

Implement or test small-scale concurrency safety:

- multiple jobs can build in parallel under distinct job ids without cross-job artifact pollution;
- registry writes are protected by a file lock or equivalent atomic strategy;
- concurrent registry additions do not corrupt registry JSON.

If changing `LocalSkillRegistry` is necessary, keep changes narrow and preserve existing behavior.

### Retention/Cleanup

Artifact cleanup should:

- remove transient artifacts only when explicitly requested;
- preserve locked inputs, final reports, verifier results, QA reports, registry evidence, approved packages, and provenance-critical artifacts;
- produce a machine-readable cleanup report;
- support dry-run.

### Observability

Observability report should summarize:

- job count and statuses;
- final status distribution;
- failed jobs and failure classes;
- attempt counts;
- verifier pass/fail;
- QA pass/fail;
- registry approved/quarantined/rejected counts;
- feedback/versioning events where present;
- durations or duration availability;
- usage availability/unavailability reasons.

### Health/Readiness

Health/readiness should check:

- runs root exists and is writable;
- registry path is under expected control and parseable if present;
- no obvious workspace path violation;
- optional CLI/import readiness;
- current test command can be documented or invoked by tests where practical.

### Documents

`docs/OPERATIONS.md` should explain:

- how to run tests;
- how to run minimal API/UI;
- how to run health/readiness;
- how to run cleanup dry-run/apply;
- expected local filesystem layout.

`docs/SECURITY_CHECKLIST.md` should cover:

- path traversal;
- symlink/package download risks;
- worker boundary;
- CodexWorker boundary claims;
- registry/Verifier/QA gates;
- retention risks;
- live Codex opt-in.

`docs/PRODUCTION_READINESS.md` should include:

- internal beta readiness status;
- known residual risks;
- Python/Rust boundary assessment;
- JSON registry vs SQLite/database migration plan;
- performance profiling notes;
- what is still not production-grade.

## Required Tests

Automated tests must prove:

- Multi-job concurrent builds produce isolated workspaces and registered jobs.
- Concurrent registry additions do not corrupt registry JSON.
- Cleanup dry-run reports planned removals without deleting.
- Cleanup apply preserves provenance-critical artifacts and approved package.
- Observability report includes jobs/statuses/registry/QA/usage/failure summaries.
- Health/readiness check returns machine-readable pass/fail checks.
- Full `.venv/bin/python -m pytest -q` passes.

## Acceptance Criteria

- `src/skillfoundry/ops.py` exists.
- `tests/test_ops.py` exists.
- `docs/OPERATIONS.md` exists.
- `docs/SECURITY_CHECKLIST.md` exists.
- `docs/PRODUCTION_READINESS.md` exists.
- Full test suite passes:

```bash
.venv/bin/python -m pytest -q
```

- No heavy production infrastructure is introduced.
- Internal beta status and residual risks are explicit.

## Expected Final Response From Worker

List:

- files changed;
- operations API shape;
- hardening features implemented;
- docs added;
- tests implemented;
- tests run and exact result;
- deviations or blockers.

