# Agent Brief WP4: Independent Verifier

## Mission

Implement SkillFoundry WP4: an independent verifier that evaluates worker-produced Skill packages and writes a machine-readable `verification_result.json`.

This is an implementation task for a 5.5-xhigh worker. The architect will review independently.

## Context

Repository: `/home/mansteinl/skillfoundry`

Already completed:

- WP1: schema, workspace, artifact manifest, path confinement.
- WP2: LangGraph skeleton with refs-only state.
- WP3: WorkerAdapter and deterministic FakeWorker fixtures.

Read before editing:

- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `docs/WORK_PACKAGES.md`
- `docs/ACCEPTANCE_PLAN.md`
- `src/skillfoundry/schema.py`
- `src/skillfoundry/workspace.py`
- `src/skillfoundry/security.py`
- `src/skillfoundry/worker.py`

## Scope

WP4 owns:

- Independent verifier API.
- Static package checker.
- `SKILL.md` required-section checker.
- Trigger / non-trigger / required input / expected output fixture checks.
- Reference/script path safety checks.
- Package path confinement checks.
- Artifact manifest presence and locked-input hash checks.
- Package hash calculation.
- Worker execution-report gate.
- Sandbox smoke placeholder/checker.
- Optional LLM judge signal representation, but not as a primary gate.
- Machine-readable `verifier/verification_result.json`.
- Human-readable static/smoke summary files if useful.

Recommended files:

- `src/skillfoundry/verifier.py`
- `tests/test_verifier.py`
- update `src/skillfoundry/__init__.py`

## Non-goals

Do not implement:

- Registry write/approval workflow;
- ContextForge integration;
- real Codex Worker integration;
- production security sandbox;
- API/UI;
- real LLM judge/model calls;
- shell/MCP/action runtime.

Do not trust builder self-report. A worker `ExecutionReport` with success is evidence input only; it is not a pass condition by itself.

## Required Package Contract

For WP4, define a conservative minimal `SKILL.md` contract and test it. Suggested required headings:

```markdown
# <title>
## Overview
## When To Use
## When Not To Use
## Inputs
## Outputs
## Workflow
## Safety
```

The exact required headings may be adjusted, but tests must prove missing required sections fail.

## Verifier API Requirements

Implement a narrow API such as:

```python
Verifier().verify(workspace: JobWorkspace) -> VerificationResult
```

The verifier must:

- read `artifact_manifest.json`;
- call WP1 locked input checks;
- inspect `package/`;
- inspect latest or specified attempt execution report;
- calculate package hash;
- write `verifier/verification_result.json`;
- return a `VerificationResult` schema object;
- include evidence refs and check records with pass/fail reasons.

If there is no valid execution report, verification must fail.

## Required Failures

Automated tests must prove these fail:

- missing `package/SKILL.md`;
- missing required `SKILL.md` section;
- path traversal or unsafe path under package references/scripts;
- artifact manifest missing or locked input mismatch;
- worker self-report says success but package is structurally invalid;
- LLM judge signal says pass but static check fails;
- sandbox smoke failure;
- hash mismatch fixture, if the implementation stores expected hashes in a verifier input or static report.

## Required Pass

Automated tests must prove:

- a valid package produced by FakeWorker or a fixture package passes all primary gates;
- `VerificationResult` validates through the WP1 schema class;
- `verifier/verification_result.json` is written and round-trips;
- verification is deterministic for the same workspace input, except timestamps/result ids if explicitly documented.

## Acceptance Criteria

- `src/skillfoundry/verifier.py` exists.
- `tests/test_verifier.py` exists.
- `__init__.py` exports the main WP4 API.
- Missing required section fails.
- Path traversal fails.
- Hash mismatch or locked input mismatch fails.
- Missing artifact manifest fails.
- Builder self-report cannot pass invalid package.
- LLM judge cannot override static failure.
- Sandbox smoke fail causes verification fail.
- Verifier result schema validates.
- Fixture pass/fail are covered by tests.

Required command:

```bash
.venv/bin/python -m pytest -q
```

## Implementation Notes

- Keep this deterministic and local.
- Do not run untrusted scripts for real. A sandbox smoke check can be a conservative policy/file check or deterministic fixture switch.
- Use WP1 path confinement helpers.
- Write clear check records: `name`, `passed`, `severity`, `message`, `evidence_ref`.
- Treat unknown/uncertain safety as fail-closed.
- Do not modify locked inputs.
- Do not change `.metaloop/`, `.venv/`, caches, unrelated docs, or previous WP behavior unless integration requires a tiny export update.

## Expected Final Response From Worker

List:

- files changed;
- verifier API shape;
- checks implemented;
- tests run and exact result;
- any deviations.
