# AGENT BRIEF WP1: Workspace + Schema

You are implementing WP1 for SkillFoundry. You are not alone in this
repository: do not revert edits made by others, and keep your changes scoped to
the workspace/schema foundation described here.

## Role

Implement the first code package for SkillFoundry:

- Python project scaffold;
- core schema objects;
- JSON/YAML serialization round-trip;
- job workspace initialization;
- artifact hashing and manifests;
- locked input tamper checks;
- path confinement checks including absolute paths, `..`, and symlink escape.

Do not implement LangGraph, WorkerAdapter, Verifier, Registry, ContextForge
integration, API, UI, or real Codex integration in this work package.

## Required Inputs

Read these files first:

- `docs/ARCHITECTURE.md`
- `docs/WORK_PACKAGES.md`
- `docs/ACCEPTANCE_PLAN.md`
- `docs/ROADMAP.md`
- `WHITEPAPER.md`

## Required Scope

Create a conservative Python package with tests.

Likely files:

- `pyproject.toml`
- `src/skillfoundry/__init__.py`
- `src/skillfoundry/schema.py`
- `src/skillfoundry/workspace.py`
- `src/skillfoundry/security.py` or equivalent path utilities
- `tests/test_schema.py`
- `tests/test_workspace.py`
- optional `examples/requirements/pytest_repair.md` if useful as fixture

## Schema Objects

Implement at least:

- `SkillSpec`
- `BuildContract`
- `VerificationSpec`
- `WorkerInvocation`
- `ExecutionReport`
- `VerificationResult`
- `RepairAttempt`
- `ArtifactRecord`
- `ArtifactManifest`
- `RegistryEntry`
- `ApprovalRecord`

Requirements:

- schema version fields where appropriate;
- explicit required fields;
- JSON-compatible payloads only;
- no pickle;
- no Python `repr()` as persisted contract;
- deterministic canonical JSON bytes for hashing;
- JSON round-trip;
- YAML round-trip, using a declared dependency if needed;
- validation errors for missing/invalid required fields;
- stable `sha256` helpers.

## Workspace Requirements

Implement a job workspace initializer that creates:

```text
runs/<job_id>/
  build_contract.yaml
  skill_spec.yaml
  verification_spec.yaml
  worker_input.md
  attempts/
  package/
    references/
    scripts/
    tests/
  verifier/
  artifact_manifest.json
  resume_brief.md
```

It should be acceptable if initial files are caller-supplied or initialized with
minimal valid content, but tests must prove the standard directory layout.

Implement:

- artifact hashing;
- manifest read/write;
- locked input hash recording;
- locked input tamper detection;
- safe relative path validation;
- path resolution under workspace root;
- rejection of absolute paths;
- rejection of `..`;
- rejection of symlink escape, or a documented explicit symlink ban enforced by code.

## Acceptance Tests

Add tests proving:

- all required schema objects JSON round-trip;
- schema objects YAML round-trip;
- canonical JSON hashing is stable;
- workspace initializer creates standard directories/files;
- artifact manifest covers locked inputs;
- locked input tamper is detected;
- workspace outside path is rejected;
- absolute paths are rejected;
- `..` paths are rejected;
- symlink escape is rejected or explicitly forbidden;
- package exposes `import skillfoundry`.

Run:

```bash
.venv/bin/python -m pytest -q
```

If `.venv` is missing, create it and install the package in editable test mode.

## Constraints

- Write code and comments in English unless existing project convention requires Chinese.
- Keep README/whitepaper docs changes minimal unless needed for install/test instructions.
- Do not use `.metaloop/` as a product runtime model.
- Do not copy ContextForge code wholesale. You may use similar ideas, but SkillFoundry must have its own product schema.
- Do not introduce network calls.
- Do not add a real Codex dependency.
- Do not implement worker execution or verifier business checks.

## Final Response

List:

- changed files;
- schema objects implemented;
- workspace/path safety behavior;
- validation commands and results;
- any intentional gaps left for WP2+.
