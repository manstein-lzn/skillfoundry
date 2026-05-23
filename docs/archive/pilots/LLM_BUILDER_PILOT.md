# LLM Builder Pilot

WP17 adds `LLMSkillBuilderWorker` as a controlled real-builder integration
pilot behind the existing `BuildWorker` / `WorkerAdapter` protocol.

This worker is not a production autonomous builder. It is a production-shaped
boundary for trying a SkillFoundry-owned LLM call after Front Desk freeze and
before the independent Verifier, QA, acceptance coverage, and Registry gates.

## Boundary

`LLMSkillBuilderWorker` reads only the frozen root inputs:

- `skill_spec.yaml`
- `acceptance_criteria.yaml`
- `verification_spec.yaml`
- `build_contract.yaml`
- `worker_input.md`
- the current attempt `attempts/<id>/input_manifest.json`

It does not read Front Desk conversation logs, raw prompts, raw provider
outputs, or non-frozen conversation artifacts. The builder prompt explicitly
instructs the model to use only frozen inputs, return JSON only, write only
under `package/`, avoid self-approval, and leave final approval to the
Verifier, QA Lab, Acceptance Coverage, and Registry.

The model response is a JSON object with schema version
`skillfoundry.llm_skill_builder_output.v1`. `skill_markdown` is always written
to `package/SKILL.md`. Optional files are accepted only under:

- `package/references/`
- `package/scripts/`
- `package/tests/`

Unsafe paths, absolute paths, parent traversal, package root escapes, duplicate
paths, invalid JSON, wrong schema versions, provider errors, and empty file
contents fail closed before the package is accepted for verification.

## ContextForge Owned Call

The LLM builder uses:

```python
SkillFoundryContextAdapter.call_owned_llm(...)
```

This is a SkillFoundry-owned LLM call recorded through ContextForge. It is
different from the `CodexWorker` pilot. `CodexWorker` invokes `codex exec` as
an external worker boundary and SkillFoundry does not control or replay Codex
internal prompt planning, tool loop, context compaction, cache, or cost.

`LLMSkillBuilderWorker` owns the builder prompt and output contract. ContextForge
records the owned call and replay evidence for that call; it does not make the
builder self-report into acceptance evidence.

## Default Tests

Default tests are deterministic and offline. They inject scripted fake model
clients into `LLMSkillBuilderWorker` and do not call live providers, network,
Codex, provider SDKs, shell runtimes, MCP servers, or external action systems.

The tests cover:

- public API exports;
- prompt input discipline and exclusion of raw Front Desk conversation content;
- successful JSON output writing `package/SKILL.md` plus optional package files;
- fail-closed behavior for invalid JSON, schema mismatch, unsafe paths, and
  provider errors;
- locked input confinement through `WorkerAdapter`;
- the full pilot path through `WorkerAdapter`, `Verifier`, `QALab`,
  `AcceptanceCriteriaPlanner`, `AcceptanceCoverageEvaluator`, and
  `LocalSkillRegistry.add_verified`.

## Opt-In Real Provider Use

Real provider use is opt-in by caller injection only. The worker accepts a
caller-provided `client`, `provider`, `model`, and `model_params`, then passes
them through `SkillFoundryContextAdapter.call_owned_llm(...)`.

SkillFoundry does not configure live credentials, import provider SDKs, or ship
a default live provider client in WP17. Callers that want a real pilot must
construct and inject a compatible client explicitly.

## Final Gates

Builder completion is not acceptance. A successful `LLMSkillBuilderWorker`
attempt only means the worker produced a package candidate and the attempt is
ready for verifier inspection.

The package can enter the registry only after these independent gates pass:

- `Verifier` checks locked inputs, package shape, paths, declared references,
  hashes, execution report evidence, and deterministic smoke policy.
- `QALab` checks verifier status, fixture coverage, IO contract coverage,
  workflow actionability, safety actionability, and script safety.
- `AcceptanceCriteriaPlanner` and `AcceptanceCoverageEvaluator` map frozen
  acceptance criteria to deterministic evidence and require must-criteria to
  pass or be explicitly manual-only.
- `LocalSkillRegistry.add_verified` re-reads verifier, worker, manifest, and
  acceptance coverage provenance before approving a registry entry.

The builder cannot approve itself, and its summary or warnings are not
acceptance evidence.
