# SkillFoundry x ContextForge Agent 工作外骨骼产品愿景

最后更新：2026-05-22

## 文档用途

本文是 SkillFoundry 在 ContextForge Goal Harness 完成之后的下一代产品愿景文档。

它不替代当前短期执行源：

- `HANDOFF.md`
- `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`
- `docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md`

当前状态说明：ContextForge Goal Harness MVP 已经在 `third_party/contextforge` 中存在，SkillFoundry 也已经落地一批 Goal Harness bridge/slice。本文仍作为长期愿景使用；具体 phase 编号、当前下一步和实现状态以 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 为准。

它的作用是固定一个长期架构判断：ContextForge 不应该只是 SkillFoundry 的附属上下文模块，而应该演进为强 agent 的工作外骨骼；SkillFoundry 则应该成为这套外骨骼的第一个真实产品验证场。

后续工程决策可以用本文回答三个问题：

- ContextForge 重构应该服务什么产品目标；
- SkillFoundry 为什么要等待并接入 ContextForge Goal Harness；
- Codex SDK thread / GPT-5.5、LangGraph、Verifier、Ledger、PromptCachePlan 各自应该站在哪个边界上。

## 一句话结论

SkillFoundry 后续不应该只是一条 Codex Skill 构建流水线，而应该成为 ContextForge Goal Harness 完成后的第一个真实产品验证场。

新的总体判断：

```text
ContextForge = agent 工作外骨骼
LangGraph = 多阶段骨架
Codex SDK thread / GPT-5.5 = 肌肉和智能
Verifier = 免疫系统
Ledger / Replay / Checkpoint = 神经记录
PromptCachePlan = 成本控制器
SkillFoundry = 第一座工厂和第一个产品化场景
```

这意味着：

```text
不要重做完整 Codex。
不要依赖纯黑盒 Codex。
做一个 Goal Harness。
让强模型在 harness 里自由工作。
ContextForge 管边界、上下文视界、缓存、checkpoint 和证据。
LangGraph 管大阶段。
Verifier 管真伪。
SkillFoundry 用这套能力交付第一个真实产品：高质量 Codex Skill 工厂。
```

## 背景

当前 SkillFoundry 已经完成一条离线可验证的 Codex Skill 工厂主线，并具备 Front Desk、需求澄清、Spec Auditor、FreezeGate、Builder、Verifier、QA Lab、Registry 等模块。

但当前架构中的 ContextForge 主要承担的是：

- SkillFoundry 自有 LLM 调用的 PromptView / PromptBlock 管理；
- 工具输出治理；
- memory 显式注入；
- replay 和 telemetry；
- 对 Codex Worker 只记录边界证据。

这套边界是对的，但它还不是最终形态。

随着 GPT-5.5 / Codex SDK thread 这类强 agent 的能力变强，SkillFoundry 不应该把强模型拆成过细的传统多 agent 流水线，也不应该把复杂任务完全交给黑盒 agent。更合理的方向是：把强 agent 纳入一个可控、可审计、可复用、可缓存、可验证的工作外骨骼。

ContextForge 要成为这个外骨骼。SkillFoundry 要成为这个外骨骼的第一个产品。

## 核心隐喻

### ContextForge = agent 工作外骨骼

ContextForge 不负责替强模型思考，也不负责替 Codex 写代码。

它负责把强模型放进一个可控工程边界里：

- 目标是什么；
- 能看什么；
- 不能看什么；
- 能用什么工具；
- 能写哪里；
- prompt 如何编译；
- prompt cache 如何保持稳定；
- 工具输出如何治理；
- 长任务如何 checkpoint；
- 证据如何记录；
- 失败如何分类；
- 验收如何独立完成；
- 多 agent 之间如何 handoff。

它是强 agent 的外骨骼，不是强 agent 的大脑。

### LangGraph = 多阶段骨架

LangGraph 不应该管理强 agent 的每一次思考。

它应该管理大阶段：

- intake；
- clarification；
- planning；
- build；
- repair；
- verification；
- review；
- registry；
- feedback；
- versioning。

LangGraph 负责阶段流转、分支、重试、人工门和 workflow checkpoint。

每个 LangGraph node 内部，可以是一个由 ContextForge Goal Harness 管住的强 agent worker。

### Codex SDK thread / GPT-5.5 = 肌肉和智能

强模型和 Codex SDK thread 是真正执行复杂任务的智能体。

它们可以：

- 理解需求；
- 分析代码；
- 调用工具；
- 修改文件；
- 跑测试；
- 解释失败；
- 生成修复；
- 进行长时间复杂工作。

但它们不应该拥有最终验收权。

它们在 SkillFoundry 中的定位是 worker，而不是平台事实源。

### Verifier = 免疫系统

Verifier 不负责生成。

Verifier 负责判断：

- 产物是否满足 frozen spec；
- acceptance criteria 是否覆盖；
- 测试是否通过；
- artifact hash 是否匹配；
- forbidden path 是否被触碰；
- forbidden claim 是否出现；
- schema 是否有效；
- review gate 是否需要独立审查；
- 是否需要 human authority。

Verifier 是系统免疫边界。builder self-report 不是验收证据。

### Ledger / Replay / Checkpoint = 神经记录

长任务不能只靠 chat history。

系统必须记录：

- 输入目标；
- 上下文视界；
- prompt blocks；
- model calls；
- tool calls；
- raw artifacts；
- governed outputs；
- checkpoints；
- decisions；
- failures；
- repairs；
- verification results；
- registry events。

这些记录让系统可恢复、可复盘、可迁移、可审计。

### PromptCachePlan = 成本控制器

强模型长任务会产生大量 API 调用。

如果每次都重排 prompt，缓存命中率会很差。

如果无限 append history，prompt 会膨胀，质量和成本都会失控。

PromptCachePlan 的职责是：

- 稳定 prefix；
- 动态 suffix；
- cache epoch；
- cache break reason；
- provider payload hash；
- expected cacheable tokens；
- actual cached tokens；
- prefix churn rate。

它让系统知道什么时候该稳定、什么时候该换 epoch、什么时候该 checkpoint，而不是无脑拼接或无脑总结。

## SkillFoundry 的新产品定位

SkillFoundry 是 ContextForge Agent Exoskeleton Runtime 的第一个产品化应用。

第一产品仍然是 Codex Skill 工厂，但产品含义升级：

```text
旧定位：
  把模糊需求转成 Codex Skill 包。

新定位：
  用 ContextForge Goal Harness 驱动强 agent worker，
  在可控上下文、可缓存 prompt、可审计证据和独立验收边界下，
  把业务需求转化为可复用、可测试、可注册的能力资产。
```

长期定位：

```text
SkillFoundry = AI capability delivery factory

它不仅能生产 Codex Skill，
还可以生产 prompt package、tool adapter、workflow node、agent contract、
verification suite、internal automation asset。
```

但第一阶段仍要克制：

```text
先把 Codex Skill 工厂做硬。
不要急于宣称通用自动化平台。
```

## 目标系统架构

目标架构：

```text
User / Product Owner
  -> SkillFoundry Front Desk
      -> Requirements Elicitor
      -> Spec Auditor
      -> Solution Planner
      -> User Review Gate
      -> FreezeGate

  -> LangGraph Workflow
      -> Goal Harness Node: Build
      -> Goal Harness Node: Repair
      -> Goal Harness Node: QA
      -> Goal Harness Node: Registry

  -> ContextForge Goal Harness
      -> GoalContract
      -> AgentNodeContract
      -> ContextView
      -> PromptView
      -> PromptCachePlan
      -> ToolPermission
      -> WriteScope
      -> WorkerRun
      -> Checkpoint
      -> EvidenceLedger
      -> VerificationGate

  -> Worker Layer
      -> Codex SDK thread worker
      -> GPT-5.5 direct worker
      -> fake worker
      -> external agent worker

  -> Verifier / QA / Registry
      -> independent validation
      -> artifact review
      -> approval
      -> versioned registry
```

责任分离：

```text
SkillFoundry:
  产品路径、用户体验、需求交付、资产注册。

LangGraph:
  大阶段流程、路由、重试、人工门。

ContextForge:
  goal harness、上下文视界、prompt cache、worker 边界、证据账本。

Worker:
  智能执行。

Verifier:
  独立验收。

Registry:
  可复用资产边界。
```

## 核心运行路径

### 1. Front Desk 发现真实需求

Front Desk 不应该一开始就追问技术字段。

它应该先发现：

- 用户真正的问题；
- 使用场景；
- 期望结果；
- 成功信号；
- 输入输出边界；
- 风险；
- 不该做什么；
- 是否需要人工确认；
- 是否有数据敏感性；
- 是否允许外部 API、文件读取、脚本执行。

输出：

```text
CoreNeed
ClarificationSummary
SolutionPlan
RiskReport
FrozenSpec candidate
```

### 2. Spec Auditor 独立审查

Spec Auditor 不负责讨好用户。

它负责判断：

- 需求是否清楚；
- 成功标准是否可测试；
- 是否存在不可验收目标；
- 是否有权限缺口；
- 是否有安全/隐私风险；
- 是否需要 human gate；
- 是否可以进入 builder。

输出：

```text
AuditReport
FreezeRecommendation
RequiredQuestions
RiskBlocks
```

### 3. FreezeGate 冻结合同

FreezeGate 是确定性门。

它把需求、方案、风险、权限、验收标准冻结成：

```text
GoalContract
AgentNodeContract
VerificationGate
```

一旦冻结，builder 不能再自由改变目标和验收标准。

### 4. LangGraph 进入 Build 阶段

LangGraph 不直接把 prompt 发给模型。

它启动一个 ContextForge Goal Harness node：

```text
BuildSkillNode
  goal_contract_ref
  agent_node_contract_ref
  worker_kind
  verification_gate_ref
```

### 5. ContextForge 编译上下文

ContextForge 从 ledger 和 workspace 中编译：

```text
ContextView
PromptView
PromptCachePlan
```

其中：

```text
stable prefix:
  role
  mission
  tool/write permission
  frozen constraints
  acceptance criteria
  verification gate
  output contract

dynamic suffix:
  current intent
  current plan
  recent failures
  governed tool diagnostics
  checkpoint summary
  selected memory
```

### 6. Worker 执行

Build worker 可以是：

```text
Codex SDK thread worker
GPT-5.5 white-box worker
fake worker
external worker
```

不管 worker 是谁，都必须进入同一套 `WorkerRun` 记录：

```text
worker_kind
input_context_view_id
prompt_view_ids
model_call_ids
tool_call_ids
tool_output_ids
artifact_ids
changed_files
summary
open_questions
risks
usage
status
```

### 7. 工具输出治理

raw tool output 不直接进 prompt。

所有工具输出必须：

- 原始内容 artifact 化；
- 通过 ToolOutputGovernor；
- 保留关键失败信号；
- 脱敏；
- 截断；
- 生成 governed output；
- 写入 ledger。

### 8. Checkpoint

长任务不能等到最后才记录。

Checkpoint 触发条件：

- build 阶段完成；
- repair 前；
- verifier 失败后；
- 连续失败；
- context pressure；
- handoff 前；
- budget 接近上限；
- worker 长时间运行。

Checkpoint 内容：

```text
current goal
locked acceptance
current best result
latest diagnosis
next plan
source evidence refs
do-not-repeat failed attempts
```

### 9. Verifier 独立验收

Verifier 从 frozen contract 和 artifact refs 出发，不信 worker 自述。

验收范围：

- Skill package schema；
- required sections；
- trigger / non-trigger coverage；
- acceptance coverage；
- path safety；
- test smoke；
- artifact hash；
- forbidden path；
- forbidden claim；
- optional LLM judge；
- human review gate。

输出：

```text
VerificationResult
QAReport
AcceptanceCoverageReport
RegistryDecision
```

### 10. Registry 注册资产

只有通过 verifier 的 asset 才能进入 Registry。

Registry 记录：

- skill id；
- version；
- package ref；
- verification report ref；
- acceptance coverage ref；
- provenance；
- usage feedback；
- rollback info；
- approval status。

## 关键合同

### GoalContract

SkillFoundry 中的 `GoalContract` 来自 frozen spec。

它描述“这次到底要交付什么”。

核心字段：

```text
goal_id
objective
user_problem
success_criteria
acceptance_criteria
non_goals
constraints
data_sensitivity
permission_requirements
budgets
checkpoint_policy
verification_gate_ref
locked_at
revision
```

### AgentNodeContract

每个 LangGraph agent node 都应该有自己的 `AgentNodeContract`。

核心字段：

```text
node_id
goal_id
role
mission
visible_context
forbidden_context
allowed_tools
write_scope
output_contract
worker_kind
cache_policy
checkpoint_policy
stop_conditions
handoff_policy
```

这是 SkillFoundry 覆盖 90% 以上 agent node 场景的关键。

### ContextView

ContextView 解释“worker 为什么看见这些内容”。

核心字段：

```text
context_view_id
goal_id
node_id
included_items
excluded_items
forbidden_items_checked
stable_prefix_items
dynamic_suffix_items
omitted_items
budget_report
trust_report
permission_report
cache_plan_ref
prompt_view_ref
```

### PromptCachePlan

PromptCachePlan 解释“本次调用如何控制缓存成本”。

核心字段：

```text
cache_plan_id
cache_epoch_id
stable_prefix_block_ids
dynamic_suffix_block_ids
stable_prefix_hash
dynamic_suffix_hash
provider_payload_hash
cache_break_reason
expected_cacheable_tokens
actual_cached_tokens
prefix_churn
```

### WorkerRun

WorkerRun 是强 agent 执行的白盒外壳。

核心字段：

```text
worker_run_id
worker_kind
worker_name
input_context_view_id
model_call_ids
tool_call_ids
artifact_ids
checkpoint_ids
changed_files
summary
failure_class
status
usage_summary
```

### VerificationGate

VerificationGate 是 frozen acceptance 的机器可执行版本。

核心字段：

```text
verification_gate_id
validators
required_evidence
metric_gates
artifact_hashes
forbidden_paths
forbidden_claims
review_required
human_authority_required
```

## Codex SDK thread 的定位

Codex SDK thread 是强 worker，不是平台主控。

适合让 Codex SDK thread 做：

- 复杂代码生成；
- 多文件修改；
- 测试修复；
- repo 级理解；
- 重构建议；
- 产物实现。

不应该让 Codex SDK thread 决定：

- 是否满足业务目标；
- 是否通过验收；
- 是否可以注册；
- 是否可以放宽 scope；
- 是否可以绕过权限；
- 是否可以修改 verification gate。

SkillFoundry 对 Codex SDK thread 的正确封装：

```text
CodexThreadWorker
  input:
    GoalContract
    AgentNodeContract
    ContextView
    write_scope
    tool_policy
    output_contract

  output:
    transcript_ref
    diff_refs
    artifact_refs
    summary
    changed_files
    open_questions
    risks
    usage_or_unavailable_reason

  post-process:
    ToolOutputGovernor
    EvidenceLedger
    VerificationGate
```

Codex SDK thread 的内部 prompt/cache/tool loop 可以是黑盒，但边界必须可审计。

## GPT-5.5 white-box worker 的定位

GPT-5.5 direct worker 是更白盒的执行体。

适合用于：

- 高审计要求；
- 高缓存成本敏感；
- 需要精确控制上下文；
- 需要每次模型调用 replay；
- 需要工具权限细粒度控制；
- 需要实验不同 context policy。

它和 Codex SDK thread 的区别：

```text
Codex SDK thread:
  更强工程执行能力。
  内部不完全白盒。
  更适合作为黑盒 builder。

GPT-5.5 white-box worker:
  每次模型调用都经过 ContextKernel。
  每次 prompt 都有 PromptCachePlan。
  每次工具输出都受治理。
  更适合高控制任务。
```

SkillFoundry 应该同时支持二者。

## Prompt cache 策略

SkillFoundry 的长任务成本控制必须成为产品能力。

基本策略：

```text
不要无限追加全部历史。
不要每轮都调用模型总结。
使用 ledger 保存完整历史。
使用 stable prefix 提高 cache 命中。
使用 dynamic suffix 承载最新状态。
使用 checkpoint summary 压缩阶段成果。
使用 cache epoch 控制何时重建前缀。
```

推荐 prompt layout：

```text
Stable prefix:
  platform rules
  worker role
  GoalContract stable fields
  AgentNodeContract stable fields
  tool/write permissions
  acceptance criteria
  VerificationGate
  output contract

Dynamic suffix:
  current node intent
  latest user-approved plan
  current workspace facts
  recent verifier failures
  governed tool diagnostics
  current checkpoint summary
  selected memory hits
```

cache epoch 改变条件：

```text
GoalContract revision
AgentNodeContract revision
VerificationGate revision
permission/write scope revision
major phase transition
user changes goal
security/risk policy changes
```

## SkillFoundry 作为第一个产品的原因

SkillFoundry 是 ContextForge Goal Harness 的理想第一产品，因为它天然要求：

- 模糊需求澄清；
- 多阶段流程；
- 强 agent 执行；
- 文件产物生成；
- 独立验收；
- repair loop；
- registry；
- usage feedback；
- 长任务恢复；
- 成本可观测；
- 上下文可审计。

这比普通 chat app 更能验证 ContextForge 的价值。

如果 ContextForge 能让 SkillFoundry 稳定生产高质量 Codex Skill，那么它就有机会扩展到：

- internal automation factory；
- agent workflow factory；
- prompt/tool package factory；
- enterprise knowledge workflow；
- software maintenance agent；
- data analysis agent；
- research assistant workflow。

## 分阶段路线

### Phase 0：保持当前 SkillFoundry 路线稳定

目标：

- 不打断当前 WP0-WP17 基线；
- 不把未来愿景误认为当前已完成能力；
- 不让 SkillFoundry 立刻依赖未完成的 ContextForge Goal Harness。

动作：

- 保留当前 `DEVELOPMENT_ROADMAP.md` 作为短期权威执行路线。
- 本文作为下一代产品愿景。
- 当前默认测试仍保持 deterministic/offline。

退出标准：

- 当前测试保持通过。
- 当前 Front Desk / Builder / Verifier / Registry 路线不被打断。

### Phase 1：ContextForge 完成 Goal Harness MVP

前置项目：`~/contextforge`

ContextForge 需要先完成：

- `GoalContract`
- `AgentNodeContract`
- `ContextView`
- `PromptCachePlan`
- `ToolPermission`
- `WriteScope`
- `WorkerRun`
- `GoalRunRecord`
- `VerificationGate`
- fake worker single-node harness

SkillFoundry 在此阶段只做跟踪，不强行迁移。

退出标准：

- ContextForge 能跑一个单节点 Goal Harness demo。
- PromptCachePlan 可证明 stable prefix / dynamic suffix。
- VerificationGate 不依赖 worker self-report。

### Phase 2：SkillFoundry 引入 GoalContract / AgentNodeContract

目标：

- 把 frozen spec 转成 ContextForge contracts。

动作：

- FrontDeskFreezeGate 输出 `GoalContract`。
- Build node 输出 `AgentNodeContract`。
- Acceptance Coverage 输出 `VerificationGate`。
- 当前 workspace artifacts 保持兼容。

退出标准：

- 每个 frozen Skill job 都有 goal contract。
- 每个 builder node 都有 node contract。
- builder 不再直接吃 raw frozen spec，而是吃 contract ref。

### Phase 3：Builder 进入 Goal Harness

目标：

- 把 Skill builder worker 放进 ContextForge Goal Harness。

动作：

- FakeWorker 先接入 Goal Harness。
- `LLMSkillBuilderWorker` 接入 white-box worker 路径。
- CodexWorker pilot 接入 black-box worker 路径。
- Worker output 统一记录为 `WorkerRun`。

退出标准：

- Build / repair 至少一个阶段由 Goal Harness 驱动。
- WorkerRun 记录完整。
- graph state 仍然只保存 refs，不保存大 prompt 或 raw transcript。

### Phase 4：Verifier 迁入 VerificationGate

目标：

- 把 SkillFoundry 现有 Verifier / QA / Acceptance Coverage 收敛到 ContextForge VerificationGate。

动作：

- 映射现有 validators。
- 增加 review gate / human authority gate。
- 增加 forbidden claim / forbidden path。
- 将 QA report、Acceptance Coverage report 写为 verification evidence。

退出标准：

- builder self-report 不能注册 asset。
- VerificationGate 失败时 Registry 不允许 approved。
- stale review result 被拒绝。

### Phase 5：PromptCachePlan 产品化

目标：

- 让成本控制成为 SkillFoundry 的可观测产品能力。

动作：

- 每个 LLM/worker call 记录 cache plan。
- UI/API 展示 prefix churn、cached tokens、cache break reason。
- 对长任务设置 cache budget 和 churn warning。

退出标准：

- 一个 job 可以报告：
  - prompt count；
  - input tokens；
  - cached input tokens；
  - prefix churn；
  - cache break reasons；
  - estimated cost。

### Phase 6：长任务 checkpoint / resume

目标：

- 让 SkillFoundry 能处理长时间复杂构建任务。

动作：

- 每个 build/repair/qa 阶段写 checkpoint。
- checkpoint 指向 evidence refs，不复制完整历史。
- resume brief 供新 worker 或 human reviewer 接手。

退出标准：

- 中断后可以从 checkpoint 恢复。
- 新 worker 可以不读完整 transcript 接手。
- verifier failure 后 repair node 能看到最新 diagnosis。

### Phase 7：内部真实产品试运行

目标：

- 用真实需求验证这套外骨骼是否有产品价值。

试运行样例：

- pytest repair helper skill；
- repo onboarding skill；
- API migration helper skill；
- frontend QA checklist skill；
- internal release note skill。

指标：

- 需求澄清轮数；
- frozen spec 成功率；
- build 成功率；
- verifier 一次通过率；
- repair 次数；
- token 成本；
- cache hit ratio；
- prefix churn；
- human review 次数；
- registry approval rate；
- 用户复用率。

退出标准：

- 至少 5 个真实内部需求跑通。
- 每个 approved skill 都有完整 evidence chain。
- 成本和失败原因可解释。

## 与当前 Roadmap 的关系

当前权威短期开发路线仍是：

- `docs/DEVELOPMENT_ROADMAP.md`
- `HANDOFF.md`

本文不是替代当前路线图，而是下一代架构愿景。

关系如下：

```text
当前 SkillFoundry:
  Front Desk + Builder + Verifier + Registry + ContextForge owned LLM boundary

下一代 SkillFoundry:
  Front Desk + LangGraph stages + ContextForge Goal Harness + strong workers + VerificationGate + Registry
```

也就是说：

```text
当前路线解决“Skill 工厂能不能跑起来”。
本文路线解决“Skill 工厂能不能长期稳定、可控、可审计、可缓存、可扩展地跑下去”。
```

## 成功标准

当这套愿景完成时，SkillFoundry 应该能做到：

```text
1. 用户提交模糊需求。
2. Front Desk 澄清真实目标。
3. FreezeGate 生成 GoalContract。
4. LangGraph 启动 Build stage。
5. ContextForge 编译 ContextView / PromptView / PromptCachePlan。
6. Codex SDK thread 或 GPT-5.5 worker 在边界内执行。
7. 所有工具输出被治理。
8. 长任务写 checkpoint。
9. Verifier 独立验收。
10. Registry 只注册通过验证的资产。
11. 整个过程可 replay、可审计、可恢复、可解释成本。
```

如果做不到这些，就不能宣称 SkillFoundry 是生产级 AI capability delivery factory。

## 非目标

这套愿景不意味着：

- 立即重写现有 SkillFoundry。
- 立即把 MetaLoop 代码搬进 SkillFoundry。
- 立即把 ContextForge 作为强依赖接入所有路径。
- 立即做多租户 SaaS。
- 立即做后台 agent pool。
- 立即做全自动万能 agent。
- 立即替代 Codex SDK thread。
- 立即把 LangGraph 用到每个细粒度工具步骤。

应该避免：

- 过早复杂化多 agent 编排；
- 把强模型切得太碎；
- 把 ContextForge 做成普通 memory 插件；
- 把 Verifier 弱化成 builder 自述；
- 把 prompt cache 当成事后指标，而不是设计目标。

## 推荐近期行动

短期在 SkillFoundry 中只做三件事：

```text
1. 保留当前产品路线，把 Front Desk / Builder / Verifier / Registry 做稳。
2. 跟踪 ContextForge Goal Harness 重构，不在 SkillFoundry 内重复实现。
3. 预留 contract adapter：
   FrozenSpec -> GoalContract
   BuilderInput -> AgentNodeContract
   AcceptanceCoverage -> VerificationGate
```

等 ContextForge 完成 Goal Harness MVP 后，SkillFoundry 再进入迁移：

```text
Phase 1:
  frozen spec 输出 GoalContract artifact。

Phase 2:
  builder node 使用 AgentNodeContract。

Phase 3:
  fake worker 进入 Goal Harness。

Phase 4:
  LLM builder / CodexWorker 进入 Goal Harness。

Phase 5:
  Verifier 迁入 VerificationGate。

Phase 6:
  PromptCachePlan 和 checkpoint 在 UI/API 产品化。
```

## 最终判断

SkillFoundry 的第一性产品价值不是“模型能生成 Skill 文件”。

真正价值是：

```text
把强 agent 的能力变成可控、可审计、可复用、可缓存、可验证的能力资产生产过程。
```

ContextForge 负责外骨骼。

SkillFoundry 负责第一座工厂。

这条路线比传统复杂多 agent 框架更简洁，也更符合 GPT-5.5 / Codex SDK thread 时代。
