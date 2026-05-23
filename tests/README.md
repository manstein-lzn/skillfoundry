# SkillFoundry Test Ownership

The test suite is deterministic/offline by default. `make test` runs the full
pytest suite and must not call live Codex. Some tests exercise compatibility
islands, script wrappers, or manual pilot tooling; those tests are still useful
coverage, but they are not instructions for the current product architecture.

## Default Gates

Use these commands:

```bash
make focused
make test
make fresh-clone-smoke
```

`make focused` is the fast deterministic FrontDesk/ForgeUnit gate.

`make test` is the complete deterministic pytest gate. It includes current
mainline tests, compatibility tests, and script smoke tests.

`make fresh-clone-smoke` creates a temporary fresh clone and runs an offline
fake-mode semantic smoke. It uses network/Git to clone/install, but it does not
call live Codex.

## Current Mainline Tests

These tests protect the current product path:

```text
FrontDesk
  -> ContextForge Goal Runtime
  -> ForgeUnit SkillFoundry vNext
  -> Codex exec / deterministic fake command boundary
  -> SkillFoundry Verifier
  -> Registry
```

Files:

- `tests/test_api.py`
- `tests/test_frontdesk_api.py`
- `tests/test_frontdesk_auditor.py`
- `tests/test_frontdesk_elicitor.py`
- `tests/test_frontdesk_freeze_gate.py`
- `tests/test_frontdesk_goal_runtime.py`
- `tests/test_frontdesk_loop.py`
- `tests/test_frontdesk_schema.py`
- `tests/test_frontdesk_v2.py`
- `tests/test_frontdesk_workspace.py`
- `tests/test_forgeunit_adapter.py`
- `tests/test_forgeunit_skillfoundry_adapters.py`
- `tests/test_forgeunit_skillfoundry_composition.py`
- `tests/test_forgeunit_skillfoundry_scripts.py`
- `tests/test_contracts.py`
- `tests/test_final_report.py`
- `tests/test_public_api.py`
- `tests/test_registry.py`
- `tests/test_schema.py`
- `tests/test_verification_bridge.py`
- `tests/test_verifier.py`
- `tests/test_workspace.py`

Interpretation:

- Failures here usually indicate a current-product regression.
- Prefer fixing the implementation or updating the current product contract
  before weakening these tests.

## Compatibility Tests

These tests protect module-scoped compatibility surfaces that still serve
fixtures, migration checks, or current bridge maintenance.

Files:

- `tests/test_graph_v2.py`
- `tests/test_graph_v2_runtime.py`
- `tests/test_goal_harness_slice.py`
- `tests/test_goal_harness_verified_runtime.py`
- `tests/test_workers_v2.py`
- `tests/test_acceptance_coverage.py`
- `tests/test_feedback.py`
- `tests/test_qa.py`
- `tests/test_ops.py`

Interpretation:

- Failures can still be important because current bridge code may rely on these
  surfaces.
- These tests do not mean graph v2, direct Goal Runtime runners, feedback, QA,
  or ops support APIs should be promoted back to package root.
- New imports for these surfaces should usually come from explicit modules such
  as `skillfoundry.graph_v2`, `skillfoundry.goal_runtime`,
  `skillfoundry.feedback`, `skillfoundry.qa`, or `skillfoundry.ops`.

## Legacy Fixture Tests

These tests preserve deterministic coverage for old v0/WP compatibility
islands.

Files:

- `tests/test_offline.py`
- `tests/test_worker.py`
- `tests/test_codex_worker.py`
- `tests/test_context.py`

Interpretation:

- Failures here usually mean a compatibility island changed.
- Passing these tests does not make `offline.py`, `worker.py`, `CodexWorker`,
  or `context.py` the current product mainline.
- Do not add new product features to these old paths without first checking
  `docs/LEGACY_COMPATIBILITY.md`.

## Script Smoke Tests

These tests exercise local scripts, wrappers, and manual pilot helpers in
deterministic mode.

Files:

- `tests/test_frontdesk_forgeunit_command_pilot_script.py`
- `tests/test_frontdesk_live_codex_eval_script.py`
- `tests/test_forgeunit_real_codex_pilot_scripts.py`

Interpretation:

- These tests validate parser behavior, deterministic fake-mode flows, redaction
  rules, and wrapper boundaries.
- They do not call live Codex during `make test`.
- Script names may mention live Codex or real Codex pilots because they test
  operator tooling. Live execution still requires explicit manual commands.

## Live Opt-In

Live Codex semantic evaluation is not part of `make test`.

Use:

```bash
make live-semantic-eval-help
```

Then follow:

```text
docs/FRONTDESK_LIVE_SEMANTIC_EVAL.md
```

Live opt-in evidence should stay under local artifact paths such as `.local/`,
`.local_registry/`, or `runs/` unless a separate review decides otherwise.

## Cleanup Rule

Before deleting or moving a test, identify the behavior it owns:

- current product behavior;
- compatibility surface;
- legacy fixture;
- script smoke;
- live opt-in support.

Then update this file, affected docs, and the relevant deterministic gate.
Physical test moves are optional and should only happen when they improve
understanding more than this ownership map already does.
