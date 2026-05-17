# AGENT BRIEF WP16: Acceptance Criteria to QA/Verifier Coverage Bridge

You are implementing WP16 in `/home/mansteinl/skillfoundry`.

You are not alone in the codebase. Do not revert or overwrite other changes. Keep the patch narrowly scoped.

## Goal

Convert frozen Front Desk acceptance criteria into deterministic QA/Verifier coverage evidence:

```text
acceptance_criteria.yaml
  -> acceptance_coverage_plan.json
  -> QA/Verifier/package evidence
  -> acceptance_coverage_result.json
  -> QA/final report summary
  -> Registry consumes pass/hash/provenance only
```

WP16 must make this statement true:

```text
An approved registry entry is impossible when a must acceptance criterion is uncovered,
unless that criterion is explicitly manual-only and routed to human authority.
```

## Required Deliverables

1. Acceptance coverage module.
   - Preferred new file: `src/skillfoundry/acceptance.py`.
   - Suggested public API:
     - `AcceptanceCriteriaPlanner`
     - `AcceptanceCoveragePlan`
     - `AcceptanceCoveragePlanItem`
     - `AcceptanceCoverageEvaluator`
     - `AcceptanceCoverageResult`
     - `AcceptanceCoverageResultItem`
   - Suggested constants:
     - `ACCEPTANCE_COVERAGE_PLAN_VERSION`
     - `ACCEPTANCE_COVERAGE_RESULT_VERSION`
     - `ACCEPTANCE_COVERAGE_PLAN_REF = "qa/acceptance_coverage_plan.json"`
     - `ACCEPTANCE_COVERAGE_RESULT_REF = "qa/acceptance_coverage_result.json"`

2. Planning behavior.
   - Input: root `acceptance_criteria.yaml` written by FrontDeskFreezeGate.
   - Output: `qa/acceptance_coverage_plan.json`.
   - Every acceptance criterion must map to one of:
     - verifier check id;
     - fixture ref;
     - required evidence file/command ref;
     - QA report check;
     - manual authority;
     - explicit uncovered reason.
   - Build/freeze phase may use `planned`; plan is not approval evidence.
   - LLM-only must criteria must not be considered deterministic coverage.

3. Evaluation behavior.
   - Input: coverage plan, QA report, verifier result, package files.
   - Output: `qa/acceptance_coverage_result.json`.
   - Result statuses must not use `planned`.
   - Use statuses such as:
     - `covered/pass`
     - `covered/fail`
     - `manual_only`
     - `uncovered`
   - Overall `passed=true` only if:
     - all must criteria are `covered/pass`, or
     - all non-covered must criteria are explicitly `manual_only` with manual authority metadata.
   - If a must criterion is `uncovered`, `covered/fail`, or LLM-only without deterministic evidence, overall `passed=false`.
   - Optional/should/could failures may reduce coverage metrics but should not necessarily block pass unless existing policy says they must.

4. QA/final report integration.
   - `QALab.evaluate(...)` should include acceptance coverage summary when `qa/acceptance_coverage_result.json` exists.
   - Do not make LLM judge override this.
   - If a coverage result is missing, the existing QA tests should continue to pass.

5. Registry gate integration.
   - Registry must not calculate coverage itself.
   - If root `acceptance_criteria.yaml` exists, registry approval must require:
     - `qa/acceptance_coverage_result.json` exists;
     - result has `passed=true`;
     - result hash is stored in registry provenance;
     - verification of registry entry re-checks that hash and `passed=true`.
   - If `acceptance_criteria.yaml` does not exist, keep existing registry behavior so old tests stay valid.
   - Do not inspect package text in Registry for coverage. It may parse the coverage result only to consume `passed` and identify the result id/hash/provenance.

6. Tests.
   - Add `tests/test_acceptance_coverage.py`.
   - Cover at least:
     - planner maps every criterion to a plan item.
     - good skill + QA/verifier evidence -> must criteria pass.
     - bad skill -> must criterion fails.
     - uncovered must criterion -> overall fail.
     - manual-only must criterion -> not auto-approved unless manual authority metadata is present.
     - LLM-only must criterion cannot be registry-approved.
     - QALab report includes acceptance coverage summary when result exists.
     - Registry rejects when coverage result is missing but root acceptance criteria exists.
     - Registry rejects when coverage result `passed=false`.
     - Registry accepts when coverage result `passed=true` and stores hash/provenance.
     - Registry verify fails after coverage result tampering.

7. Exports.
   - Export new public API from `src/skillfoundry/__init__.py`.

## Non-Goals

Do not implement:

- WP17 real builder.
- Live provider/network/Codex calls.
- LangGraph changes.
- UI/API changes.
- A new marketplace or advanced registry.
- LLM judge as acceptance authority.
- Full semantic test generation.

## Hard Constraints

- Default tests must remain deterministic/offline.
- No network calls.
- No real provider calls.
- Registry must not become an evaluator.
- Registry can only consume coverage result `passed`, hash, result id/provenance refs.
- QA/Verifier/acceptance module owns coverage computation.
- Do not claim ContextForge controls Codex internals.

## Acceptance Commands

Run:

```bash
.venv/bin/python -m pytest tests/test_acceptance_coverage.py -q
.venv/bin/python -m pytest tests/test_qa.py tests/test_registry.py tests/test_acceptance_coverage.py -q
.venv/bin/python -m pytest -q
git diff --check
```

## Final Response Required From Worker

Report:

- files changed;
- public API added;
- how Registry remains a consumer rather than evaluator;
- test commands run and results;
- remaining limitations.

