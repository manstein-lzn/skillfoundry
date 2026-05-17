# AGENT BRIEF WP17: Real Builder Integration Pilot

You are implementing WP17 in `/home/mansteinl/skillfoundry`.

You are not alone in the codebase. Do not revert or overwrite other changes. Keep the patch narrowly scoped.

## Goal

Add a controlled real-builder integration pilot after Front Desk freeze and acceptance coverage gates.

Use this route for WP17:

```text
frozen spec inputs
  -> WorkerAdapter
  -> LLMSkillBuilderWorker (SkillFoundry-owned LLM call through ContextForge)
  -> package/SKILL.md
  -> Verifier
  -> QALab
  -> AcceptanceCoveragePlanner/Evaluator
  -> Registry
```

This is not a production-grade autonomous builder. It is a production-shaped pilot boundary with deterministic tests and opt-in real provider ability through injected clients only.

## Required Deliverables

1. LLM builder worker.
   - Preferred new file: `src/skillfoundry/llm_builder.py`.
   - Suggested public API:
     - `LLMSkillBuilderWorker`
     - `LLMSkillBuilderResult` only if useful
     - constants:
       - `LLM_SKILL_BUILDER_AGENT_ROLE`
       - `LLM_SKILL_BUILDER_OUTPUT_SCHEMA_VERSION`
       - `LLM_SKILL_BUILDER_STATUS_SUCCEEDED`
       - `LLM_SKILL_BUILDER_STATUS_FAIL_CLOSED`
   - It must implement the existing `BuildWorker` protocol:
     - `worker_type`
     - `run(context: WorkerRunContext) -> WorkerExecutionOutcome`

2. Builder input discipline.
   - Read only frozen root inputs:
     - `skill_spec.yaml`
     - `acceptance_criteria.yaml`
     - `verification_spec.yaml`
     - `build_contract.yaml`
     - `worker_input.md`
     - current attempt input manifest
   - Do not read `frontdesk/conversation.jsonl`, raw prompts, raw model output, or any non-frozen conversation artifact.
   - The prompt must explicitly say:
     - use only frozen inputs;
     - write only under `package/`;
     - do not self-approve;
     - Verifier/QA/Registry are final gates.

3. ContextForge owned call.
   - Use `SkillFoundryContextAdapter.call_owned_llm(...)`.
   - Default tests must inject a scripted fake client.
   - Do not call real providers in tests.
   - On provider/schema failure, return fail-closed `WorkerExecutionOutcome`.

4. Output contract.
   - Require model output to be JSON, no markdown wrapper.
   - Suggested JSON:
     ```json
     {
       "schema_version": "skillfoundry.llm_skill_builder_output.v1",
       "skill_markdown": "...",
       "reference_files": [
         {"path": "references/example.md", "content": "..."}
       ],
       "script_files": [
         {"path": "scripts/helper.py", "content": "..."}
       ],
       "test_files": [
         {"path": "tests/fixture.md", "content": "..."}
       ],
       "summary": "...",
       "warnings": []
     }
     ```
   - Always write `package/SKILL.md` from `skill_markdown`.
   - Optional files must stay under:
     - `package/references/`
     - `package/scripts/`
     - `package/tests/`
   - Reject unsafe paths, absolute paths, `..`, package root escapes, and empty content where unsafe.

5. End-to-end pilot test.
   - Add `tests/test_llm_builder.py`.
   - Cover at least:
     - API export.
     - builder prompt contains frozen refs and excludes `frontdesk/conversation.jsonl`.
     - scripted LLM output writes `package/SKILL.md` and optional package files.
     - invalid JSON/schema/path fails closed and does not register as accepted.
     - builder cannot modify locked inputs through WorkerAdapter.
     - full pipeline with scripted builder:
       `WorkerAdapter(LLMSkillBuilderWorker(...)) -> Verifier -> QALab -> AcceptanceCoveragePlanner/Evaluator -> LocalSkillRegistry.add_verified`
       passes for a good frozen spec and stores acceptance coverage provenance.

6. Documentation.
   - Add or update a small doc, preferred `docs/LLM_BUILDER_PILOT.md`.
   - Explain:
     - owned LLM builder vs Codex external worker boundary;
     - default tests are fake/scripted;
     - real provider use is opt-in by caller-injected client/config;
     - verifier/QA/registry remain final gates.

7. Exports.
   - Export new public API from `src/skillfoundry/__init__.py`.

## Non-Goals

Do not implement:

- Live OpenAI credentials or provider-specific SDK setup.
- Live CodexAgentThreadWorker.
- New shell/MCP/action runtime.
- UI/API changes.
- Registry evaluator logic.
- Full semantic test generation.
- Direct use of raw Front Desk conversation.

## Hard Constraints

- Default tests deterministic/offline.
- No network calls.
- No live Codex calls.
- No direct provider SDK dependency.
- Do not claim ContextForge controls Codex internals.
- Builder self-report is not acceptance evidence.
- Only Verifier/QA/Acceptance/Registry gates can approve.
- Builder must be usable through `WorkerAdapter`.

## Acceptance Commands

Run:

```bash
.venv/bin/python -m pytest tests/test_llm_builder.py -q
.venv/bin/python -m pytest tests/test_worker.py tests/test_codex_worker.py tests/test_llm_builder.py tests/test_acceptance_coverage.py -q
.venv/bin/python -m pytest -q
git diff --check
```

## Final Response Required From Worker

Report:

- files changed;
- public API added;
- how builder stays behind WorkerAdapter and final gates;
- test commands run and results;
- remaining limitations.

