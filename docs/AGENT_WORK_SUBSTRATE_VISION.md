# Agent Work Substrate Vision

最后更新：2026-05-27

## 文档地位

本文定义 ForgeUnit + ContextForge + LangGraph 组合体系的更上层愿景。

它不是 SkillFoundry 的产品愿景，而是 SkillFoundry 背后的通用 agent work substrate 愿景。

SkillFoundry 是这套底座的第一个产品化组合应用。Capability Bundle Factory 是 SkillFoundry 的当前业务形态，但并不是这套底座的能力边界。

更长期的递归组织目标见 `docs/RECURSIVE_AGENT_ORGANIZATION_VISION.md`。本文定义底座分层；该文定义这些底座 primitives 如何递归组合成 agent team、department、organization 和更大智能组织。

本文不声称当前代码已经完整实现所有抽象。当前实现状态仍以 `README.md`、`docs/SYSTEM_MAP.md`、`docs/FORGEUNIT_SKILLFOUNDRY_COMPOSITION.md` 和测试结果为准。

## 一句话愿景

ForgeUnit + ContextForge + LangGraph 应当组成一套通用 agent work substrate，用来构建任意复杂度的多 agent 工作集群。

```text
LangGraph = orchestration topology
ForgeUnit = bounded work-unit harness
ContextForge = governed state / context / evidence substrate
Verifier = truth gate
Reviewer = quality and strategy gate
Codex / strong model = worker intelligence
Adaptive Steering = complex-task control loop
```

中文表述：

```text
LangGraph 管流程拓扑。
ForgeUnit 管有边界的一步执行。
ContextForge 管状态估计、证据、修正和上下文投影。
Verifier 管真假。
Reviewer 管质量和策略判断。
Codex / 强模型管智能执行。
Adaptive Steering 管复杂任务中的走一步看一步。
```

## 核心判断

复杂 agent 工作不能依赖一次性完整规划。

大型代码迁移、研究复现、数据工程、知识库构建、EDA 自动化、企业流程自动化、Capability Bundle 构建，都有同一个结构：

```text
当前只知道目标和部分状态。
下一步需要根据当前最可信状态来预测。
执行后必须看真实证据。
新证据会修正状态。
修正后的状态决定下一步。
```

这套模式不是 SkillFoundry 专属，而是复杂 agent 工作的通用控制论。

因此，卡尔曼式 adaptive steering 应该是 substrate-native，domain-instantiated。

```text
Kalman-style steering should be substrate-native, domain-instantiated.
```

中文：

```text
卡尔曼式 steering 应该是底座原生能力，在具体领域应用中实例化。
```

## SkillFoundry 的位置

SkillFoundry 是组合应用，不是底座。

它使用底座来完成一个具体产品目标：

```text
把任意需求铸造成 verified AI-native Capability Bundle。
```

SkillFoundry 独有的是领域语义：

- Capability Bundle；
- Bundle Manifest；
- Package Profile；
- Capability Surface；
- Agent Interface；
- Runtime Interface；
- Distribution Policy；
- Skill Registry；
- skill-specific verifier profiles。

SkillFoundry 不应该永久私有化这些通用机制：

- state estimate；
- next-step contract；
- observation report；
- state correction；
- decision ledger；
- adaptive steering loop；
- reviewer gate；
- verifier gate；
- repair loop；
- refs-only state；
- checkpoint；
- replay。

这些机制应该先在 SkillFoundry 中以领域形态验证，成熟后下沉到 ContextForge / ForgeUnit。

## 分层职责

### LangGraph

LangGraph 负责 workflow 拓扑。

它拥有：

- node；
- edge；
- conditional route；
- loop；
- branch；
- join；
- repair route；
- review route；
- human gate；
- stop condition。

它不应该拥有：

- state estimate 的语义；
- evidence 可信度判断；
- decision ledger；
- prompt/cache 细节；
- domain-specific quality bar；
- worker 自身执行逻辑。

原则：

```text
LangGraph owns orchestration topology.
It should stay thin.
```

中文：

```text
LangGraph 管流程拓扑，保持薄。
```

### ForgeUnit

ForgeUnit 负责 bounded work-unit harness。

它拥有：

- WorkUnit；
- NextStepContract 的执行边界；
- visible input refs；
- allowed write scope；
- expected outputs；
- exit criteria；
- stop conditions；
- execution attempt；
- observation report envelope；
- repair packet handoff；
- work-unit result。

ForgeUnit 不关心这一步是在做 EDA 文档解析、Rust 内核开发、数据清洗，还是服务包装。

它只关心：

```text
这一步目标是什么？
能看什么？
能写哪里？
预期产物是什么？
怎样记录执行？
怎样汇报结果？
失败怎样返回？
```

原则：

```text
ForgeUnit owns bounded execution.
It turns a steering decision into a governed work attempt.
```

中文：

```text
ForgeUnit 管有边界的一步执行。
```

### ContextForge

ContextForge 负责 governed state / context / evidence substrate。

它拥有：

- StateEstimate；
- EvidenceItem；
- EvidenceReliability；
- Observation；
- StateCorrection；
- DecisionLedger；
- ContextView；
- PromptCachePlan；
- Checkpoint；
- Replay；
- HandoffSummary；
- refs-only state projection；
- context compilation for the next worker。

如果使用卡尔曼类比：

```text
State estimate      -> ContextForge
Measurement         -> ContextForge evidence / observation
Measurement noise   -> ContextForge evidence reliability
Correction          -> ContextForge state correction / decision ledger
Checkpoint          -> ContextForge checkpoint
Replay              -> ContextForge replay
```

ContextForge 的核心不是简单拼 prompt，而是维护 agent 工作过程中的受治理状态估计和证据链，并把它投影成下一轮 worker 应该看到的上下文视界。

原则：

```text
ContextForge owns governed state, evidence, correction, and context projection.
```

中文：

```text
ContextForge 管状态估计、证据、修正和上下文投影。
```

### Verifier

Verifier 负责 truth gate。

它判断：

- artifact 是否存在；
- schema 是否有效；
- hash 是否匹配；
- 命令是否真实通过；
- worker 是否越界；
- forbidden claim 是否出现；
- final report 是否 refs-only；
- 结果是否满足 frozen spec。

Verifier 不负责创造，也不负责替 worker 解释为什么失败。

原则：

```text
Worker self-report is not acceptance.
```

### Reviewer

Reviewer 负责 quality and strategy gate。

Verifier 更偏真假，Reviewer 更偏质量、取舍和方向。

Reviewer 应检查：

- 当前路线是否合理；
- next-step contract 步长是否过大或过小；
- worker 是否把困难藏进 known gaps；
- domain quality 是否足够；
- verification 是否太弱；
- 是否需要回到 spec revision；
- 是否应该继续、repair、redesign、pause 或 closure。

Reviewer 可以是 human，也可以是 independent reviewer agent，也可以由 deterministic policy 处理低风险路径。

### Codex / Strong Worker

Codex exec、Codex SDK thread、GPT-5.5 或其他强模型 worker 负责智能执行。

它可以：

- 写代码；
- 读文档；
- 调研工具；
- 构建数据库；
- 实现服务；
- 写测试；
- 修复失败；
- 组织交付物。

但它不能独自决定：

- 自己是否通过验收；
- 一步是否真的完成；
- 是否可以注册；
- 是否可以越过 frozen spec；
- 是否可以泄漏 raw prompt、raw transcript 或私有 source。

## 卡尔曼式 Adaptive Steering

复杂任务的通用循环：

```text
StateEstimate
  -> NextStepContract
  -> WorkUnitExecution
  -> ObservationReport
  -> StateCorrection
  -> RoutingDecision
  -> continue / repair / redesign / review / stop / closure
```

它的哲学是：

```text
先基于当前状态预测下一步。
执行 bounded work unit。
用真实证据观测结果。
按证据可信度修正状态。
再决定下一步。
```

这不是一次性 plan-and-execute，也不是无约束随机游走。

它是有模型、有预测、有观测、有修正、有收敛的工作控制循环。

## 通用 Primitive

### StateEstimate

当前系统对任务真实状态的压缩判断。

通用字段可以包括：

- objective confidence；
- known good；
- known bad；
- known unknowns；
- current risks；
- verification status；
- blockers；
- next best step；
- confidence by subsystem。

领域应用可以扩展领域字段。

SkillFoundry 可以扩展：

- package profile；
- runtime substrate status；
- agent interface status；
- bundle manifest status；
- distribution policy status。

ResearchFoundry 可以扩展：

- literature coverage；
- evidence strength；
- reproducibility status；
- claim risk。

CodeOps 可以扩展：

- migration status；
- test suite status；
- compatibility risk；
- rollout risk。

### NextStepContract

下一步工作合同。

通用字段可以包括：

- current state ref；
- next objective；
- why now；
- allowed scope；
- visible refs；
- expected outputs；
- exit criteria；
- stop conditions；
- estimated followups；
- risk if too large；
- risk if too small。

### ObservationReport

工作之后的观测报告。

通用字段可以包括：

- produced artifacts；
- changed refs；
- tests run；
- commands run；
- failures；
- worker claims；
- verifier evidence；
- reviewer notes；
- new unknowns；
- recommended next steps。

### StateCorrection

基于观测对状态估计的修正。

通用字段可以包括：

- previous state ref；
- observation refs；
- evidence reliability；
- corrected fields；
- changed confidence；
- decision；
- rationale；
- fallback；
- next route。

### DecisionLedger

关键决策账本。

通用字段可以包括：

- decision id；
- context；
- options；
- chosen option；
- rationale；
- risk；
- expected evidence；
- fallback；
- reviewer；
- timestamp。

## 证据可信度

不同证据来源的可信度不同。

高可信：

- compiler result；
- test result；
- hash match；
- schema validation；
- deterministic command output；
- verifier evidence；
- explicit human/domain review。

中可信：

- sample query；
- LLM judge；
- small sample conversion；
- benchmark on limited fixtures。

低可信：

- worker self-report；
- unverified summary；
- unrun command claim；
- “looks good” statement；
- 未绑定 artifact 的口头判断。

原则：

```text
可靠观测应大幅修正状态。
噪声观测只能小幅修正，或者要求更多证据。
```

## 多 Agent 集群

这套底座应能支持任意复杂度的多 agent 集群。

典型集群可以包含：

- Supervisor / Steering Agent；
- Research Agent；
- Builder Agent；
- Tester Agent；
- Reviewer Agent；
- Integrator Agent；
- Verifier Agent；
- Domain Specialist Agent。

但 agent 数量不是核心。

核心是每个 agent 都工作在明确边界内：

```text
Goal Contract
Visible Context
Write Scope
Next-Step Contract
Observation Report
Decision Ledger
Verification Gate
```

多 agent 不是让多个黑盒并发乱跑，而是让多个受治理 work unit 在统一状态估计和证据账本下协作。

## 泛化路径

短期不应直接在底座层过度抽象；但已验证的 adaptive primitives 也不应继续被当成临时实现。

推荐路径：

```text
Prototype in SkillFoundry.
Validate with Codexarium / Mini-EdaSkill / EdaSkill-like pilots.
Identify stable primitives.
Generalize into ContextForge / ForgeUnit.
Keep LangGraph thin.
```

中文：

```text
先在 SkillFoundry 试出来。
用真实复杂任务验证。
识别稳定 primitives。
再下沉到 ContextForge / ForgeUnit。
LangGraph 保持薄。
```

原因：

- 过早抽象容易设计出空泛框架；
- 真实任务会暴露字段、证据、步长和 review gate 的实际需要；
- SkillFoundry 足够复杂，适合作为底座试验场；
- 成熟后再抽象，复用价值更高。

当前结论：

- adaptive steering MVP 已在 SkillFoundry 层验证成立；
- baseline/upgraded benchmark 已证明它是可比较、可收敛的控制循环；
- 下一步重点是收敛稳定 primitives，而不是扩大试验半径；
- 具体领域实例保留在 SkillFoundry，通用骨架再考虑下沉到 ContextForge / ForgeUnit。

## 可复用应用

同一套 substrate 可以支撑多个组合应用：

- SkillFoundry：把需求铸造成 Capability Bundle；
- ResearchFoundry：自动化调研、文献综述、实验复现；
- CodeOps：自动化大型代码库迁移、测试修复、技术债治理；
- DataFoundry：自动化数据清洗、数据转换、知识库构建；
- EDAOps：自动化半导体 EDA flow、版图脚本、验证任务；
- ProductOps：自动化 PRD、原型、用户反馈、实验计划；
- EnterpriseOps：自动化企业内部流程和知识工作。

这些应用共享底座 primitives，但拥有各自领域语义。

## 宪法级结论

SkillFoundry 是第一座工厂，不是最终平台本身。

真正的平台目标是：

```text
A reusable agent work substrate for building governed multi-agent clusters
that can automate open-ended complex work.
```

中文定义：

```text
一套可复用的 agent 工作底座，
用于构建受治理的多 agent 集群，
自动化开放式复杂工作。
```

归属原则：

```text
LangGraph owns topology.
ForgeUnit owns bounded work execution.
ContextForge owns governed state, evidence, correction, and context projection.
SkillFoundry owns capability-bundle domain semantics.
```

这就是 ForgeUnit + ContextForge + LangGraph 组合体系的上层愿景。
