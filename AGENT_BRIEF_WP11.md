# Agent Brief WP11: Feedback + Versioning

## Mission

Implement SkillFoundry WP11: feedback capture and version governance for verified Skill assets.

This is an implementation task for a 5.5-xhigh worker. The architect will review independently.

## Context

Repository: `/home/mansteinl/skillfoundry`

Already completed:

- WP6 Registry: approved/rejected/quarantined entries with provenance.
- WP7 Offline E2E: deterministic build/verify/register/final report.
- WP9 Minimal API/UI: internal entry and approved package download.
- WP10 QA Lab: deterministic quality report and failure taxonomy.

WP11 turns one-shot Skill generation into maintainable assets. Feedback must create traceable repair/version work. It must not directly mutate approved packages.

## Scope

WP11 owns:

- Feedback record schema and JSON persistence.
- Failed usage case capture.
- Repair/version job planning from feedback.
- Version upgrade helper that requires Verifier pass, QA Lab pass, and Registry gate.
- Quarantine/rollback event helpers.
- Version change report.
- Tests proving gates and provenance.

Recommended files:

- `src/skillfoundry/feedback.py`
- `tests/test_feedback.py`
- optional updates to `src/skillfoundry/__init__.py`
- optional docs `docs/FEEDBACK_VERSIONING.md`

## Non-goals

Do not implement:

- production dashboard;
- production queue;
- marketplace;
- multi-tenant review platform;
- direct package mutation;
- bypass of Verifier, QA Lab, or Registry gates.

## Required Behavior

Provide a small API shape such as:

```python
from skillfoundry import (
    FeedbackRecord,
    SkillVersionManager,
)

feedback = FeedbackRecord(...)
manager = SkillVersionManager(registry_path)
plan = manager.plan_repair_from_feedback(feedback, source_entry)
entry = manager.register_repaired_version(workspace, feedback, source_entry, version="0.2.0")
```

Names may vary, but behavior must exist.

### Feedback Record

Machine-readable feedback must include:

- schema version;
- feedback id;
- skill id;
- source version;
- source build job id;
- reporter or channel;
- rating or severity;
- summary;
- failed usage case;
- expected behavior;
- actual behavior;
- evidence refs;
- created_at.

It must write/read JSON.

### Repair/Version Plan

Planning from feedback should produce a machine-readable repair plan that references:

- feedback record;
- source registry entry;
- source package hash;
- suggested new version;
- repair goal;
- acceptance notes;
- target repair job id;
- gate requirements: Verifier, QA Lab, Registry.

The plan should be durable, for example under:

```text
runs/<repair_job_id>/feedback_repair_plan.json
```

### Register Repaired Version

Registering a repaired version must:

- require existing `verifier/verification_result.json` to pass;
- require `qa/quality_report.json` to pass;
- call `LocalSkillRegistry.add_verified`;
- use a new version distinct from the source version;
- preserve provenance linking:
  - source skill id/version;
  - source package hash;
  - feedback record;
  - repair plan;
  - repair job id;
  - verification result;
  - QA report;
  - new registry entry.

If QA fails, registration must fail even if Verifier passes.

### Quarantine

Must support quarantining an existing version using `LocalSkillRegistry.quarantine` or a wrapper. Quarantined entries must not appear in default `reuse_candidates()`.

### Rollback

Must support recording a rollback event that marks a previous approved version as preferred/restored without modifying package files. A lightweight event/report is enough for WP11.

### Version Change Report

Write a report summarizing feedback, plan, old/new version, quarantine/rollback state, and gate refs.

## Required Tests

Automated tests must prove:

- FeedbackRecord JSON round-trip.
- Feedback creates durable repair/version plan.
- Repaired version registration succeeds only after Verifier and QA Lab pass.
- Repaired version provenance links source version, feedback record, repair job, verifier result, QA report, and registry entry.
- QA-failed repaired version cannot register even if Verifier passes.
- Quarantine excludes old version from default reuse candidates.
- Rollback event is recorded without modifying package content.
- Full `.venv/bin/python -m pytest -q` passes.

## Acceptance Criteria

- `src/skillfoundry/feedback.py` exists.
- `tests/test_feedback.py` exists.
- Full test suite passes:

```bash
.venv/bin/python -m pytest -q
```

- Feedback cannot directly modify approved packages.
- New versions must pass Verifier, QA Lab, and Registry gates.
- Provenance is explicit.

## Expected Final Response From Worker

List:

- files changed;
- feedback/versioning API shape;
- reports/artifacts written;
- tests implemented;
- tests run and exact result;
- deviations or blockers.

