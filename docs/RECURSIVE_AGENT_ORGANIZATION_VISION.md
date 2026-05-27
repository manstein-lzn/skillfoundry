# Recursive Agent Organization Vision

最后更新：2026-05-27

## 文档地位

本文定义 SkillFoundry 背后更长期的最终目标：不是只构建一个
Capability Bundle Factory，也不是只构建一个 multi-agent workflow
framework，而是打磨一套能够递归组合智能执行单元的 agentic control
substrate。

它承接并上移以下文档：

- `docs/AGENT_WORK_SUBSTRATE_VISION.md`：定义 LangGraph + ForgeUnit + ContextForge
  作为通用 agent work substrate 的分层职责。
- `docs/CONTEXTFORGE_AGENT_EXOSKELETON_PRODUCT_VISION.md`：定义 ContextForge
  作为强 agent 工作外骨骼的长期方向。
- `docs/ADAPTIVE_STEERING_SUBSTRATE_EXTRACTION_PLAN.md`：记录已经在
  SkillFoundry 中验证过、未来可能下沉到底座的 adaptive steering primitives。

本文不是当前实现状态说明。当前实现仍以 `README.md`、`docs/SYSTEM_MAP.md`、
`docs/FORGEUNIT_SKILLFOUNDRY_COMPOSITION.md` 和测试结果为准。

## 一句话愿景

构建一个面向智能工作的递归控制系统，使单个 agent、agent team、department、
organization 都能通过同一套 bounded objective processor 接口递归组合，并在
可验证、可恢复、可审计、可调度的边界内承接任意复杂度的长期任务。

```text
Recursive Agent Organization =
  stable primitives
  + recursive composition
  + bounded execution
  + evidence feedback
  + independent verification
  + durable runtime
  + resource / policy control
```

中文表述：

```text
不是堆很多 agent。
而是用少数稳定元协议，
把任意智能执行单元递归封装成更大的智能组织。
```

## 核心判断

大模型让实现细节的边际价值下降，但没有让问题消失。

它把软件工程和组织工程的核心重心推向：

```text
如何设计一套稳定、自洽、可验证、可恢复的控制系统，
让强智能在其中持续行动、观察、修正，并被独立证据约束。
```

复杂系统不是靠枚举所有情况构建的，而是靠少数稳定 primitive 递归组合出来的。

物理世界也是类似结构：

```text
基本粒子
-> 原子
-> 分子
-> 蛋白质
-> 细胞
-> 器官
-> 生命体
-> 社会
```

agent work substrate 的目标是形成对应的智能工作层级：

```text
Tool Call
-> Runtime Event
-> WorkUnit
-> Agent Session
-> Agent Worker
-> Agent Team
-> Department
-> Organization
-> Ecosystem
```

每一层都可以拥有内部复杂性，但对上层暴露稳定接口：

```text
接受目标；
接受约束；
消耗资源；
执行工作；
产出证据；
报告状态；
接受验证；
处理失败。
```

## 不是 Multi-Agent Chat

大量 multi-agent 系统失败，是因为它们只是让多个模型互相说话：

```text
planner talks to researcher
researcher talks to coder
coder talks to reviewer
reviewer talks back to planner
```

这不是稳定的多 agent 系统，只是 prompt choreography。

目标系统应该是：

```text
每个 agent 都是受 WorkUnitContract 约束的执行器。
每个 team 都是可以被上层调用的 bounded worker。
每个 department 都是更大的 bounded objective processor。
每个 output 都进入 ObservationReport。
每个 ObservationReport 都进入 EvidenceGraph / Verifier。
每个状态变化都进入 DecisionLedger。
每个下一步都基于 corrected state 生成。
```

agent 不是自治叙事主体，而是控制系统中的受控执行单元。

## 递归组织模型

核心递归接口：

```text
interface WorkExecutor:
  accept(contract: WorkUnitContract) -> ExecutionHandle
  observe(handle) -> RuntimeEvent[]
  report(handle) -> ObservationReport
  verify(report) -> VerifierResult
```

实现这个接口的可以是：

- 单个 LLM worker；
- 一个 Codex / DeepAgents / Pi session；
- 一个由多个 agent 组成的开发团队；
- 一个专门做 verification 的部门；
- 一个完整的 agent organization；
- 一个外部公司或人类团队。

因此：

```text
Worker == Team == Department == Organization
```

它们内部复杂度不同，但外部协议一致。

这让复杂度可以通过封装增长，而不是泄漏到全局 orchestrator。

## 控制系统映射

这套体系的本质是控制系统，而不是传统 workflow。

```text
Objective              = 目标函数 / 任务意图
StateEstimate          = 当前状态估计
ContextProjection      = 给 worker 的观测窗口
WorkUnitContract       = 下一步控制输入
AgentRuntime           = 执行器 / actuator
Tools / filesystem     = 外部环境接口
ObservationReport      = 测量结果
EvidenceGraph          = 测量证据
Verifier               = 传感器校准 / truth gate
StateCorrection        = 状态修正
DecisionLedger         = 控制决策记录
Scheduler              = 多执行器调度器
PolicyEngine           = 安全约束 / 权限 / 预算 / 风险控制
Checkpoint / Replay    = 可恢复性
Reviewer               = 高阶策略审查
```

闭环：

```text
estimate
-> decide
-> contract
-> execute
-> observe
-> verify
-> correct
-> route
-> repeat
```

workflow 假设步骤大体已知。
control substrate 承认状态不完全、计划不完整、执行会改变认知。

因此真正稳定的是 feedback loop，不是一次性 plan。

## 四个平面

为了避免架构膨胀，系统应强制分成四个平面。

### Control Plane

负责目标、状态估计、下一步决策、路由、调度、预算和停止条件。

它拥有：

- Objective；
- StateEstimate；
- RoutePlan；
- Scheduler；
- dependency graph；
- priority / budget policy；
- escalation policy；
- stop conditions。

它不应该拥有：

- worker 具体执行细节；
- 原始 tool output；
- 大段对话 transcript；
- verifier 的独立判断权。

### Runtime Plane

负责 agent session、tool call、event stream、save point、abort、resume、sandbox。

它拥有：

- RuntimeSession；
- TurnSnapshot；
- RuntimeEvent；
- ToolCallJournal；
- SavePoint；
- Abort / Resume；
- lease / lock；
- execution environment。

它不应该决定业务目标是否完成。

### Evidence Plane

负责 artifact refs、logs、test results、hashes、observations、verification results。

它拥有：

- EvidenceRef；
- ArtifactRef；
- ObservationReport；
- VerifierResult；
- audit trail；
- replay material；
- forbidden path / forbidden claim evidence。

它不应该依赖 worker self-report 作为最终真相。

### Intelligence Plane

负责调用强模型、subagent、coding agent、research agent、domain worker。

它拥有：

- Codex / strong model worker；
- DeepAgents-style worker harness；
- Pi-style runtime session；
- specialized domain agent；
- human-in-the-loop worker；
- external service worker。

它可以提出方案、执行任务、解释失败、建议 state correction。
它不能拥有最终验收权。

## 核心 Primitives

第一版底座 primitive 不应太多。推荐收敛到以下对象。

### Objective

系统要优化或完成的目标。

Objective 不是一句 prompt，而是包含：

- target outcome；
- non-goals；
- acceptance criteria；
- constraints；
- priority；
- risk boundary；
- budget boundary。

### StateEstimate

当前对世界、任务、项目、组织状态的估计。

它不是 chat history。
它是经过证据修正后的工作状态。

### ContextProjection

把 StateEstimate、Evidence、Policy、Contract 投影成某个 worker 应该看到的最小上下文。

原则：

```text
Context is a projection, not the source of truth.
```

### WorkUnitContract

一个有边界的工作契约。

候选字段：

- objective；
- why now；
- visible refs；
- allowed read scope；
- allowed write scope；
- allowed tools；
- expected outputs；
- exit criteria；
- stop conditions；
- resource budget；
- risk boundary；
- verifier profile；
- recovery policy。

### RuntimeSession

worker 的可观测执行过程。

它记录：

- turn snapshots；
- provider requests；
- tool calls；
- tool results；
- runtime events；
- save points；
- abort / retry / resume；
- environment metadata。

### ObservationReport

执行后的结构化观测。

它区分：

- worker claims；
- produced artifacts；
- changed refs；
- commands run；
- tests run；
- failures；
- new unknowns；
- recommended next steps；
- verifier evidence；
- evidence gaps。

### EvidenceRef

可验证证据的引用。

证据可以是：

- artifact hash；
- command log；
- test output；
- schema validation result；
- diff；
- review note；
- external API result；
- screenshot / dataset / report；
- verifier result。

大内容不应直接塞入 state。

### VerifierResult

独立验证结果。

它回答：

- 是否满足 contract；
- 哪些 acceptance criteria 被覆盖；
- 哪些证据可信；
- 哪些 claim 未被证明；
- 是否越界；
- 是否需要 repair；
- 是否需要 reviewer；
- 是否可以 closure。

### StateCorrection

基于 Observation 和 Evidence 对 StateEstimate 的修正。

它不是 worker 自己改 state，而是底座根据证据提交 correction。

### DecisionLedger

记录系统为什么做某个决定。

它应该能回答：

- 为什么选择这个 WorkUnit；
- 为什么分配给这个 worker；
- 为什么接受或拒绝某个 output；
- 为什么 repair / review / stop；
- 为什么消耗这个预算；
- 为什么改变状态估计。

### ResourceBudget

控制 token、算力、时间、工具调用、人类注意力和风险。

上规模以后，budget 是组织稳定性的核心。

### Policy

权限、安全、合规、风险、升级规则。

Policy 是非智能边界，不应该交给 worker 自我约束。

### OrgUnit

递归组织单元。

它可以表示：

- individual agent；
- team；
- department；
- company；
- external partner。

OrgUnit 的关键不是名称，而是它是否实现 WorkExecutor 协议。

### CapabilityRegistry

记录谁能做什么、历史表现如何、适合接什么任务。

它是调度器选择 worker / team / department 的依据。

### Scheduler

根据 Objective、StateEstimate、DependencyGraph、CapabilityRegistry、ResourceBudget 和 Policy 选择下一批 WorkUnit。

Scheduler 不一定是 LLM。
它可以是规则、优化器、LLM judge、queue system 或它们的组合。

## 硬不变量

这些不变量比具体技术栈重要。

```text
1. Worker self-report is never final evidence.
   worker 自报永远不是最终证据。

2. Every execution is bounded by a WorkUnitContract.
   每次执行必须有明确边界。

3. All durable state changes are evented and replayable.
   所有持久状态变化必须事件化、可回放。

4. Context is a projection, not the source of truth.
   prompt/context 只是投影视界，不是真实状态源。

5. Artifacts enter state by refs, not raw blob stuffing.
   产物以引用进入状态，不把原始大内容塞进状态。

6. Verification is separate from generation.
   生成和验收分权。

7. Long-running work progresses only at save points.
   长任务只能在明确 save point 推进持久状态。

8. Failed work produces structured observation, not just exception text.
   失败也必须结构化进入系统。

9. Agents can propose state corrections, but the substrate commits them.
   agent 可以建议修正，底座决定是否提交。

10. Any sub-agent cluster can be wrapped as a single bounded worker.
    任意子集群必须能被上层看作一个有边界 worker。
```

## 开发团队作为第一种递归组织

完整 agent 开发团队是这个目标的自然近期验证场。

候选组织结构：

```text
Product / Requirement Agent
  -> 澄清需求、维护目标、非目标、验收标准

Architect Agent
  -> 设计模块边界、技术约束、ADR

Planner Agent
  -> 拆分 WorkUnitContract、管理依赖、优先级、风险

Implementation Agents
  -> 分别负责 frontend / backend / data / infra / tests

Reviewer Agent
  -> 代码审查、设计一致性、维护性、边界破坏

Verifier Agent
  -> 测试、schema、lint、集成验证、artifact hash

Security Agent
  -> 权限、secret、依赖、攻击面

Release Agent
  -> changelog、migration、部署计划、回滚计划

Documentation Agent
  -> 用户文档、开发文档、handoff

Coordinator / Controller
  -> 维护 StateEstimate、分配下一步、汇总 evidence、决定 repair / review / closure
```

但这些角色名不是本质。

本质是每个角色都必须服从同一套协议：

```text
WorkUnitContract
-> RuntimeSession
-> ObservationReport
-> EvidenceRef
-> VerifierResult
-> StateCorrection
-> DecisionLedger
```

## Agent 公司作为远期目标

成千上万个 agent 协作时，瓶颈不是单个 agent 智能，而是组织控制论。

主要风险：

- communication explosion；
- duplicated work；
- objective conflict；
- inconsistent state；
- permission abuse；
- budget runaway；
- verification bottleneck；
- local optimum；
- context pollution；
- error propagation；
- long-term drift；
- task starvation；
- resource contention。

因此公司级系统必须引入组织 primitive：

- OrgUnit；
- Role；
- CapabilityRegistry；
- ResourceBudget；
- PriorityQueue / PriorityMarket；
- WorkQueue；
- DependencyGraph；
- AuthorityModel；
- PolicyEngine；
- AuditLedger；
- KnowledgeGraph；
- EscalationPath；
- ReviewBoard；
- VerifierPool；
- IncidentSystem。

这不是模拟人类公司表面形式，而是抽象公司有效机制：

```text
目标分解；
责任归属；
资源分配；
质量控制；
风险隔离；
知识积累；
可追责性；
长期协调。
```

## 不应照抄人类公司

agent organization 不应该复制人类公司的所有形态。

人类公司中很多机制来自人类限制：

- 记忆差；
- 沟通慢；
- 注意力有限；
- 情绪复杂；
- 激励不一致；
- 培训周期；
- 会议成本；
- 上下班制度。

agent-native organization 应该保留有效机制，替换低效形态。

例如：

```text
会议
-> shared state board
-> event stream
-> async review packet
-> verifier summary
-> decision ledger

经理
-> scheduler
-> policy engine
-> state estimator
-> budget allocator

汇报
-> ObservationReport
-> EvidenceGraph
-> StateCorrection proposal

审计
-> append-only ledger
-> replay
-> artifact hash
-> verifier trail
```

## 规模化原则

### 层级化

不允许所有 agent 和所有 agent 全连接通信。

```text
局部 team 内部高频通信；
team 对外只发布 summary / evidence / state delta；
上层只处理 compressed interface；
跨团队通过 dependency graph 和 work queue 协调；
全局状态只存 refs 和 ledger。
```

### 信息压缩边界

每个 OrgUnit 对外暴露：

- accepted contracts；
- current status；
- produced artifacts；
- evidence refs；
- risks；
- unresolved questions；
- verifier status；
- resource usage。

不暴露全部内部 transcript。

### 局部自治，中央约束

OrgUnit 内部可以自主拆解和执行。
但必须遵守上层 contract、policy、budget、verification gate。

### 证据优先

所有上层决策都应基于 evidence，而不是基于 worker narrative。

### 预算约束

任何 agent / team / department 都必须在预算内工作。

预算包括：

- token；
- compute；
- wall-clock；
- tool calls；
- external API；
- human attention；
- risk；
- verification capacity。

## 与现有 SkillFoundry 的关系

SkillFoundry 当前仍是第一个产品化验证场：

```text
SkillFoundry =
  一个专门生产 verified capability bundle 的 agent organization prototype
```

它已经具备一些组织雏形：

- FrontDesk：需求入口和规格冻结；
- ContextForge：上下文、证据、ledger、checkpoint；
- ForgeUnit：bounded work-unit harness；
- adaptive steering：状态估计、下一步契约、观测、修正；
- Verifier：独立 truth gate；
- Registry：只注册 verified asset。

后续不应把这些机制理解成 skill factory 专属实现。

它们应该逐步抽象为：

```text
WorkUnit lifecycle；
Runtime harness；
Evidence substrate；
Verification gate；
Recursive OrgUnit interface；
Scheduler / resource policy。
```

然后可以实例化为：

- SoftwareFoundry；
- ResearchFoundry；
- DataFoundry；
- OpsFoundry；
- KnowledgeFoundry；
- CompanyFoundry。

## 与 Pi / DeepAgents 调研的关系

Pi 和 DeepAgents 分别提供了两个重要参考。

### Pi-style runtime kernel

Pi 更像透明 runtime kernel 参考：

- AgentLoop；
- TurnSnapshot；
- Session tree；
- SavePoint；
- pending writes；
- queue semantics；
- provider/tool hooks；
- semi-durable recovery model。

它对应 Runtime Plane。

### DeepAgents-style worker harness

DeepAgents 更像 batteries-included worker harness：

- LangGraph / LangChain agent；
- subagents；
- skills；
- filesystem；
- shell；
- memory；
- HITL；
- sandbox / deploy integrations。

它对应 Intelligence Plane 中的一种强 worker adapter。

### SkillFoundry 的位置

SkillFoundry / ContextForge / ForgeUnit 不应被任一 worker runtime 吞掉。

推荐关系：

```text
Pi-style runtime semantics
+ DeepAgents / Codex-style strong worker capability
+ ContextForge evidence/state substrate
+ ForgeUnit WorkUnitContract
+ independent verifier gate
= recursive agent organization substrate
```

## 成熟度路线

### L0: Single WorkUnit Runtime

一个 `WorkUnitContract` 驱动一个 worker，产出 `ObservationReport`，由
`VerifierResult` 决定是否通过。

目标：把单次智能执行变成可审计、可恢复、可验证的 work attempt。

### L1: Adaptive Loop

```text
StateEstimate
-> WorkUnitContract
-> ObservationReport
-> StateCorrection
-> route
```

目标：让复杂任务可以走一步、看证据、修正状态、再决定下一步。

### L2: Multi-Worker Cluster

一个任务可以拆给多个 bounded worker。
所有结果进入 EvidenceGraph 和 DecisionLedger。

目标：实现 agent team。

### L3: Durable Long-Running Runtime

支持：

- save point；
- resume；
- branch；
- retry；
- abort；
- lease；
- tool journal；
- budget ledger；
- recovery policy。

目标：让长任务稳定运行，而不是靠 chat history 和临时状态。

### L4: Recursive Agent Cluster

一个 cluster 可以包装成一个 worker，被更上层 orchestration 调用。

目标：实现 team / department / organization 的递归组合。

### L5: Domain-Instantiated Organizations

不同领域只改变 profile、worker、verifier、artifact schema、policy 和 budget。

目标：SoftwareFoundry、ResearchFoundry、DataFoundry、OpsFoundry 等都成为同一底座的实例。

## 近期工程焦点

不要立刻构建一万个 agent。

近期最重要的问题是：

```text
一个 WorkUnit 从创建到完成，完整、可恢复、可验证的生命周期到底是什么？
```

候选生命周期：

```text
created
-> context_projected
-> assigned
-> runtime_started
-> tool_calls_recorded
-> artifacts_written
-> observation_submitted
-> verifier_started
-> verified_passed / verified_failed / review_required
-> state_corrected
-> closed / repaired / escalated
```

每个状态转移都应该：

- 有 event；
- 有 schema；
- 可 replay；
- 可 checkpoint；
- 可被 verifier / reviewer 审查；
- 可被上层 OrgUnit 聚合。

## 反目标

这套体系不应该变成：

- 一个巨大总控大脑；
- 一个所有 agent 互相聊天的聊天室；
- 一个把所有状态塞进 prompt 的上下文拼接器；
- 一个把 worker self-report 当验收的自动化脚本；
- 一个模拟人类公司表面职级的角色扮演系统；
- 一个无法 replay、无法 audit、无法恢复的黑盒调度器；
- 一个只支持 SkillFoundry 单一产品语义的封闭实现。

控制器要小。
协议要硬。
worker 要强。
验证要独立。
状态要可恢复。

## 最终目标

最终目标不是自动写代码。

最终目标是构造一种新的智能组织形式：

```text
一个 agent 是一个执行单元；
一个 team 是一个更大的执行单元；
一个 department 是一个更大的执行单元；
一个 company 是一个巨大的执行单元；
一个生态是多个执行单元之间的递归组合。
```

只要接口稳定、证据可信、状态可恢复、预算可控、验证独立，复杂度就可以通过递归组合增长。

这就是 SkillFoundry 背后的更长期方向：

```text
Recursive Operating System for Agentic Organizations.
面向智能组织的递归操作系统。
```
