# Agent Brief WP10: QA Lab Expansion

## Mission

Implement SkillFoundry WP10: a deterministic QA Lab layer that adds scenario-level quality evidence on top of the existing independent Verifier.

This is an implementation task for a 5.5-xhigh worker. The architect will review independently.

## Context

Repository: `/home/mansteinl/skillfoundry`

Already completed:

- WP4 Verifier: static/path/hash/smoke quality gate.
- WP6 Registry: accepts only verifier-passed packages.
- WP7 Offline E2E: final reports and repair loop.
- WP8 CodexWorker Pilot: optional external worker boundary.
- WP9 Minimal API/UI: internal entry and approved package download gate.

WP10 must improve quality evidence without weakening the existing trust model.

## Scope

WP10 owns:

- A QA Lab evaluator module.
- Machine-readable quality report.
- Trigger/non-trigger fixture checks.
- Input/output contract checks.
- Script smoke checks.
- Optional auxiliary judge signal.
- Failure taxonomy that can drive repair planning.
- Tests for good/bad packages and judge override boundaries.

Recommended files:

- `src/skillfoundry/qa.py`
- `tests/test_qa.py`
- optional updates to `src/skillfoundry/__init__.py`
- optional docs `docs/QA_LAB.md`

## Non-goals

Do not implement:

- WP11 feedback/versioning;
- production benchmark infrastructure;
- live provider calls in default tests;
- a full sandbox product;
- registry approval bypass;
- replacement of the existing Verifier.

LLM judge or judge-like signal is auxiliary evidence only. It cannot approve a Skill when deterministic hard checks fail.

## Required Behavior

QA Lab should be usable as:

```python
from skillfoundry import QALab

result = QALab().evaluate(workspace)
```

or equivalent.

It should write a machine-readable report, for example:

```text
runs/<job_id>/qa/quality_report.json
```

The report should include:

- schema version;
- job id;
- package hash;
- verifier result ref/hash when present;
- overall `passed`;
- numeric quality score or equivalent;
- checks with names, pass/fail, severity, evidence refs, and failure class;
- trigger fixture results;
- non-trigger fixture results;
- input/output contract results;
- script smoke results;
- optional judge signal and judge evidence ref;
- failure taxonomy / repair classes.

Hard checks must include deterministic fixture/contract checks. Suggested checks:

- `verifier_passed`: QA requires an existing verifier-passed result for full pass.
- `trigger_fixture_coverage`: at least one trigger fixture from SkillSpec or QA fixture spec.
- `non_trigger_fixture_coverage`: at least one non-trigger fixture.
- `io_contract_coverage`: required inputs and expected outputs are represented.
- `workflow_actionability`: `Workflow` section contains actionable steps.
- `safety_actionability`: `Safety` section contains concrete constraints.
- `script_smoke`: declared local scripts exist, are confined to package/scripts, and do not contain obviously unsafe shell/process/network patterns.

Optional judge signal:

- May be represented by an injected deterministic judge object or static signal.
- Must be recorded as auxiliary evidence.
- Must not turn failed hard checks into pass.
- If judge prompt evidence is produced, use existing ContextForge adapter or a compact governed evidence object; do not dump raw large logs into prompt/report.

## Required Tests

Automated tests must prove:

- A good verifier-passed package passes QA Lab and writes `qa/quality_report.json`.
- A structurally valid but behaviorally weak package fails deterministic fixture/contract checks.
- Trigger and non-trigger fixture results are present.
- Input/output contract results are present.
- Script smoke passes for safe scripts and fails for unsafe script content.
- Optional positive judge signal cannot override failed hard checks.
- Failure taxonomy includes repair-driving classes for failed checks.
- Existing Verifier and Registry behavior still passes full test suite.

## Acceptance Criteria

- `src/skillfoundry/qa.py` exists.
- `tests/test_qa.py` exists.
- Full test suite passes:

```bash
.venv/bin/python -m pytest -q
```

- QA Lab writes a durable quality report.
- QA Lab does not replace Verifier or Registry gate.
- No live provider call is required by default tests.

## Expected Final Response From Worker

List:

- files changed;
- QA Lab API shape;
- quality report fields;
- tests implemented;
- tests run and exact result;
- deviations or blockers.

