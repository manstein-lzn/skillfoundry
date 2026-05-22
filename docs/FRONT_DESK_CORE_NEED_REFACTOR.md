# Front Desk Core Need Refactor Roadmap

版本：v0.1
日期：2026-05-21
适用范围：SkillFoundry Phase A Front Desk 重构

## 0. 当前落地状态

截至 2026-05-21，本路线的可执行骨架已经进入代码：

- `FrontDeskState` 已显式记录 `frontdesk_phase`、`core_need_brief_ref`、`solution_plan_ref`、`latest_plan_review_ref`、`core_need_round` 和 `plan_revision_count`。
- `FrontDeskLoop` 在 `ready_for_audit` 后先物化 `frontdesk/core_need_brief.json`、`frontdesk/core_need_report_*.json`、`frontdesk/solution_plan.json` 和 `frontdesk/solution_plan.md`，并停在 `awaiting_plan_review`。
- `POST /frontdesk/jobs/<job_id>/plan-review` 记录 `frontdesk/plan_review_*.json`；只有 `approve` 后才会进入 audit 和 deterministic freeze。
- `FrontDeskFreezeGate` 已把 solution plan、plan review hash、risk/privacy/budget report 和 acceptance criteria 纳入确定性 gate。
- manual-only acceptance 已要求 `qa/manual_acceptance_record.json`，Registry 会校验该 artifact 的 hash 和覆盖项。
- 测试覆盖：`uv run --extra test pytest -q`；若本机未安装 `uv` 但已有 `.venv`，可用 `.venv/bin/python -m pytest -q`。当前结果 `421 passed`。

剩余产品化工作主要集中在：更强的长对话摘要/脱敏治理、独立 Planner/Auditor 对 solution plan 的深度审查，以及更完整的前端体验。

## 1. 一句话结论

Front Desk 已经有 `RequirementsElicitor`、`SpecAuditor`、`FrontDeskFreezeGate`、`FrontDeskLoop`、API 和 HTML 入口。原始机制偏向“继续补字段直到 ready_for_audit”；本路线把它重构成有限轮数内强制收敛的产品入口：

```text
用户模糊表达
  -> Core Need Discovery: 先理解痛点和真正问题
  -> Solution Planning: Agent 站在用户立场设计可执行方案
  -> User Review Gate: 用户审查规划文档并纠偏
  -> Deterministic Freeze: 冻结 spec / acceptance / verification / worker input
  -> Build / Verify / QA / Registry
```

核心改变：

- Front Desk 不再以“字段完整”为主要目标，而是以“能否定义一个值得构建的 v1 方案”为目标。
- Stage 1 不问技术细节，只确认痛点、场景、期望结果和成功信号。
- Stage 2 由 Agent 自己做技术设计，不把技术路线选择丢给用户。
- Stage 3 让用户审查规划文档，用户只确认问题理解和方案方向。
- FreezeGate 只允许在规划文档被用户确认或明确进入人工审核后继续，禁止无限澄清。

## 2. 当前实现基线

相关模块：

```text
src/skillfoundry/frontdesk_schema.py
  ConversationTurn
  ElicitationReport
  SpecAuditReport
  FeasibilityReport
  AcceptanceCriteriaSet
  FreezeManifest
  FrontDeskState
  FrontDeskConfig

src/skillfoundry/frontdesk_workspace.py
  frontdesk/conversation.jsonl
  frontdesk/clarification_summary.md
  frontdesk/budget.json
  frontdesk/risk_report.json
  frontdesk artifact manifest upsert

src/skillfoundry/frontdesk.py
  RequirementsElicitor
  SpecAuditor
  FrontDeskFreezeGate

src/skillfoundry/frontdesk_loop.py
  FrontDeskLoop.run_round()
  ask_user / audit / freeze / human_review / reject routing

src/skillfoundry/api.py
  POST /frontdesk/jobs
  POST /frontdesk/jobs/<job_id>/messages
  POST /frontdesk/jobs/<job_id>/retry
  GET /frontdesk/jobs/<job_id>
  server-rendered Front Desk HTML
```

当前问题：

- `FrontDeskConfig.max_clarification_rounds` 默认是 10，系统允许较长时间停留在普通澄清状态。
- `ElicitationReport` 同时承载问题澄清、draft skill spec 和 draft acceptance criteria，容易让早期对话过早进入技术规格。
- `FrontDeskState` 只有 `readiness` 和 `next_action`，没有显式区分核心需求发现、方案设计、用户审查和冻结。
- `RequirementsElicitor` 的 prompt 虽然已经强调 product discovery，但输出契约仍围绕 `readiness_guess` 和 `missing_fields`，没有硬性的 `CoreNeedBrief` 退出门。
- `SpecAuditor` 目前审查 draft spec，而不是审查“用户确认过的规划文档”。
- 到达轮数上限时当前逻辑进入 human review；缺少 `freeze_with_assumptions` 或 `plan_for_user_review` 这种强制收敛路径。

## 3. 目标行为

用户体验应该像：

```text
用户：我遇到一个问题。
Front Desk：我先帮你搞清楚真正要解决的痛点。
Front Desk：我理解你的核心需求是 X。我建议先做 v1 方案 Y。
Front Desk：这是完整规划文档，请确认是否解决你的问题。
用户：这里改一下。
Front Desk：已修订。确认后进入实现。
用户：可以执行。
SkillFoundry：冻结规格，启动 builder。
```

Front Desk 不应该像：

```text
请提供输入格式。
请提供输出格式。
请提供触发条件。
请提供路径。
请提供更多细节。
...
```

## 4. 新阶段模型

### 4.1 Stage 1：Core Need Discovery

目标：搞清楚用户真正痛点，不做技术设计。

必须回答：

```text
pain: 用户现在什么事情痛苦或低效
user: 谁会使用这个 Skill
moment: 用户会在什么时候使用它
desired_outcome: 用完后希望得到什么结果
success_signal: 什么表现说明它真的有用
```

允许 Agent 推断但必须记录：

```text
assumptions: 可以安全假设的事项
non_goals: v1 明确不做的事项
risks: 会影响方案方向或安全边界的问题
```

禁止事项：

- 不问本地路径、文件格式、API、RAG、脚本、模型、Agent 数量等技术细节，除非它是安全硬门。
- 不要求用户替系统选择技术路线。
- 不因非阻塞信息缺失继续追问。

退出条件：

```text
能用一句话写清楚：
为谁，在什么场景下，解决什么痛点，交付什么结果。
```

建议轮数：

```text
max_core_need_rounds = 3
max_questions_per_round = 1
```

到达上限后只能：

```text
core_need_ready
human_review_required
reject_or_infeasible
```

不能继续普通追问。

### 4.2 Stage 2：Solution Planning

目标：Agent 站在用户立场，把核心需求转化成可执行方案。

输入：

```text
frontdesk/core_need_brief.json
frontdesk/core_need_summary.md
frontdesk/decision_ledger.json
registry summary, optional
SkillFoundry capability boundary
```

输出：

```text
frontdesk/solution_plan.md
frontdesk/solution_plan.json
frontdesk/draft_skill_spec.yaml
frontdesk/acceptance_criteria.yaml
frontdesk/verification_spec.yaml
frontdesk/worker_input.md
```

规划文档必须包括：

```text
1. 我理解的核心问题
2. 推荐 v1 方案
3. 用户将如何使用
4. 输入和输出
5. 系统默认假设
6. 不做什么
7. 权限和安全边界
8. 验收标准
9. 技术实现路线
10. 需要用户确认的问题
```

技术路线由 Agent 决定：

```text
prompt_only
rag
script_required
owned_llm_builder
codex_external_builder
human_review
```

用户只需要确认“这个方案是否解决我的问题”，不需要审查每个技术字段。

### 4.3 Stage 3：User Review Gate

目标：用户审查规划文档并提出修改，直到认为可以执行。

状态：

```text
awaiting_plan_review
plan_revision_requested
plan_approved
human_review_required
```

规则：

- 用户可以要求修改方案，Planner 只修订 `solution_plan` 和 draft artifacts。
- 不回到无限需求澄清，除非用户否认核心痛点理解。
- 最多允许 2-3 次 plan revision。
- 用户确认后才进入 deterministic freeze。

### 4.4 Stage 4：Deterministic Freeze

目标：把用户确认的方案冻结为 builder 可读输入。

冻结输入：

```text
core_need_brief.json
solution_plan.md
solution_plan.json
draft_skill_spec.yaml
acceptance_criteria.yaml
verification_spec.yaml
worker_input.md
build_contract.yaml
risk_report.json
budget.json
```

冻结输出：

```text
skill_spec.yaml
acceptance_criteria.yaml
verification_spec.yaml
worker_input.md
build_contract.yaml
frontdesk/freeze_manifest.json
frontdesk/freeze_gate_result.json
```

FreezeGate 必须拒绝：

- 没有 `core_need_brief`；
- 没有用户确认过的 `solution_plan`；
- must acceptance criteria 为空；
- 权限、安全、数据敏感度不明确；
- usage/cost/budget 超限；
- raw conversation 被声明为 builder 输入；
- 用户仍处于 `plan_revision_requested`。

## 5. Schema 重构计划

### WP-A1：新增 Core Need schemas

在 `frontdesk_schema.py` 增加：

```text
CoreNeedBrief
  problem_statement
  target_user
  usage_moment
  desired_outcome
  success_signal
  current_workaround
  non_goals
  assumptions
  risk_flags
  confidence_score
  source_turn_ids

CoreNeedQuestion
  question_id
  text
  reason
  priority
  answer_type
  options
  blocks_core_need

CoreNeedDiscoveryReport
  readiness: needs_core_need_input | core_need_ready | human_review_required | rejected
  current_understanding
  core_need_brief
  next_questions
  decision_ledger_ref
  summary_ref
```

保留 `ElicitationReport` 兼容旧测试，但新 loop 不再把它作为 Stage 1 主产物。过渡期可以由 `CoreNeedDiscoveryReport` 生成兼容的 `ElicitationReport`。

### WP-A2：新增 Solution Planning schemas

在 `frontdesk_schema.py` 增加：

```text
SolutionPlan
  plan_id
  core_need_ref
  recommended_solution
  user_workflow
  inputs
  outputs
  assumptions
  non_goals
  permissions
  safety_boundaries
  acceptance_summary
  technical_route
  implementation_steps
  open_confirmation_items
  status: draft | awaiting_user_review | revision_requested | approved

PlanReviewRecord
  review_id
  reviewer_role
  decision: approve | request_revision | reject | human_review
  comment
  source_turn_id
  reviewed_plan_ref
  reviewed_plan_hash
```

`SolutionPlan` 必须能渲染成 `frontdesk/solution_plan.md`，同时写机器可读 `frontdesk/solution_plan.json`。

### WP-A3：扩展 FrontDeskState

在 `FrontDeskState` 增加 refs-only 字段：

```text
frontdesk_phase:
  core_need_discovery | solution_planning | user_review | freeze | complete | failed

latest_core_need_report_ref
core_need_brief_ref
decision_ledger_ref
solution_plan_ref
solution_plan_markdown_ref
latest_plan_review_ref
plan_revision_count
core_need_round
```

扩展 `FRONTDESK_STAGES` / `FRONTDESK_READINESS` / `FRONTDESK_NEXT_ACTIONS`：

```text
discover_core_need
plan_solution
await_user_plan_review
revise_plan
freeze_approved_plan

needs_core_need_input
core_need_ready
plan_draft_ready
awaiting_plan_review
plan_revision_requested
plan_approved
```

状态仍然禁止保存 raw conversation、prompt 和 model output。

### WP-A4：拆分 Config budgets

把单一 `max_clarification_rounds = 10` 替换或降级为：

```text
max_core_need_rounds = 3
max_plan_revision_rounds = 3
max_questions_per_core_need_round = 1
max_open_confirmation_items = 3
max_total_frontdesk_rounds = 8
```

保留旧字段用于兼容，但新 loop 不再用它驱动普通追问。

## 6. Agent 和 Loop 重构计划

### WP-A5：CoreNeedDiscoverer

实现位置：

```text
src/skillfoundry/frontdesk.py
```

可选方式：

- 新增 `CoreNeedDiscoverer`；
- 或先让 `RequirementsElicitor` 增加 `discover_core_need()`，保留 `elicit()` 兼容旧路径。

职责：

- 只做痛点、场景、结果、成功信号发现；
- 每轮最多一个高价值问题；
- 优先给候选方向让用户选择；
- 输出 `CoreNeedDiscoveryReport`；
- 写 `core_need_brief.json` 和 `core_need_summary.md`。

失败策略：

- 模型输出不可解析：可 retry parse repair；
- 没有减少 blocking unknown：下一轮必须换成候选方案选择题；
- 达到 `max_core_need_rounds`：不能继续问，进入 `core_need_ready_with_assumptions` 或 human review。

### WP-A6：SolutionPlanner

实现位置：

```text
src/skillfoundry/frontdesk.py
```

新增 `SolutionPlanner` owned LLM call，通过 ContextForge 记录。

职责：

- 根据 `CoreNeedBrief` 设计完整方案；
- 自主决定技术路线；
- 生成用户可读规划文档；
- 生成 draft SkillSpec、AcceptanceCriteria、VerificationSpec、WorkerInput；
- 明确 assumptions、non-goals、permissions、安全边界。

输出必须落盘，不能只存在模型响应里。

### WP-A7：SpecAuditor 改为审查方案

当前 `SpecAuditor` 审查 draft spec。重构后它审查：

```text
core_need_brief.json
solution_plan.json
draft_skill_spec.yaml
acceptance_criteria.yaml
verification_spec.yaml
```

审查重点：

- 方案是否解决核心痛点；
- 技术路线是否在 SkillFoundry 能力边界内；
- assumptions 是否可接受；
- acceptance criteria 是否能验证；
- 权限和安全边界是否足够；
- 是否应该进入 human review。

Auditor 仍然不能 freeze，只能提供 evidence。

### WP-A8：FrontDeskLoop v2

重构 `frontdesk_loop.py`，把当前一轮式流程：

```text
elicit -> maybe audit -> freeze/ask_user
```

改成阶段式路由：

```text
discover_core_need
  -> ask_user_core_need
  -> plan_solution
  -> audit_plan
  -> await_user_plan_review
  -> revise_plan
  -> freeze_approved_plan
```

关键 routing policy：

```text
if phase == core_need_discovery:
    if blocking_core_need_unknowns and core_need_round < max_core_need_rounds:
        ask_user_core_need
    elif safe_assumptions_exist:
        plan_solution
    else:
        human_review

if phase == solution_planning:
    write plan and draft artifacts
    audit_plan
    await_user_plan_review

if phase == user_review:
    if user_approves:
        freeze_approved_plan
    elif revision_count < max_plan_revision_rounds:
        revise_plan
    else:
        human_review
```

Loop result 继续 refs-only。

## 7. API / UI 重构计划

### WP-A9：API payload 增加阶段信息

扩展 `SkillFoundryAPI._frontdesk_payload()`：

```json
{
  "phase": "core_need_discovery",
  "core_need_brief": {},
  "solution_plan": {},
  "solution_plan_markdown_ref": "frontdesk/solution_plan.md",
  "review_actions": ["approve", "request_revision", "reject"],
  "next_questions": []
}
```

新增或扩展 route：

```text
GET /frontdesk/jobs/<id>/core-need
GET /frontdesk/jobs/<id>/solution-plan
POST /frontdesk/jobs/<id>/plan-review
GET /frontdesk/jobs/<id>/frozen-spec
```

可以先复用 `POST /frontdesk/jobs/<id>/messages`，但 payload 需要支持：

```json
{
  "message": "...",
  "review_decision": "approve | request_revision | reject"
}
```

### WP-A10：HTML 体验调整

当前 UI 有对话区、问题、理解、artifact refs。重构后第一屏应该围绕：

```text
当前阶段
我理解的核心问题
推荐方案/规划文档
需要你确认的一件事
批准 / 请求修改 / 进入人工审核
```

不要把 schema 字段、artifact refs、技术路线作为主要 UI。artifact refs 放在折叠的 operator/debug 区。

## 8. Workspace Artifact 计划

新增 Front Desk artifacts：

```text
runs/<job_id>/frontdesk/
  core_need_report_001.json
  core_need_brief.json
  core_need_summary.md
  decision_ledger.json
  solution_plan.json
  solution_plan.md
  plan_review_001.json
  plan_audit_report_001.json
  freeze_gate_result.json
  freeze_manifest.json
```

继续保留：

```text
conversation.jsonl
budget.json
risk_report.json
draft_skill_spec.yaml
acceptance_criteria.yaml
feasibility_report.json
spec_audit_report_001.json
```

Builder 输入必须只读取 frozen root inputs，不读取：

```text
frontdesk/conversation.jsonl
raw model output
raw prompt
transcript
```

## 9. 测试计划

新增测试文件：

```text
tests/test_frontdesk_core_need.py
tests/test_frontdesk_solution_planner.py
tests/test_frontdesk_review_gate.py
tests/test_frontdesk_loop_v2.py
```

必须覆盖：

- 模糊需求第一轮只问痛点/场景问题，不问路径或格式。
- 用户给出足够痛点后进入 `solution_planning`，不继续普通追问。
- 达到 3 轮 core need 上限时不会第 4 次普通追问。
- Agent 可以在 assumptions 下产出 v1 方案。
- 用户 request revision 后只修订方案，不丢失 core need brief。
- 用户 approve 后 FreezeGate 才能冻结。
- 没有 solution plan approval 时 FreezeGate 拒绝。
- raw conversation 不进入 `worker_input.md`。
- API payload 暴露 phase、core need、solution plan、review actions。
- 旧 `ElicitationReport` 路径在过渡期仍能通过现有测试。

验收命令：

```bash
uv run --extra test pytest -q
# fallback when uv is unavailable but the local venv is provisioned:
.venv/bin/python -m pytest -q
```

## 10. 迁移顺序

### Step 1：文档和 schema

- 增加 CoreNeed 和 SolutionPlan schema；
- 扩展 FrontDeskState / Config；
- 添加 schema 单测；
- 不改现有 API 行为。

### Step 2：Core Need Discovery

- 新增 `CoreNeedDiscoverer` 或 `RequirementsElicitor.discover_core_need()`；
- 写 artifacts；
- 增加 fake/scripted clients；
- 默认测试不调用 live provider。

### Step 3：Solution Planner

- 新增 `SolutionPlanner`；
- 生成 `solution_plan.md/json` 和 draft artifacts；
- 增加 planner 单测。

### Step 4：Loop v2

- 在 `FrontDeskLoop` 中引入 phase router；
- 保留旧 `run_round()` 兼容入口，内部切到 v2 或通过 config flag 控制；
- 增加有限轮数强制收敛测试。

### Step 5：API/UI

- API payload 增加 phase、core need、solution plan、review actions；
- HTML 主视图从 artifact/debug 转为用户审查体验；
- 增加 `plan-review` route 或复用 message route。

### Step 6：FreezeGate 硬化

- FreezeGate 校验 `solution_plan approved`；
- freeze manifest 记录 core need、solution plan、plan review hash；
- 明确拒绝 raw conversation builder input。

### Step 7：真实样例回归

至少用 5 个需求跑通：

```text
pytest 失败日志分析 Skill
代码库结构理解 Skill
周报草稿生成 Skill
文档审核 Skill
API 响应诊断 Skill
```

每个样例记录：

```text
core_need_rounds
plan_revision_count
final_decision
是否进入 build
用户是否认为方案解决核心问题
```

## 11. 成功标准

Phase A 的 Front Desk 重构完成必须满足：

- 80% 的内部样例在 3 轮以内得到 `CoreNeedBrief`。
- 系统不会因为非阻塞字段缺失继续普通追问。
- 每个进入构建的 job 都有用户确认过的 `solution_plan.md`。
- 用户可以看懂规划文档并提出修改。
- FreezeGate 不能在缺少 core need、solution plan 或 plan approval 时冻结。
- Builder 只能读取 frozen inputs。
- 全量离线测试稳定通过。

## 12. 非目标

本重构不做：

- 多租户权限；
- 复杂前端框架；
- 生产级队列；
- 通用咨询机器人；
- 让用户填写完整技术规格；
- 让 CodexWorker 接管需求澄清；
- 让 LLM Auditor 单独决定 freeze。

## 13. 对现有 roadmap 的影响

本文替代 `docs/DEVELOPMENT_ROADMAP.md` 中 Phase A 的具体执行细节，但不改变 Phase B-E 的顺序。

新的 Phase A 定义为：

```text
Phase A = Core Need Discovery + Solution Planning + User Review Gate + Deterministic Freeze
```

完成后再进入：

```text
Phase B = frozen spec -> controlled builder -> verifier -> QA -> acceptance coverage -> registry
```
