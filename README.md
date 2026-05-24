# SkillFoundry

SkillFoundry 是一个基于 **LangGraph + ContextForge + ForgeUnit + 外部
Codex/worker 边界 + 独立 Verifier** 的 Codex Skill 工厂实验系统。

当前主线不是旧 WP0-WP17 原型，而是：

```text
FrontDesk
  -> ContextForge Goal Runtime
  -> ForgeUnit SkillFoundry vNext
  -> Codex exec / deterministic fake command boundary
  -> SkillFoundry Verifier
  -> Registry
```

## Current Mainline

- **ContextForge**：agent 工作外骨骼，负责上下文视界、边界证据、cache plan、
  checkpoint 和 ledger。
- **ForgeUnit**：LangGraph 内的 work-unit harness，负责把强 worker 放进可审计、
  可验证的执行边界。
- **FrontDesk**：把用户模糊需求转为 core need、solution plan、frozen
  SkillSpec 和 acceptance criteria。
- **Codex exec / external worker**：可选执行体。默认测试不调用 live Codex。
- **Verifier / Registry**：独立质量门和资产注册门。worker self-report 不是验收。

## Quick Start

```bash
git clone --recurse-submodules git@github.com:manstein-lzn/skillfoundry.git
cd skillfoundry
git submodule update --init --recursive

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e third_party/contextforge
.venv/bin/python -m pip install -e ".[test,forgeunit]"
```

ForgeUnit is installed from the pinned Git tag:

```text
git+ssh://git@github.com/manstein-lzn/forgeunit.git@v1.2.1
```

It is not resolved from a local sibling directory.

## Developer Commands

Use the Makefile entrypoints:

```bash
make focused
make test
make fresh-clone-smoke
make live-semantic-eval-help
```

Equivalent script entrypoints:

```bash
scripts/dev_check.sh focused
scripts/dev_check.sh full
scripts/dev_check.sh fresh-clone
scripts/dev_check.sh live-help
```

Default commands are deterministic/offline. They do not call live Codex.

## Validation Gates

Use these before claiming a change is ready:

```bash
make focused
make test
```

Use this before claiming a new checkout can reproduce the baseline:

```bash
make fresh-clone-smoke
```

That command creates a temporary fresh clone, installs dependencies from public
Git refs, and runs a two-scenario fake-mode semantic smoke.

Live Codex semantic eval is manual and opt-in only:

```bash
make live-semantic-eval-help
```

Then follow [docs/FRONTDESK_LIVE_SEMANTIC_EVAL.md](docs/FRONTDESK_LIVE_SEMANTIC_EVAL.md).

## Important Docs

Start from [docs/README.md](docs/README.md) and
[docs/SYSTEM_MAP.md](docs/SYSTEM_MAP.md).

Current mainline docs:

- [System Map](docs/SYSTEM_MAP.md)
- [Development Workflow](docs/DEVELOPMENT_WORKFLOW.md)
- [Fresh Clone Gate](docs/FRESH_CLONE_GATE.md)
- [Legacy Compatibility](docs/LEGACY_COMPATIBILITY.md)
- [Test Ownership](tests/README.md)
- [FrontDesk Live Semantic Eval](docs/FRONTDESK_LIVE_SEMANTIC_EVAL.md)
- [Product Validation PV001: Codexarium Clean-Room Rebuild](docs/PRODUCT_VALIDATION_CODEXARIUM_REBUILD_PLAN.md)
- [SkillFoundry v2 Baseline](docs/SKILLFOUNDRY_V2_BASELINE.md)
- [SkillFoundry ContextForge Refactor Plan](docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md)
- [ForgeUnit SkillFoundry Composition](docs/FORGEUNIT_SKILLFOUNDRY_COMPOSITION.md)
- [ContextForge Agent Exoskeleton Product Vision](docs/CONTEXTFORGE_AGENT_EXOSKELETON_PRODUCT_VISION.md)

Historical WP/v0 roadmaps, pilots, and operations notes are preserved under
[docs/archive](docs/archive/). They are context, not the current implementation
contract.

## Repository Layout

```text
src/forgeunit_skillfoundry/   # current clean composition layer
src/skillfoundry/             # product capabilities reused by the current layer
tests/                        # deterministic/offline tests
scripts/                      # local gates and explicit manual pilots
third_party/contextforge/     # ContextForge submodule
docs/                         # current docs plus archive
```

## Boundaries

SkillFoundry currently proves a governed Codex Skill factory path. It is not yet
presented as a production multi-tenant platform.

Short-term repository cleanup is complete through Phase 13N. See
[docs/SKILLFOUNDRY_CLEANUP_COMPLETION_PLAN.md](docs/SKILLFOUNDRY_CLEANUP_COMPLETION_PLAN.md).
Real product validation with live Codex scenarios is intentionally later.

Not default:

- live Codex calls;
- background workers or schedulers;
- long-term memory daemons;
- CI deployment;
- production auth/tenant/queue/audit stack.

Those may be added later, but the current baseline is intentionally small,
auditable, and deterministic by default.
