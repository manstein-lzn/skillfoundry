# SkillFoundry Production Readiness

> Historical note: this document records the old WP12 small-scale internal beta
> readiness boundary. It does not describe current v2 production readiness.
> Current v2 readiness levels, blockers, and migration gates are defined in
> `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`.

WP12 reaches small-scale internal beta readiness. It does not make
SkillFoundry a full production platform.

## Status

Current status: ready for controlled internal beta after the full test suite and
local health check pass.

What is hardened:

- historical local concurrent offline build fixtures existed in WP12; current
  ops no longer exposes a concurrent offline build helper;
- registry read-modify-write mutations are serialized with a local file lock
  and atomic replace;
- transient cleanup supports dry-run and explicit apply;
- cleanup preserves provenance-critical artifacts and approved packages;
- health/readiness checks are machine-readable;
- observability reports summarize jobs, gates, registry, failures, feedback
  events, durations, and usage availability;
- operator docs and security checklist exist.

What remains intentionally out of scope:

- production queue or scheduler;
- marketplace;
- multi-tenant permissions;
- full auth platform;
- external service dependency;
- database migration implementation;
- Rust rewrite;
- signed external distribution.

## Known Residual Risks

- The minimal API/UI is for trusted internal networks only. It has no auth,
  rate limiting, CSRF protection, tenant model, or audit login trail.
- The registry is a local JSON file. File locking protects small-scale local
  concurrent writes, but it is not a distributed consistency mechanism.
- Cleanup is conservative and transient-only. It does not implement retention
  windows, archival, quota enforcement, or per-project lifecycle policy.
- Observability is derived from local artifacts. There is no metrics daemon,
  tracing backend, alerting, or long-term log store.
- Provider usage/cost is normally unavailable for offline workers and remains
  unavailable at the Codex CLI pilot boundary unless a future worker interface
  provides reliable counters.
- Live Codex pilot behavior depends on an external CLI and must stay opt-in.
- Package review remains an internal human/process responsibility before any
  external use.

## Python and Rust Boundary Assessment

Keep Python as the main implementation for the internal beta.

Python is adequate for:

- schema validation and deterministic serialization;
- local workspace orchestration;
- file hash gates;
- Verifier static checks;
- QA Lab deterministic checks;
- small-scale concurrent local jobs;
- operator reports.

Potential future Rust candidates:

- high-volume package tree hashing;
- path normalization and symlink policy enforcement;
- archive inspection and creation for untrusted packages;
- verifier sandbox primitives if package volume or threat model increases.

Do not migrate to Rust in WP12. The current bottleneck is product and evidence
discipline, not CPU-bound execution.

## JSON Registry vs Database Migration

Current decision: keep `LocalSkillRegistry` as a JSON file for internal beta.

Why JSON is acceptable now:

- entries are small;
- internal beta write volume is low;
- the registry is human-inspectable;
- tests can remain deterministic and offline;
- WP12 adds local write locking and atomic replace;
- registry verification rechecks package and provenance hashes.

Migration trigger points:

- concurrent writers across machines or containers;
- registry entries growing beyond easy human review;
- need for query performance, pagination, or history queries;
- need for transactional updates across registry, feedback, and audit events;
- formal backup/restore or migration requirements.

Likely migration path:

1. Keep the RegistryEntry schema as the contract.
2. Add an adapter interface around the registry store.
3. Implement SQLite first for local transactional durability.
4. Add import/export between JSON and SQLite.
5. Run both implementations against the same registry behavior tests.
6. Only then consider a networked database if deployment requires it.

No database migration is implemented in WP12.

## Performance Notes

Expected internal-beta profile:

- job counts are small;
- package directories are small;
- registry writes are infrequent;
- verification and QA are local deterministic checks;
- concurrency is bounded by local threads and filesystem behavior.

Current performance-sensitive operations:

- hashing package trees;
- reading all job directories for observability;
- registry verification for package download;
- QA Lab markdown and script checks.

Current mitigation:

- deterministic local tests keep regressions visible;
- observability reports expose duration availability and total attempt duration;
- registry operations sort entries for stable output;
- cleanup avoids broad deletion and follows an allowlist of transient artifacts.

Future profiling plan:

- add a fixture with dozens of jobs and larger package trees;
- record wall time for build, verify, QA, registry add, observability, and
  cleanup;
- track package tree hash time separately;
- decide whether SQLite indexing or Rust hashing is justified from measured
  data.

## Operational Gates for Internal Beta

Before a trial:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m skillfoundry.cli ops --runs-root runs --registry runs/registry.json health
.venv/bin/python -m skillfoundry.cli ops --runs-root runs --registry runs/registry.json cleanup
```

During a trial:

- keep runs and registry under a local controlled directory;
- keep live Codex pilot disabled unless the trial explicitly requires it;
- review failed jobs through `final_report.json`, `verifier/`, `qa/`, and
  attempt artifacts;
- use `observability` after batches to inspect status and failure distribution.

After a trial:

```bash
.venv/bin/python -m skillfoundry.cli ops --runs-root runs --registry runs/registry.json observability
.venv/bin/python -m skillfoundry.cli ops --runs-root runs --registry runs/registry.json cleanup --apply
```

Only apply cleanup after reviewing the dry-run output.

## Not Production Grade Yet

SkillFoundry still lacks:

- authentication and authorization;
- tenant isolation;
- production deployment manifests;
- queue semantics and backpressure;
- distributed locks;
- durable database transactions;
- external package signing;
- formal incident response;
- secrets management;
- audit log retention policy;
- monitoring and alerting;
- user-facing SLAs.

WP12 makes the existing WP7-WP11 loop safer and more observable for internal
beta. It is the hardening layer before deciding whether the next step is
continued Python implementation, selective Rust kernels, or a registry database
migration.
