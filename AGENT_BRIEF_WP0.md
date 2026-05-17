# AGENT BRIEF WP0: SkillFoundry Design v0.2

You are implementing WP0 for SkillFoundry. You are not alone in this
repository: do not revert edits made by others, and keep your changes scoped to
the design/documentation package described here.

## Role

Update the SkillFoundry design documents so they accurately reflect the
architecture chosen after independent review:

```text
LangGraph orchestration
+ file-as-context workspace protocol
+ Codex Worker as a black-box high-capability builder
+ independent verifier as the quality gate
+ registry as the approved asset store
+ ContextForge as evidence ledger and owned-LLM context runtime
+ MetaLoop-style task governance ideas, rewritten for SkillFoundry
```

This is a documentation/design work package. Do not implement product code.

## Required Inputs

Read these files first:

- `README.md`
- `WHITEPAPER.md`
- `docs/ROADMAP.md`
- Optional context: `/home/mansteinl/contextforge/README.md`

## Design Corrections Required

The current `WHITEPAPER.md` still overstates ContextForge's role. Fix this.

Required corrections:

- Distinguish **SkillFoundry-owned LLM calls** from **external worker
  invocations**.
- Owned LLM calls may be fully controlled by ContextForge:
  `ContextRequest -> PromptView -> ModelCallEnvelope -> ContextKernel`.
- Codex Worker invocations are black-box external worker boundaries. ContextForge
  records worker input/output, transcript, diff, hashes, duration, verifier
  evidence, and usage availability, but does not claim to control or replay
  Codex internal prompts/tool loops/cache behavior.
- Replace broad claims like "all important LLM calls go through ContextForge"
  with precise boundary language.
- Define the route as an "external worker supervised factory", not a
  ContextForge-built ActionRuntime.
- Make Verifier the primary quality gate; LLM judge is optional and never the
  only gate.
- State that builder self-report is not acceptance evidence.
- State that real Codex Worker integration must wait until workspace
  confinement, WorkerAdapter, verifier, and registry gate exist.

## Required Files

Create or update:

- `WHITEPAPER.md`
- `docs/ARCHITECTURE.md`
- `docs/WORK_PACKAGES.md`
- `docs/ACCEPTANCE_PLAN.md`
- `README.md` only if needed for links or terminology alignment

Keep `docs/ROADMAP.md` compatible with your changes. Update only if you find a
real inconsistency.

## Content Requirements

### `WHITEPAPER.md`

Make it v0.2-compatible. It must clearly explain:

- product vision;
- conditional-go route;
- Codex Worker black-box boundary;
- ContextForge owned-call vs worker-boundary responsibilities;
- workspace/file-as-context strategy;
- verifier and registry trust model;
- risks and non-goals;
- phased roadmap summary.

### `docs/ARCHITECTURE.md`

Must define:

- system layers;
- LangGraph state boundary;
- workspace protocol;
- WorkerAdapter boundary;
- ContextForge integration points;
- verifier gate;
- registry trust model;
- security baseline;
- Mermaid-free ASCII diagrams preferred.

### `docs/WORK_PACKAGES.md`

Must define implementable WPs from WP0 onward, with:

- goal;
- owns;
- non-goals;
- acceptance criteria;
- dependency/order.

Keep the first implementation sequence conservative:

1. WP0 docs v0.2
2. WP1 workspace + schema
3. WP2 LangGraph skeleton
4. WP3 WorkerAdapter
5. WP4 Verifier
6. WP5 ContextForge integration
7. WP6 Registry MVP
8. WP7 offline E2E MVP
9. WP8 CodexWorker pilot
10. WP9 minimal API/UI
11. WP10 feedback loop

### `docs/ACCEPTANCE_PLAN.md`

Must define:

- document acceptance;
- schema/workspace acceptance;
- LangGraph state acceptance;
- WorkerAdapter acceptance;
- verifier acceptance;
- ContextForge integration acceptance;
- registry acceptance;
- E2E smoke acceptance;
- security/fail-closed requirements.

## Constraints

- Write in Simplified Chinese.
- Do not copy MetaLoop implementation details or `.metaloop/` layout directly
  into the product model.
- Do not claim ContextForge already provides sandbox, shell runtime, MCP
  runtime, permissions, queues, UI, or real Codex integration.
- Do not claim full replay or prompt-cache control for Codex Worker internals.
- Do not introduce product code in this WP.
- Keep terminology clear enough that third-party implementation agents can work
  from the docs.

## Validation

Run lightweight checks:

```bash
test -f WHITEPAPER.md
test -f docs/ARCHITECTURE.md
test -f docs/WORK_PACKAGES.md
test -f docs/ACCEPTANCE_PLAN.md
grep -q "Codex Worker" WHITEPAPER.md
grep -q "ContextForge" docs/ARCHITECTURE.md
grep -q "WorkerAdapter" docs/WORK_PACKAGES.md
grep -q "Verifier" docs/ACCEPTANCE_PLAN.md
```

Final response must list changed files and summarize the key design corrections.
