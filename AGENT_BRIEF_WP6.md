# Agent Brief WP6: Registry MVP

## Mission

Implement SkillFoundry WP6: a local Registry MVP that only registers independently verified Skill packages and preserves hash/provenance evidence.

This is an implementation task for a 5.5-xhigh worker. The architect will review independently.

## Context

Repository: `/home/mansteinl/skillfoundry`

Already completed:

- WP1: schema, workspace, artifact manifest, path confinement.
- WP2: LangGraph skeleton.
- WP3: WorkerAdapter and FakeWorker.
- WP4: independent Verifier.
- WP5: ContextForge evidence boundary.

Read before editing:

- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `docs/WORK_PACKAGES.md`
- `docs/ACCEPTANCE_PLAN.md`
- `src/skillfoundry/schema.py`
- `src/skillfoundry/workspace.py`
- `src/skillfoundry/worker.py`
- `src/skillfoundry/verifier.py`
- `src/skillfoundry/context.py`

## Scope

WP6 owns:

- Local JSON or SQLite registry store.
- Registry writer.
- Registry query/list.
- Registry verifier gate.
- Package hash and artifact hash validation.
- Provenance preservation.
- Approved/rejected/quarantined status handling.
- Duplicate version policy.
- Registry entry verification after write.

Recommended files:

- `src/skillfoundry/registry.py`
- `tests/test_registry.py`
- update `src/skillfoundry/__init__.py`

## Non-goals

Do not implement:

- marketplace;
- multi-tenant permissions;
- API/UI;
- ContextForge internals;
- real Codex Worker integration;
- production package distribution;
- automatic registration of verifier-failed packages.

Do not accept builder self-report. Registry must trust only the independent `VerificationResult` plus hash/provenance checks.

## Required Registry Behavior

Implement a narrow API such as:

```python
LocalSkillRegistry(path).add_verified(workspace: JobWorkspace, ...) -> RegistryEntry
LocalSkillRegistry(path).get(skill_id, version) -> RegistryEntry
LocalSkillRegistry(path).list(status="approved") -> list[RegistryEntry]
LocalSkillRegistry(path).verify_entry(entry) -> bool or report
LocalSkillRegistry(path).quarantine(skill_id, version, reason) -> RegistryEntry
```

The exact names may differ, but tests must show equivalent behavior.

## Required Gates

Registration must fail when:

- `verifier/verification_result.json` is missing;
- `VerificationResult.passed` is false;
- `package_hash` is missing or does not match current package;
- `verification_result_hash` does not match current result file;
- `artifact_manifest_hash` does not match current manifest;
- `artifact_manifest.json` is missing;
- `worker_invocation_id` cannot be derived from the latest execution report or provenance;
- builder self-report says success but verifier failed;
- duplicate skill/version violates the chosen duplicate policy.

Approved entry must preserve:

- skill id;
- version;
- package path;
- package hash;
- build job id;
- worker invocation id;
- verification spec hash;
- verification result hash;
- artifact manifest hash;
- verifier version;
- approval status;
- review status;
- created_at;
- provenance;
- quarantine status.

## Acceptance Criteria

Automated tests must prove:

- verifier-passed package can be registered;
- verifier-failed package cannot be registered;
- builder self-report alone cannot register;
- tampered package after verification cannot register or fails registry verify;
- tampered verification result fails registry verify;
- missing artifact manifest fails registration;
- approved entry traces to build job, worker invocation, verification spec, verification result, and artifact manifest;
- quarantined entry is not returned by default approved list/reuse candidates;
- duplicate version policy is explicit and tested;
- RegistryEntry schema validates and round-trips.

Required command:

```bash
.venv/bin/python -m pytest -q
```

## Implementation Notes

- Prefer deterministic JSON store for MVP unless SQLite is much cleaner.
- Keep writes atomic enough for local tests: write temp file then replace.
- Use WP1 path and hash helpers.
- Use WP4 `VerificationResult` as the primary quality gate.
- Do not mutate the Skill package during registration.
- Do not modify `.metaloop/`, `.venv/`, caches, unrelated docs, or previous WP behavior unless integration requires tiny exports/config updates.

## Expected Final Response From Worker

List:

- files changed;
- registry API shape;
- gates implemented;
- tests run and exact result;
- any deviations.
