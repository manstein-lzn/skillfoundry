# SkillFoundry Cleanup Completion Plan

This plan defines the remaining short-term cleanup work required before
SkillFoundry is considered clean enough for a new contributor to understand and
extend. It intentionally stops before real product validation. Product
validation with real Skill requests and live Codex remains a later phase.

## Current Baseline

SkillFoundry's current mainline is:

```text
FrontDesk
  -> ContextForge Goal Runtime
  -> ForgeUnit SkillFoundry vNext
  -> Codex exec / deterministic fake command boundary
  -> SkillFoundry Verifier
  -> Registry
```

This is the current implementation contract. Historical WP0-WP17 assets,
legacy offline builder paths, legacy worker adapters, and old owned-call
context adapters may remain as compatibility islands, but they must not define
the current product architecture.

Cleanup already completed:

- Phase 13A retired the old WP2 graph.
- Phase 13B retired the old `llm_builder.py`.
- Phase 13C extracted `final_report.py` from legacy `offline.py`.
- Phase 13D retired legacy API/UI `POST /jobs` offline creation.
- Phase 13E removed the hidden ops offline build helper.
- Phase 13F removed legacy worker/offline internals from top-level
  `skillfoundry`.
- Phase 13G removed legacy context adapter internals from top-level
  `skillfoundry`.

The repo now has a runnable deterministic baseline:

```bash
make focused
make test
make fresh-clone-smoke
```

## Definition of Cleanup Done

Short-term cleanup is complete when a new user can inspect the repository and
answer these questions without reading historical WP material:

- What is the current product path?
- Which modules are current, compatibility, or historical?
- Which package-root exports are supported for current development?
- Which tests protect current behavior and which tests are compatibility
  fixtures?
- Which docs are source of truth and which docs are archived context?
- Which local commands prove the deterministic baseline?

Concretely, the cleanup is done when:

- `README.md`, `docs/README.md`, and `HANDOFF.md` point to one consistent
  current architecture.
- `src/skillfoundry/__init__.py` exposes a deliberately small public surface.
- Legacy islands are explicit:
  `skillfoundry.offline`, `skillfoundry.worker`, `skillfoundry.context`, and
  any remaining compatibility modules are documented as compatibility surfaces.
- Default tests and smoke commands remain deterministic/offline.
- Fresh clone smoke passes from `origin/main`.
- No root-level or current-doc page tells new users to build on a retired path.

## Non-Goals

This cleanup plan does not include:

- Real product validation with new SkillFoundry scenarios.
- Live Codex semantic evaluation.
- Production deployment, auth, tenancy, queues, or background workers.
- Long-term memory design.
- Replacing ContextForge, ForgeUnit, or LangGraph.
- Deleting a compatibility module before imports, tests, docs, and CLI usage
  have been audited.

## Cleanup Principles

- Prefer small phases that can be independently verified.
- Retire or isolate legacy surfaces before deleting files.
- Keep current product behavior stable while shrinking public surface area.
- Treat tests as ownership signals: tests should reveal whether a behavior is
  current, compatibility, or historical.
- Keep local validation offline unless a phase is explicitly about live eval.
- Do not move large amounts of code just to make the tree look tidy; move only
  when it improves comprehension or prevents incorrect usage.

## Remaining Cleanup Phases

### Phase 13H: Package Root Public API Contract

Goal:

Define and enforce the intended `skillfoundry` package-root API after phases
13F and 13G.

Work:

- Add a short public API section to docs explaining what belongs at package
  root versus submodules.
- Audit current `src/skillfoundry/__init__.py` exports.
- Classify exports as:
  `current_public`, `current_internal`, `compatibility_public`,
  `compatibility_module_only`, or `historical_remove`.
- Remove top-level exports that are useful only for tests or legacy fixtures.
- Keep important current product entrypoints discoverable.

Likely candidates to review:

- `feedback.py` exports such as `SkillVersionManager` and feedback constants.
- `qa.py` exports such as `QALab` and QA constants.
- graph v2 helper exports that are not intended as package-root API.
- FrontDesk fake worker/runtime result classes that may only belong in
  `frontdesk_goal_runtime.py`.

Acceptance:

- A documented package-root allowlist exists.
- Static tests prove disallowed legacy/internal exports do not leak through
  `skillfoundry.__all__`.
- Existing current tests still pass.

Suggested validators:

```bash
git diff --check
.venv/bin/python -m pytest tests/test_* -q
make focused
make test
```

### Phase 13I: Support Surface Audit (`feedback.py`, `qa.py`, `ops.py`)

Goal:

Decide whether support modules are current product surfaces, compatibility
surfaces, or module-level utilities.

Work:

- Audit `feedback.py`:
  determine whether versioning and repair feedback are active product features
  or v0 support surfaces.
- Audit `qa.py`:
  determine whether QALab is current acceptance support or legacy WP support.
- Confirm `ops.py` is already reduced to health, observability, cleanup.
- Remove unnecessary top-level exports for support modules.
- Keep module-level imports where tests or explicit tools still require them.

Acceptance:

- Each module has a short status note in the cleanup plan or a module docstring.
- Package-root exports are consistent with that status.
- Tests import support internals from modules when they are not current
  package-root API.

Suggested focused tests:

```bash
.venv/bin/python -m pytest tests/test_feedback.py tests/test_qa.py tests/test_ops.py tests/test_registry.py -q
make focused
make test
```

### Phase 13J: Graph v2 and Goal Runtime Export Audit

Goal:

Keep current runtime compatibility while reducing package-root noise from graph
and goal-runtime helper internals.

Work:

- Audit `graph_v2.py` exports:
  keep only the compatibility graph entrypoints that external callers should
  reasonably use.
- Audit `goal_runtime.py` exports:
  keep current Goal Runtime helpers needed by ForgeUnit adapter, graph v2, and
  tests.
- Distinguish `seed_goal_harness_context` and contract/state helpers that
  belong to the current ContextForge evidence path from older offline harness
  compatibility helpers.
- Move tests to explicit module imports where they assert internal behavior.

Acceptance:

- Top-level graph/runtime exports are deliberate.
- Current ForgeUnit adapter and FrontDesk build tests pass.
- No current path imports final report helpers from `offline.py`.

Suggested focused tests:

```bash
.venv/bin/python -m pytest tests/test_graph_v2.py tests/test_graph_v2_runtime.py tests/test_goal_harness_slice.py tests/test_goal_harness_verified_runtime.py tests/test_forgeunit_adapter.py -q
make focused
make test
```

### Phase 13K: Legacy Island Index

Goal:

Make remaining compatibility islands explicit so new users know they are not
the product mainline.

Work:

- Add a concise legacy compatibility index, likely
  `docs/LEGACY_COMPATIBILITY.md`.
- Cover:
  `offline.py`, `worker.py`, `context.py`, compatibility parts of `graph_v2.py`,
  archived CodexWorker pilot notes, and deterministic fixture tests.
- Link this index from `docs/README.md` and `HANDOFF.md`.
- State what is still allowed:
  direct CLI/dev fixtures, deterministic migration coverage, and historical
  evidence preservation.
- State what is not allowed:
  new product features built on retired API/UI offline creation, old
  WorkerAdapter as the main current worker boundary, or old context adapter as
  the current context manager.

Acceptance:

- New contributors can identify all compatibility islands from one page.
- Existing archive docs do not need to be deleted, but current docs point to the
  compatibility index before archive material.

Suggested validators:

```bash
rg -n "LEGACY_COMPATIBILITY|Compatibility Islands|Current Mainline" docs/README.md HANDOFF.md docs/LEGACY_COMPATIBILITY.md
git diff --check
```

### Phase 13L: Test Ownership Map

Goal:

Make the test suite readable by ownership without disrupting working coverage.

Work:

- Add `tests/README.md` or an equivalent docs section that classifies tests as:
  current mainline, compatibility, legacy fixture, script smoke, and live-opt-in
  script coverage.
- Optionally add pytest markers later, but do not physically move test files
  unless the benefit is clear.
- Ensure legacy fixture tests no longer imply package-root API ownership.
- Keep the default `make test` behavior unchanged.

Acceptance:

- A new developer can identify which tests protect current product behavior.
- Compatibility tests are not mistaken for current architecture guidance.
- `make test` remains the default complete deterministic gate.

Suggested validators:

```bash
test -f tests/README.md
rg -n "Current mainline|Compatibility|Legacy fixture|Live opt-in" tests/README.md
make test
```

### Phase 13M: Current Docs Entry Consolidation

Goal:

Reduce doc-entry confusion before real product validation begins.

Work:

- Update `docs/README.md` so the first screen is the current reading path:
  architecture, composition, development workflow, fresh clone gate, cleanup
  state, compatibility index.
- Keep historical vision docs available, but ensure they do not outrank current
  implementation docs.
- Add or update a compact `docs/SYSTEM_MAP.md` if the current architecture still
  requires too many docs to understand.
- Ensure archive pages remain context only.

Acceptance:

- A new user can follow a 10-minute reading path.
- Current docs do not send users into old WP roadmaps as implementation
  contracts.
- README, docs README, and HANDOFF agree on the current mainline.

Suggested validators:

```bash
rg -n "Current Mainline|Start Here|Compatibility|Cleanup" README.md docs/README.md HANDOFF.md
git diff --check
```

### Phase 13N: Final New-User Cleanup Gate

Goal:

Close short-term cleanup with a fresh clone, source tree, docs, and package API
audit.

Work:

- Run a root-file audit:
  ensure no runtime artifacts, generated packages, old briefs, or stray local
  files are tracked.
- Run a package-root export audit against the allowlist from Phase 13H.
- Run a docs search for retired-path claims.
- Run the deterministic gates:
  `make focused`, `make test`, and `make fresh-clone-smoke`.
- Record the final cleanup result in `HANDOFF.md` and
  `docs/SOURCE_TEST_CLEANUP_PLAN.md`.

Acceptance:

- Working tree is clean after commit.
- `main` equals `origin/main`.
- Fresh clone smoke passes.
- The cleanup plan can move from active to completed.

Suggested validators:

```bash
git status --short --branch
git diff --check
make focused
make test
make fresh-clone-smoke
```

## Validation Gates

Every cleanup phase should use the smallest adequate gate:

- Documentation-only phases:
  `git diff --check` plus specific `rg` or file-existence checks.
- Public API changes:
  static import/export checks, focused tests, `make focused`, `make test`.
- Test ownership changes:
  affected tests plus `make test`.
- Final cleanup closeout:
  `make focused`, `make test`, and `make fresh-clone-smoke`.

Live Codex eval is excluded from cleanup validation. It belongs to product
validation later.

## Stop Cleanup When

Stop the short-term cleanup and move to product validation when all of these
are true:

- Package-root API is deliberate and documented.
- Remaining legacy modules are explicitly indexed as compatibility islands.
- Tests are classified by ownership.
- Current docs have a short, unambiguous reading path.
- Fresh clone smoke passes after the final cleanup commit.
- The only remaining work requires real product behavior, real user scenarios,
  live Codex, deployment, or long-running operations evidence.

At that point, additional cleanup without product validation has diminishing
returns.

## Product Validation Later

After cleanup is complete, product validation should start with a separate
plan. That plan should cover:

- 3-5 real SkillFoundry scenarios.
- live Codex semantic eval as an explicit opt-in gate.
- failure taxonomy for repair, verifier rejection, registry rejection, and
  human review.
- evidence UX for refs-only API/UI reads.
- cost/cache/context observations.
- long-running task recovery and checkpoint behavior.

Those are intentionally out of scope for this cleanup completion plan.
