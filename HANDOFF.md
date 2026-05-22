# SkillFoundry Handoff

更新日期：2026-05-22

## 当前状态

当前主线已经从 v0 Front Desk / worker / graph 原型，推进到 ContextForge Goal Harness v2 骨架的混合迁移阶段。

重要更新：SkillFoundry 目前没有线上用户、外部兼容性承诺或生产数据迁移负担。后续可以基于新版 ContextForge Goal Harness 重新设计技术实现；旧 WP0-WP17 代码和文档是 v0 原型与知识资产，不是 v2 技术约束。v2 当前集成蓝图是 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`，阶段实现计划和历史执行证据见 `docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md`，前提说明见 `docs/SKILLFOUNDRY_V2_BASELINE.md`。

核心行为现在是：

```text
Core Need Discovery
  -> Solution Planning
  -> User Review Gate
  -> Deterministic Freeze
  -> Build / Verify / QA / Registry
```

用户不再被无限追问技术细节。Front Desk 会先理解痛点、使用场景、目标用户、期望结果和成功信号；随后由 Agent 生成方案文档，用户确认或要求修改。只有用户批准过的方案才能进入 deterministic freeze。

当前不能说“v2 重构已经完成”。更准确的状态是：

```text
ContextForge contract bridge 已存在。
Offline Goal Harness build path 已存在。
workers_v2 / graph_v2 / verification bridge / registry evidence gate 已存在。
Front Desk v2 Goal Harness slices 已存在。
graph v2 failed verification -> Goal Harness repair -> verifier / acceptance coverage / ContextForge bridge / registry gate 闭环已存在。
产品主路径还需要继续收敛到这套 v2 骨架。
```

## 最近完成的关键改动

- ContextForge 已作为 Git submodule 接入：`third_party/contextforge`。
- `pyproject.toml` 通过 editable path source 使用 `contextforge==0.1.0`，默认 `uv` index 设置为清华源。
- `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 已创建；初版曾由独立 `gpt-5.5 xhigh` reviewer 审查为 `approved_with_residual_risks`、无 blocking findings。当前入口文档 reviewer 记录以该文档末尾和最新 MetaLoop review 为准。
- v2 核心桥接模块已经存在：
  - `src/skillfoundry/contracts.py`
  - `src/skillfoundry/goal_runtime.py`
  - `src/skillfoundry/workers_v2.py`
  - `src/skillfoundry/graph_v2.py`
  - `src/skillfoundry/frontdesk_v2.py`
  - `src/skillfoundry/frontdesk_goal_runtime.py`
  - `src/skillfoundry/verification_bridge.py`
- Front Desk schema 增加：
  - `CoreNeedBrief`
  - `CoreNeedDiscoveryReport`
  - `CoreNeedQuestion`
  - `SolutionPlan`
  - `PlanReviewRecord`
  - `FrontDeskState.frontdesk_phase`
  - `FrontDeskState.core_need_brief_ref`
  - `FrontDeskState.solution_plan_ref`
  - `FrontDeskState.latest_plan_review_ref`
  - `FrontDeskState.core_need_round`
  - `FrontDeskState.plan_revision_count`
- `FrontDeskLoop` 在 `ready_for_audit` 后先生成：
  - `frontdesk/core_need_brief.json`
  - `frontdesk/core_need_report_*.json`
  - `frontdesk/decision_ledger.json`
  - `frontdesk/solution_plan.json`
  - `frontdesk/solution_plan.md`
  - `frontdesk/draft_skill_spec.yaml`
  - `frontdesk/acceptance_criteria.yaml`
- `POST /frontdesk/jobs/<id>/plan-review` 支持：
  - `approve`
  - `request_revision`
  - `reject`
  - `human_review`
- `request_revision` 会写入新的 user turn，并触发下一轮方案修订；超过 `max_plan_revision_rounds` 会持久化为 `human_review_required`。
- `FrontDeskFreezeGate` 现在要求 approved plan review 和 source hash 匹配，否则不能 freeze。
- Freeze manifest hash 现在覆盖 risk/budget/plan review 证据：
  - `frontdesk/budget.json`
  - `frontdesk/risk_report.json`
  - `frontdesk/core_need_brief.json`
  - `frontdesk/solution_plan.json`
  - `frontdesk/solution_plan.md`
  - `frontdesk/plan_review_*.json`
- Manual-only acceptance 不再只靠 `manual_authority`，必须有 `qa/manual_acceptance_record.json`；Registry 会复验该 artifact 的 hash、decision 和 covered criterion ids。
- Server-rendered HTML 的 Front Desk submit script 现在序列化完整 `FormData`，plan-review UI 在启用 JS 时也能提交 `decision` / `reason`。

## 关键代码入口

- `src/skillfoundry/frontdesk_schema.py`
  - Front Desk schema、状态字段、阶段/动作枚举。
- `src/skillfoundry/frontdesk_loop.py`
  - 需求澄清主循环。
  - 核心需求和方案文档物化。
  - 用户批准后 audit/freeze。
- `src/skillfoundry/frontdesk.py`
  - `RequirementsElicitor`
  - `SpecAuditor`
  - `FrontDeskFreezeGate`
  - no-freeze-without-approved-plan、risk/privacy/budget gate。
- `src/skillfoundry/api.py`
  - `/frontdesk/jobs`
  - `/frontdesk/jobs/<id>/messages`
  - `/frontdesk/jobs/<id>/plan-review`
  - `/frontdesk/jobs/<id>/core-need`
  - `/frontdesk/jobs/<id>/solution-plan`
  - server-rendered HTML UI。
- `src/skillfoundry/acceptance.py`
  - acceptance coverage 和 manual-only artifact gate。
- `src/skillfoundry/registry.py`
  - Registry provenance gate 和 manual acceptance record revalidation。
- `src/skillfoundry/contracts.py`
  - SkillFoundry frozen artifacts 到 ContextForge contracts 的 bridge。
- `src/skillfoundry/goal_runtime.py`
  - Offline Goal Harness build runtime。
  - Goal Harness repair evidence runtime。
- `src/skillfoundry/workers_v2.py`
  - Fake / owned LLM / Codex thread boundary / external agent worker。
- `src/skillfoundry/graph_v2.py`
  - refs-only LangGraph v2 spine。
  - verified build/registry happy path 和 failed verification repair re-verification/registry loop。
- `src/skillfoundry/frontdesk_goal_runtime.py`
  - Core Need、Solution Planner、Spec Auditor 的 Goal Harness runtime slices。
- `src/skillfoundry/verification_bridge.py`
  - SkillFoundry verifier / acceptance coverage 到 ContextForge VerificationResult 的桥接。

## 关键文档

- `README.md`
  - 项目入口、开发环境、submodule 初始化方式。
- `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`
  - v2 当前集成蓝图：解释 ContextForge / LangGraph / worker / verifier / registry 边界，列出 Phase 0-9 迁移计划和验收门。
- `docs/SKILLFOUNDRY_V2_BASELINE.md`
  - v2 重建基线：保留 SkillFoundry agent 协作思想，围绕新版 ContextForge Goal Harness 重建技术骨架。
- `docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md`
  - v2 阶段实现计划和历史执行证据，已合入第三方 `gpt-5.5 xhigh` reviewer 审查意见。
- `docs/CONTEXTFORGE_AGENT_EXOSKELETON_PRODUCT_VISION.md`
  - SkillFoundry 作为 ContextForge Agent Exoskeleton Runtime 第一个产品化应用的长期愿景。
- `docs/DEVELOPMENT_ROADMAP.md`
  - v0/WP0-WP17 能力基线和产品经验输入；不再约束 v2 模块边界。
- `docs/FRONT_DESK_CORE_NEED_REFACTOR.md`
  - Front Desk 需求澄清层重构路线和当前落地状态。
- `docs/FRONT_DESK_ROADMAP_AUDIT.md`
  - 历史独立审核，说明 WP15/WP16/风险门背景。

## 验证结果

代码实现切片需要继续使用全量验证：

```bash
uv run --extra test pytest -q
```

若本机未安装 `uv`，但 checkout 已经包含可用 `.venv`，可用等价本地验证：

```bash
.venv/bin/python -m pytest -q
```

当前 MetaLoop 状态请以本地命令为准：

```bash
python3 /home/mansteinl/.codex/skills/metaloop/scripts/metaloop_kernel.py --workspace . status
```

`docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 的初版独立 reviewer 结论是 `approved_with_residual_risks`、无 blocker；后续入口文档复审记录以该文档末尾和最新 MetaLoop review 为准。代码切片仍需按对应 focused tests 和全量测试重新验证。

## 接手后建议先做

1. 确认本地依赖和 submodule：

```bash
git submodule update --init --recursive
uv run --extra test pytest -q
```

没有 `uv` 时可先用：

```bash
.venv/bin/python -m pytest -q
```

2. 若要继续 v2 重建，先读 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`。当前默认 Front Desk frozen job 已能通过 API build endpoint 进入 graph v2 verified build / verify / acceptance coverage / registry happy path：

- `POST /frontdesk/jobs/{job_id}/build` 只接受 approved/frozen Front Desk jobs。
- endpoint 通过 `graph_v2.py` 调用 verified Goal Harness build、SkillFoundry verifier、acceptance coverage、ContextForge verification bridge 和 registry gate。
- failed verification route 可以进入 Goal Harness-backed repair node，记录 governed verifier-failure context、WorkerRun、ContextView、PromptCachePlan、checkpoint、repair instructions、repair runtime result 和 `RepairAttempt`；repair 后会重新进入 SkillFoundry verifier、acceptance coverage、ContextForge verification bridge 和 registry gate。repair worker self-report 仍不是验收或注册依据。
- graph v2 final state 持久化到 `contextforge/graph_v2_state.json`，仍是 refs/IDs/status-only。
- `GET /jobs/{job_id}/contextforge` 会暴露 build path、verified runtime、graph v2 state、repair evidence、human-review、verification 和 registry summary，不暴露 raw prompt / raw payload / raw conversation / transcript / package content。
- 相关 focused gates：`tests/test_frontdesk_api.py tests/test_api.py tests/test_graph_v2_runtime.py tests/test_graph_v2.py tests/test_goal_harness_verified_runtime.py tests/test_verification_bridge.py tests/test_registry.py tests/test_acceptance_coverage.py` 和全量 pytest。

3. 后续继续 Phase 4/5/7：

- 让 `graph_v2.py` 成为唯一产品 build / verify / repair / registry 主骨架，旧 `graph.py` 退役或隔离为 compatibility wrapper。
- 当前最具体的下一片是把旧 `POST /jobs` 离线 builder 改成显式 opt-in compatibility route，并从默认 UI 产品入口隐藏；canonical build route 应保持为 `/frontdesk/jobs/{job_id}/build`。
- 继续完善 API/UI 的 registry outcome、repair/human-review route 和 evidence 摘要。
- 隔离或退役 legacy prompt/context/worker 路径，把 v2 contract/graph/runtime 设为默认贡献入口。
- 真实 provider / Codex SDK thread 只做 opt-in pilot，不进入默认测试。

4. 不要回退以下约束：

- `FrontDeskState` 必须 refs-only，不保存 raw conversation、raw prompt、raw model output。
- Builder 不得读取 raw Front Desk conversation。
- 没有 approved plan review 不得 freeze。
- risk/privacy/budget/manual acceptance 证据必须进入 deterministic gate 或 Registry gate。
- 默认测试路径必须保持 fake/scripted/offline，不依赖 live provider。
- Worker self-report is never acceptance。
- ContextForge 不控制 Codex SDK thread 内部 prompt/cache/tool loop，只记录边界证据。

## Git 注意事项

当前变更包含 submodule：

```text
.gitmodules
third_party/contextforge
```

克隆或切换机器时请使用：

```bash
git clone --recurse-submodules <repo>
```

或者在已有 checkout 中运行：

```bash
git submodule update --init --recursive
```
