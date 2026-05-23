# SkillFoundry Handoff

更新日期：2026-05-24

## Current mainline / 当前主线

SkillFoundry 当前主线是一个小而可验证的 Codex Skill 工厂：

```text
FrontDesk
  -> ContextForge Goal Runtime
  -> ForgeUnit SkillFoundry vNext
  -> Codex exec / deterministic fake command boundary
  -> SkillFoundry Verifier
  -> Registry
```

这不是旧 WP0-WP17 原型的继续堆叠。旧代码和文档仍作为经验资产保留，但当前实现方向以
`LangGraph + ContextForge + ForgeUnit + Codex exec boundary + independent Verifier`
为准。

## Start Here

新接手时优先读：

- `README.md`：项目定位、安装方式、默认验证命令。
- `docs/README.md`：当前文档导航和历史归档入口。
- `docs/SKILLFOUNDRY_V2_BASELINE.md`：为什么不背 v0 兼容债。
- `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`：当前架构蓝图。
- `docs/FORGEUNIT_SKILLFOUNDRY_COMPOSITION.md`：当前 clean composition layer。
- `docs/DEVELOPMENT_WORKFLOW.md`：本地开发和验证命令。

历史 whitepaper、WP 文档、roadmap、pilot、operations notes 和 agent briefs 已归档到
`docs/archive/`。它们解释历史，不定义当前实现合同。

## Current Code Entrypoints

- `src/forgeunit_skillfoundry/`
  - 当前清爽拼接层。
  - 通过 `run_codex_skill_factory(...)` / `run_skill_factory_graph(...)` 运行
    ForgeUnit-backed Skill factory path。
- `src/forgeunit_skillfoundry/adapters/`
  - 把已有 `JobWorkspace` 或 approved/frozen FrontDesk job 路由进 vNext。
- `src/skillfoundry/api.py`
  - FrontDesk API。
  - `POST /frontdesk/jobs/{job_id}/build` 默认走
    `forgeunit_skillfoundry_vnext`。
  - legacy `POST /jobs` offline 创建入口已退役；`GET /jobs...` 仍作为 evidence/read
    view 保留。
- `src/skillfoundry/ops.py`
  - 仅保留 local health、observability、cleanup helper。
  - 旧 `build_jobs_concurrently()` offline 创建 helper 已退役。
- `src/skillfoundry/offline.py` / `src/skillfoundry/worker.py`
  - 仍保留为显式 CLI/dev fixture compatibility island。
  - 顶层 `skillfoundry` 只保留 `build_offline` / `OfflineWorkerMode` 兼容入口；
    legacy worker/offline internals 必须从 `skillfoundry.worker` 或
    `skillfoundry.offline` 直接导入。
- `src/skillfoundry/context.py`
  - 仍保留为旧 FrontDesk owned-call/context adapter compatibility island。
  - legacy context adapter internals 不再从顶层 `skillfoundry` 导出；维护旧夹具时
    直接从 `skillfoundry.context` 导入。
- `src/skillfoundry/feedback.py` / `src/skillfoundry/qa.py` / `src/skillfoundry/ops.py`
  - 保留为 module-scoped support surfaces。
  - feedback/versioning、deterministic QA、local ops 不再从顶层 `skillfoundry`
    导出；维护旧夹具时直接从对应模块导入。
- `docs/PUBLIC_API.md`
  - 当前 cleanup 阶段的 package-root public API 合同。
  - 新增顶层导出前必须确认属于 current product path 或显式 compatibility entrypoint。
- `src/skillfoundry/forgeunit_adapter.py`
  - `JobWorkspace -> ForgeUnit task pack -> command boundary -> SkillFoundry evidence`
    的适配层。
- `src/skillfoundry/graph_v2.py`
  - 旧 v2 compatibility graph，仍可显式调用，但不再是 FrontDesk build 默认路由。
  - graph v2 state/routes/node builders/compiler/validators 不再从顶层
    `skillfoundry` 导出；维护时从 `skillfoundry.graph_v2` 显式导入。
- `src/skillfoundry/goal_runtime.py`
  - direct Goal Runtime runners/state helpers/result refs 保留为 module-scoped
    runtime/compatibility surface。
  - 顶层 `skillfoundry` 只保留 `seed_goal_harness_context` 作为当前
    ContextForge refs-only evidence helper。
- `src/skillfoundry/final_report.py`
  - 当前 `final_report.json` evidence envelope 的读写和构建逻辑。
  - 已从 legacy `offline.py` 拆出，避免当前 v2/runtime 路径依赖旧离线 builder。
- `scripts/run_forgeunit_skill_factory.py`
  - 本地 vNext CLI smoke，支持 deterministic fake 和显式 command。
- `scripts/run_frontdesk_forgeunit_command_pilot.py`
  - FrontDesk API command-boundary 手动 pilot。
- `scripts/run_frontdesk_live_codex_eval.py`
  - 手动 live Codex semantic eval，不进入默认测试。

## Default Validation

默认验证必须保持 deterministic/offline：

```bash
make focused
make test
```

新用户 fresh clone gate：

```bash
make fresh-clone-smoke
```

Live Codex 只允许显式手动执行：

```bash
make live-semantic-eval-help
```

默认测试、默认本地 smoke、fresh-clone fake-mode semantic smoke 都不应调用 live
Codex，不应依赖本机 sibling `../ForgeUnit`。

## What Works Now

- FrontDesk 可以把模糊需求推进到 approved/frozen job。
- FrontDesk build 默认进入 ForgeUnit SkillFoundry vNext。
- deterministic fake command boundary 可以完成 build / verify / registry happy path。
- repair fake path 已覆盖第一次 verifier fail、第二次 repair pass、registry approve。
- API 和 product read models 只暴露 refs/status summary，不暴露 raw prompt、raw
  conversation、raw transcript、stdout/stderr、worker input 或 package body。
- ForgeUnit 通过 pinned Git tag `v1.2.1` 安装。

## Non-Negotiable Boundaries

- Worker self-report is never acceptance。
- Verifier / acceptance coverage / registry gate 是事实来源。
- 默认路径不得调用 live Codex。
- ContextForge 管边界、上下文视界、cache plan、checkpoint、ledger 和证据；不声称控制
  Codex exec / Codex SDK thread 的内部 prompt、tool loop、compaction 或 cache。
- FrontDesk state 和 API read model 必须 refs-only。
- 没有 approved plan review 不得 freeze。
- Live pilot 证据可以保存在 `.local/` / `.local_registry/` / `runs/`，但这些是本地产物，
  不提交到 git。

## Next Useful Work

1. 继续把产品主路径收敛到 `src/forgeunit_skillfoundry/`。
2. 继续隔离或退役 legacy `worker.py`、`context.py`、`offline.py`
   等旧路径；`src/skillfoundry/graph.py` 已在 Phase 13A 删除，
   `src/skillfoundry/llm_builder.py` 已在 Phase 13B 删除，
   `final_report.py` 已在 Phase 13C 从 `offline.py` 解耦，
   legacy API `POST /jobs` offline 创建入口已在 Phase 13D 退役，
   ops offline concurrent build helper 已在 Phase 13E 退役，
   legacy worker/offline internals 已在 Phase 13F 从顶层 public API 移除，
   legacy context adapter internals 已在 Phase 13G 从顶层 public API 移除，
   Phase 13H 已新增 public API 合同并移除明显内部 fake-worker/result/factory 顶层导出，
   Phase 13I 已把 feedback/QA/ops support surfaces 收口为 module-scoped，
   Phase 13J 已把 direct Goal Runtime 和 graph v2 compatibility helpers 收口为
   module-scoped。
3. 完善 API/UI 对 registry outcome、repair decision、human review 和 refs-only
   evidence 的展示。
4. 用 3-5 个真实 Skill 需求做 opt-in live Codex semantic eval，记录失败分类和修复策略。

## Git Notes

ContextForge 是 submodule：

```bash
git clone --recurse-submodules git@github.com:manstein-lzn/skillfoundry.git
git submodule update --init --recursive
```

本地运行产物不要提交：

```text
.local/
.local_registry/
.metaloop/
.venv/
runs/
__pycache__/
*.egg-info/
package-lock.json
```
