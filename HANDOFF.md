# SkillFoundry Handoff

更新日期：2026-05-21

## 当前状态

当前主线已经完成 Front Desk core-need clarification refactor，并通过 MetaLoop 验证和独立 reviewer 审查。

核心行为现在是：

```text
Core Need Discovery
  -> Solution Planning
  -> User Review Gate
  -> Deterministic Freeze
  -> Build / Verify / QA / Registry
```

用户不再被无限追问技术细节。Front Desk 会先理解痛点、使用场景、目标用户、期望结果和成功信号；随后由 Agent 生成方案文档，用户确认或要求修改。只有用户批准过的方案才能进入 deterministic freeze。

## 最近完成的关键改动

- ContextForge 已作为 Git submodule 接入：`third_party/contextforge`。
- `pyproject.toml` 通过 editable path source 使用 `contextforge==0.1.0`，默认 `uv` index 设置为清华源。
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

## 关键文档

- `README.md`
  - 项目入口、开发环境、submodule 初始化方式。
- `docs/DEVELOPMENT_ROADMAP.md`
  - 当前权威路线图。
- `docs/FRONT_DESK_CORE_NEED_REFACTOR.md`
  - Front Desk 需求澄清层重构路线和当前落地状态。
- `docs/FRONT_DESK_ROADMAP_AUDIT.md`
  - 历史独立审核，说明 WP15/WP16/风险门背景。

## 验证结果

最后一次全量验证：

```bash
uv run --extra test pytest -q
```

结果：

```text
290 passed
```

MetaLoop 状态：

```text
verification: completed_verified
review: approved
```

独立 reviewer 结论：approved，无 blocker。

## 接手后建议先做

1. 确认本地依赖和 submodule：

```bash
git submodule update --init --recursive
uv run --extra test pytest -q
```

2. 若要继续 Phase A，优先做：

- 更强的 conversation summary / redaction / retention。
- 真正聚合 live provider usage/token/cost，而不是只记录 usage unavailable reason。
- 用 Playwright 或等价浏览器测试覆盖 Front Desk HTML plan-review 提交流程。
- 让 `SpecAuditor` 更明确审查 `solution_plan.json` / `solution_plan.md`，而不是主要审查旧 draft spec。
- 增加 3-5 个内部真实需求样例，记录澄清轮数、方案修改次数、冻结成功率和失败分类。

3. 不要回退以下约束：

- `FrontDeskState` 必须 refs-only，不保存 raw conversation、raw prompt、raw model output。
- Builder 不得读取 raw Front Desk conversation。
- 没有 approved plan review 不得 freeze。
- risk/privacy/budget/manual acceptance 证据必须进入 deterministic gate 或 Registry gate。
- 默认测试路径必须保持 fake/scripted/offline，不依赖 live provider。

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
