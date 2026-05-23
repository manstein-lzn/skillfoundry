# SkillFoundry Docs

This directory separates the current implementation contract from historical
design assets.

## Start Here

Read these first, in order:

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

- [System Map](SYSTEM_MAP.md)
- [ForgeUnit SkillFoundry Composition](FORGEUNIT_SKILLFOUNDRY_COMPOSITION.md)
- [ForgeUnit Product Adapter Slice](FORGEUNIT_PRODUCT_ADAPTER_SLICE.md)
- [Development Workflow](DEVELOPMENT_WORKFLOW.md)
- [Fresh Clone Gate](FRESH_CLONE_GATE.md)
- [SkillFoundry Cleanup Completion Plan](SKILLFOUNDRY_CLEANUP_COMPLETION_PLAN.md)
- [Source/Test Cleanup Plan](SOURCE_TEST_CLEANUP_PLAN.md)

Architecture and product direction:

- [SkillFoundry v2 Baseline](SKILLFOUNDRY_V2_BASELINE.md)
- [SkillFoundry ContextForge Refactor Plan](SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md)
- [SkillFoundry on ForgeUnit Product Direction](SKILLFOUNDRY_ON_FORGEUNIT_PRODUCT_DIRECTION.md)
- [ContextForge Agent Exoskeleton Product Vision](CONTEXTFORGE_AGENT_EXOSKELETON_PRODUCT_VISION.md)
- [ContextForge Goal Harness Rebuild Plan](CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md)

Manual runbooks:

- [FrontDesk ForgeUnit Command Pilot Runbook](FRONTDESK_FORGEUNIT_COMMAND_PILOT_RUNBOOK.md)
- [FrontDesk Live Semantic Eval](FRONTDESK_LIVE_SEMANTIC_EVAL.md)

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
