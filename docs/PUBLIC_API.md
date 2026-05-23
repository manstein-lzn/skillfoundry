# SkillFoundry Public API

This document defines what belongs at the top-level `skillfoundry` package
root during the cleanup period. It is a cleanup contract, not a promise that
every current export is permanent.

## Package Root Public API

The package root should make the current product path easy to discover:

```text
FrontDesk
  -> ContextForge Goal Runtime
  -> ForgeUnit SkillFoundry vNext
  -> Codex exec / deterministic fake command boundary
  -> SkillFoundry Verifier
  -> Registry
```

Top-level exports are allowed only when they are useful to a caller building or
inspecting that path, or when they are an explicit compatibility entrypoint.

## Allowed Package-Root Groups

Current product entrypoints:

- API/server entrypoints such as `SkillFoundryAPI`, `serve_http`,
  `make_handler`, and `make_server`.
- FrontDesk user-facing data and workflow helpers such as `FrontDeskConfig`,
  `FrontDeskState`, `ConversationTurn`, `FrontDeskWorkspace`,
  `initialize_frontdesk_workspace`, `append_conversation_turn`, and
  `read_conversation_turns`.
- ForgeUnit bridge entrypoints that run or inspect the current vNext
  composition layer.
- ContextForge contract and Goal Runtime helpers that are part of the current
  refs-only evidence path, such as `build_goal_contract`,
  `build_agent_node_contract`, `build_verification_gate`, and
  `seed_goal_harness_context`.
- Independent gates and durable schemas such as `Verifier`,
  `LocalSkillRegistry`, `JobWorkspace`, `SkillSpec`, `VerificationSpec`,
  `VerificationResult`, `BuildContract`, and `ArtifactManifest`.

Compatibility entrypoints:

- `build_offline`
- `OfflineWorkerMode`

These remain top-level because deterministic CLI/dev compatibility still uses
them directly. Other legacy offline internals are module-scoped.

## Module-Scoped Surfaces

Use explicit module imports for internals, compatibility fixtures, and
subsystem-specific helpers.

Compatibility islands:

- `skillfoundry.offline`
- `skillfoundry.worker`
- `skillfoundry.context`

Subsystem internals:

- `skillfoundry.frontdesk_goal_runtime`
- `skillfoundry.goal_runtime`
- `skillfoundry.graph_v2`
- `skillfoundry.feedback`
- `skillfoundry.qa`
- `skillfoundry.ops`

Tests may import from these modules when they are testing internals. New
product code should not promote module internals back to package root without
updating this contract.

## Cleanup Rule

When an export is needed only by tests, deterministic fixtures, historical
pilots, or implementation-internal type annotations, import it from its module.
Do not keep it at package root.

When a top-level export is removed:

- Keep module-level compatibility if existing tests or tools need it.
- Update tests to import from the explicit module.
- Add or update a public API static check.
- Run the deterministic gates from the cleanup plan.

## Current Phase 13H Removal Set

The following implementation-internal types must not leak through
`skillfoundry` or `skillfoundry.__all__`:

- `FrontDeskCoreNeedFakeWorker`
- `FrontDeskSolutionPlannerFakeWorker`
- `FrontDeskSpecAuditorFakeWorker`
- `FrontDeskCoreNeedGoalHarnessResult`
- `FrontDeskSolutionPlannerGoalHarnessResult`
- `FrontDeskSpecAuditorGoalHarnessResult`
- `GoalHarnessWorkerFactory`
- `SkillFoundryGoalHarnessResult`
- `VerifiedSkillFoundryGoalHarnessResult`
- `RepairSkillFoundryGoalHarnessResult`
- `VerifiedRepairSkillFoundryGoalHarnessResult`

They remain available from their implementation modules when a test or maintainer
needs them.
