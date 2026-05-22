# SkillFoundry Security Checklist

> Historical note: this checklist was written for the v0/WP12 internal beta
> boundary. Its path, registry, and Codex boundary checks remain useful, but
> current v2 trust-boundary policy is defined in
> `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`.

WP12 hardening is scoped to small-scale internal beta use. This checklist
documents the current security posture and the items reviewers should verify
before running internal trials.

## Path Traversal

- Job ids must be one safe path segment matching
  `^[A-Za-z0-9][A-Za-z0-9_.-]*$`.
- Workspace path resolution uses `validate_relative_path`,
  `resolve_under_root`, and `assert_under_root`.
- Absolute paths, parent traversal, dot segments, doubled separators, Windows
  drive paths, and symlink components are rejected by the security boundary.
- The minimal API validates job ids and package download paths before reading
  or archiving files.
- The Verifier checks locked input integrity, artifact manifest hashes, package
  path confinement, and declared package paths.

Review action:

```bash
.venv/bin/python -m pytest tests/test_workspace.py tests/test_api.py tests/test_verifier.py -q
```

## Symlink and Package Download Risks

- Package download is allowed only for a registered, approved, non-quarantined
  job.
- Download archives include only files under `package/`.
- Symlinks inside package trees are rejected for download.
- The registry entry is reverified before package download. Tampered package or
  verifier evidence prevents approval reuse.
- Cleanup skips symlinks rather than following them.

Residual risk:

- Zip downloads are intended for internal review. There is no signed package
  distribution, malware scanner, or external trust root in WP12.

## Worker Boundary

- WorkerAdapter writes only through a confined `WorkerRunContext` for local
  workers.
- The allowed write roots are `package/` and the current attempt directory.
- Worker self-report is never approval evidence.
- Worker attempts produce input manifest, execution report, transcript, and
  output diff boundary artifacts.
- Failed, timed-out, missing-output, path-escape, and rejected worker outcomes
  do not register packages.

Review action:

```bash
.venv/bin/python -m pytest tests/test_worker.py tests/test_codex_worker.py -q
```

## CodexWorker Boundary Claims

- CodexWorker is an optional pilot boundary, not a claim of controlling Codex
  internals.
- SkillFoundry records Codex command, prompt hash, stdout/stderr, timeout,
  required package outputs, and disallowed workspace changes as boundary
  evidence.
- SkillFoundry does not replay Codex internal prompt planning, tool loop,
  context compaction, cache, or provider usage.
- Live Codex invocation requires explicit opt-in through
  `SKILLFOUNDRY_RUN_CODEX_PILOT=1`.
- Default tests do not invoke live Codex or network providers.

Residual risk:

- Codex CLI behavior is outside SkillFoundry's implementation boundary. Keep
  the pilot disabled for deterministic CI and enable it only in controlled
  local trials.

## Registry, Verifier, and QA Gates

- `LocalSkillRegistry.add_verified` requires a verifier-passed result,
  hash-matching package, verification spec hash, artifact manifest hash,
  execution report, and worker input manifest.
- Registry writes are serialized by a sidecar file lock and written through
  per-process temp files with atomic replace.
- Duplicate version policy remains explicit: reject by default, idempotent only
  when configured.
- QA Lab is an additional deterministic quality layer. It cannot override a
  failed Verifier result.
- Feedback-driven repaired versions must pass Verifier, QA Lab, and Registry
  gates before registration.

Review action:

```bash
.venv/bin/python -m pytest tests/test_registry.py tests/test_qa.py tests/test_feedback.py -q
```

## Retention and Cleanup Risks

- Cleanup defaults to dry-run.
- Cleanup removes only known transient files and cache directories.
- Cleanup preserves:
  - locked inputs;
  - artifact manifests;
  - final reports;
  - verifier results;
  - QA reports;
  - worker attempt input manifests, execution reports, transcripts, diffs, and
    archived verification results;
  - registry evidence;
  - approved package roots;
  - feedback records, repair plans, version-change reports, and rollback events.
- Cleanup does not prune old jobs by age and does not compact provenance.

Residual risk:

- Disk growth is still an operator responsibility. WP12 provides safe transient
  cleanup, not lifecycle management or long-term archival.

## Live Codex Opt-In

Before enabling live Codex pilot runs:

- Confirm `SKILLFOUNDRY_RUN_CODEX_PILOT=1` is intentionally set only for the
  trial shell.
- Use a disposable workspace or clean git branch.
- Keep registry and runs roots local and under operator control.
- Review `docs/CODEX_WORKER_PILOT.md`.
- Run health checks before and after live trials.
- Do not publish packages externally without manual review.

## Internal Beta Readiness Check

Run:

```bash
.venv/bin/python -m skillfoundry.cli ops --runs-root runs --registry runs/registry.json health
.venv/bin/python -m skillfoundry.cli ops --runs-root runs --registry runs/registry.json observability
.venv/bin/python -m pytest -q
```

The beta is ready only when health is `ready: true`, the full test suite passes,
and residual risks are accepted for internal users.
