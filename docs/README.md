# SkillFoundry Docs

This directory separates the current implementation contract from historical
design assets.

## Start Here

Read these first, in order:

- [Agent Work Substrate Vision](AGENT_WORK_SUBSTRATE_VISION.md): cross-application substrate vision for LangGraph + ForgeUnit + ContextForge adaptive agent work.
- [SkillFoundry Capability Bundle Vision](SKILLFOUNDRY_CAPABILITY_BUNDLE_VISION.md): product constitution for the AI-native capability bundle direction.
- [System Map](SYSTEM_MAP.md): current architecture and 10-minute reading path.
- [ForgeUnit SkillFoundry Composition](FORGEUNIT_SKILLFOUNDRY_COMPOSITION.md): current product composition layer.
- [SkillFoundry Public API](PUBLIC_API.md): package-root API contract during cleanup.
- [Legacy Compatibility](LEGACY_COMPATIBILITY.md): compatibility islands that remain for fixtures, maintenance, or history.
- [Test Ownership](../tests/README.md): which tests protect current mainline, compatibility, legacy fixtures, scripts, and live opt-in support.
- [Development Workflow](DEVELOPMENT_WORKFLOW.md): local commands and validation gates.
- [Fresh Clone Gate](FRESH_CLONE_GATE.md): new-user reproducibility check.
- [SkillFoundry Cleanup Completion Plan](SKILLFOUNDRY_CLEANUP_COMPLETION_PLAN.md): completed short-term cleanup plan; product validation remains later.

## Current Mainline

The current mainline is:

```text
FrontDesk
  -> ContextForge Goal Runtime
  -> ForgeUnit SkillFoundry vNext
  -> Codex exec / deterministic fake command boundary
  -> SkillFoundry Verifier
  -> Registry
```

Implementation docs:

- [Codex Goal Adaptive Steering Execution Plan](CODEX_GOAL_ADAPTIVE_STEERING_EXECUTION_PLAN.md)
- [Adaptive Steering Implementation Plan](ADAPTIVE_STEERING_IMPLEMENTATION_PLAN.md)
- [System Map](SYSTEM_MAP.md)
- [ForgeUnit SkillFoundry Composition](FORGEUNIT_SKILLFOUNDRY_COMPOSITION.md)
- [ForgeUnit Product Adapter Slice](FORGEUNIT_PRODUCT_ADAPTER_SLICE.md)
- [Development Workflow](DEVELOPMENT_WORKFLOW.md)
- [Fresh Clone Gate](FRESH_CLONE_GATE.md)
- [SkillFoundry Cleanup Completion Plan](SKILLFOUNDRY_CLEANUP_COMPLETION_PLAN.md)
- [Source/Test Cleanup Plan](SOURCE_TEST_CLEANUP_PLAN.md)

Architecture and product direction:

- [Agent Work Substrate Vision](AGENT_WORK_SUBSTRATE_VISION.md)
- [SkillFoundry Capability Bundle Vision](SKILLFOUNDRY_CAPABILITY_BUNDLE_VISION.md)
- [SkillFoundry v2 Baseline](SKILLFOUNDRY_V2_BASELINE.md)
- [SkillFoundry ContextForge Refactor Plan](SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md)
- [SkillFoundry on ForgeUnit Product Direction](SKILLFOUNDRY_ON_FORGEUNIT_PRODUCT_DIRECTION.md)
- [ContextForge Agent Exoskeleton Product Vision](CONTEXTFORGE_AGENT_EXOSKELETON_PRODUCT_VISION.md)
- [ContextForge Goal Harness Rebuild Plan](CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md)

Manual runbooks:

- [FrontDesk ForgeUnit Command Pilot Runbook](FRONTDESK_FORGEUNIT_COMMAND_PILOT_RUNBOOK.md)
- [FrontDesk Live Semantic Eval](FRONTDESK_LIVE_SEMANTIC_EVAL.md)
- [Product Validation PV001: Codexarium Clean-Room Rebuild](PRODUCT_VALIDATION_CODEXARIUM_REBUILD_PLAN.md)

Live Codex evaluation is manual and opt-in. It is not part of default cleanup
validation.

## Compatibility Boundaries

- [SkillFoundry Public API](PUBLIC_API.md)
- [Legacy Compatibility](LEGACY_COMPATIBILITY.md)
- [Test Ownership](../tests/README.md)

Read these before promoting a module-scoped compatibility helper back to
package root, deleting a legacy module, or using archived WP material as
implementation guidance.

## Archive

Historical documents are preserved under [archive](archive/), but they are not
the current implementation contract. Use them for context, not as source of
truth for today decisions.

- [v0 and WP artifacts](archive/v0/)
- [Historical roadmaps and audits](archive/roadmaps/)
- [Historical pilot notes](archive/pilots/)
- [Historical operations/readiness notes](archive/operations/)
- [Archived agent briefs](archive/agent-briefs/)
