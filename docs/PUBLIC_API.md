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

Support modules:

- `skillfoundry.feedback` is a feedback/versioning support surface from the
  WP11 line. Keep it available by explicit module import.
- `skillfoundry.qa` is deterministic QA support from the WP10 line. It may be
  useful for local acceptance hardening, but it is not part of the package-root
  product path.
- `skillfoundry.ops` is local health, observability, and cleanup support from
  the WP12 line. It remains module-scoped because it is operational support,
  not a product construction entrypoint.

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

## Current Phase 13I Removal Set

The following support-surface names must not leak through `skillfoundry` or
`skillfoundry.__all__`:

- `DEFAULT_REQUIRED_VERSION_GATES`
- `FEEDBACK_RECORD_VERSION`
- `FEEDBACK_REPAIR_PLAN_VERSION`
- `FEEDBACK_VERSIONING_PROVENANCE_VERSION`
- `ROLLBACK_EVENT_VERSION`
- `VERSION_CHANGE_REPORT_VERSION`
- `FeedbackRecord`
- `FeedbackRepairPlan`
- `FeedbackVersionGateError`
- `FeedbackVersioningError`
- `RepairRegistrationResult`
- `SkillVersionManager`
- `HARD_CHECK_NAMES`
- `QA_LAB_VERSION`
- `QA_REPORT_VERSION`
- `QACheck`
- `QALab`
- `QAResult`
- `OPS_CLEANUP_REPORT_VERSION`
- `OPS_HEALTH_REPORT_VERSION`
- `OPS_OBSERVABILITY_REPORT_VERSION`
- `OPS_VERSION`
- `SkillFoundryOps`

They remain available from `skillfoundry.feedback`, `skillfoundry.qa`, or
`skillfoundry.ops` when compatibility fixtures or maintainers need them.

## Current Phase 13J Removal Set

The package root keeps `seed_goal_harness_context` because it is a small
current ContextForge evidence helper. The rest of the direct Goal Runtime and
graph v2 surfaces are module-scoped.

Goal Runtime names that must not leak through `skillfoundry` or
`skillfoundry.__all__`:

- `GOAL_RUNTIME_LEDGER_REF`
- `GOAL_RUNTIME_RESULT_REF`
- `GOAL_RUNTIME_RESULT_SCHEMA_VERSION`
- `GOAL_RUNTIME_STATE_REF`
- `GOAL_RUNTIME_STATE_SCHEMA_VERSION`
- `VERIFIED_GOAL_RUNTIME_RESULT_REF`
- `VERIFIED_GOAL_RUNTIME_RESULT_SCHEMA_VERSION`
- `build_goal_harness_state`
- `build_repair_goal_harness_state`
- `run_offline_goal_harness`
- `run_repair_goal_harness`
- `run_verified_repair_goal_harness`
- `run_verified_offline_goal_harness`

Graph v2 names that must not leak through `skillfoundry` or
`skillfoundry.__all__`:

- `GRAPH_V2_STATE_REF`
- `MAX_V2_INLINE_STRING_BYTES`
- `SkillFoundryV2State`
- `V2Route`
- `V2Stage`
- `V2StateValidationError`
- `V2Status`
- `build_offline_goal_harness_node`
- `build_human_review_node`
- `build_repair_goal_harness_node`
- `build_skillfoundry_v2_graph`
- `build_verified_goal_harness_node`
- `build_verified_repair_verification_node`
- `build_verified_registry_gate_node`
- `compile_skillfoundry_v2_graph`
- `route_after_repair`
- `route_after_verification`
- `run_verified_skillfoundry_v2_graph`
- `validate_v2_graph_state`

They remain available from `skillfoundry.goal_runtime` or
`skillfoundry.graph_v2` for compatibility graph tests, ForgeUnit bridge
maintenance, and explicit runtime inspection.
