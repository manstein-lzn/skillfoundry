# SkillFoundry v2 Baseline

最后更新：2026-05-22

## 一句话结论

SkillFoundry 当前没有线上用户、外部兼容性承诺或生产数据迁移负担。因此后续可以基于新版 ContextForge Goal Harness 重新设计技术实现。

但这不是推翻 SkillFoundry 的思想，而是把旧 v0 原型里已经验证过的产品判断，迁移到更干净的 v2 技术骨架上。

```text
保留 agent 协作架构和产品边界。
重建技术实现。
不要被旧 WP0-WP17 代码结构绑住。
```

## 当前仓库的性质

当前 SkillFoundry 仓库应被视为：

- v0 原型；
- 产品思想和边界验证材料；
- schema、workspace、verifier、registry、front desk 等能力样本；
- 下一版实现的知识资产。

当前仓库不应被视为：

- 已上线生产系统；
- 必须兼容的公共 API；
- 必须保留的内部模块结构；
- SkillFoundry v2 的代码约束；
- ContextForge Goal Harness 迁移后的最终实现形态。

## 不变的架构思想

SkillFoundry v2 必须保留以下判断：

- Front Desk 负责理解用户真实需求，不能直接交给 Codex 黑盒接管。
- 不清楚需求不能启动 builder。
- 用户批准或确定性 freeze 后才允许进入 build。
- LangGraph 管大阶段、路由、重试和人工门。
- ContextForge 管每个强 agent node 的 goal contract、context view、prompt cache plan、policy、worker evidence、checkpoint 和 verification record。
- Worker 只生成候选产物，不能自证通过。
- Verifier / QA / Acceptance Coverage 是独立质量门。
- Registry 只批准 verified asset。
- Workspace 文件是上下文和 artifact 载体。
- Graph state 只保存 refs / IDs，不保存 raw conversation、raw prompt、raw transcript、raw tool logs。
- Codex SDK thread / GPT-5.5 / external agent 是强执行体，不是平台事实源。

## 可以重建的实现

SkillFoundry v2 可以重写或替换以下实现：

- 旧 `SkillFoundryContextAdapter`。
- 旧 owned LLM call wrapper。
- 旧 worker boundary 到 ContextForge evidence 的手写桥。
- 旧 LangGraph skeleton。
- 旧 Front Desk loop orchestration 组织方式。
- 旧 `LLMSkillBuilderWorker` 的 prompt 拼接方式。
- 旧 WP0-WP17 work-package 代码边界。
- 旧 API/UI 外壳。
- 旧 roadmap 中以“ContextForge 只管 owned LLM call”为前提的叙述。

这些实现服务的是旧假设：

```text
ContextForge = SkillFoundry 的上下文运行时和 owned LLM call recorder
```

v2 的新假设是：

```text
ContextForge = SkillFoundry 每个强 agent node 的工作外骨骼
```

## 推荐 v2 技术骨架

建议 SkillFoundry v2 收敛成以下模块：

```text
src/skillfoundry/
  domain.py
    SkillJob
    CoreNeed
    SolutionPlan
    FrozenSkillSpec
    SkillPackageManifest
    RegistryDecision

  workspace.py
    JobWorkspace
    artifact refs
    path safety
    file hash
    frozen artifact protocol

  contracts.py
    FrozenSkillSpec -> GoalContract
    BuildStage -> AgentNodeContract
    VerificationSpec -> VerificationGate

  graph.py
    LangGraph stages
    refs-only state
    route by ContextForge goal decision / verification status

  frontdesk.py
    Core Need Discovery
    Solution Planning
    User Review
    FreezeGate
    Front Desk LLM nodes through ContextForge Goal Harness

  workers.py
    FakeSkillBuilderWorker
    OwnedLLMSkillBuilderWorker
    CodexThreadSkillBuilderWorker
    ExternalAgentSkillBuilderWorker
    all adapted to ContextForge WorkerAdapter protocol

  verification.py
    Skill-specific validators
    Acceptance Coverage
    QA report
    mapping to ContextForge VerificationResult

  registry.py
    approved asset store
    refuses unverified / stale / uncovered assets

  api.py
    product API / internal UI boundary
```

## v2 第一条垂直闭环

不要先迁移全部旧模块。第一条 v2 闭环应该是离线、确定性、可验证的最小产品骨架：

```text
requirement fixture
  -> FrontDesk fake freeze
  -> FrozenSkillSpec
  -> ContextForge GoalContract
  -> ContextForge AgentNodeContract(build)
  -> ContextForge GoalHarness
  -> FakeSkillBuilderWorker
  -> Skill package artifact
  -> ContextForge VerificationGate
  -> Skill verifier result
  -> Registry approved / rejected
  -> GoalRunRecord + checkpoint + evidence IDs
```

这条闭环的验收标准：

- 默认离线、deterministic。
- 不调用真实 provider。
- LangGraph state 只保存 IDs。
- `GoalRunRecord` 能追溯 `ContextView`、`PromptCachePlan`、`WorkerRun`、`VerificationResult`。
- builder self-report 不能注册。
- registry 只信 verifier / acceptance coverage。
- `PromptCachePlan` 能区分 stable prefix 和 dynamic suffix。
- checkpoint 能作为 resume / handoff 的标准边界。

## 旧 WP0-WP17 的位置

旧 WP0-WP17 是历史实现基线，不是 v2 技术约束。

它们的价值在于：

- 证明产品闭环曾经离线跑通过；
- 沉淀 workspace、verifier、registry、front desk、acceptance coverage 等业务规则；
- 记录哪些边界不应该被模型 self-report 穿透；
- 提供测试样例和反例。

它们不应该继续决定：

- v2 模块边界；
- v2 ContextForge 集成方式；
- v2 worker 协议；
- v2 graph state shape；
- v2 API/UI 形态。

历史 agent 执行任务书已归档到：

```text
docs/archive/agent-briefs/
```

## 当前状态

本文只固定 v2 基线前提：

```text
保留 SkillFoundry 的产品思想和 agent 协作边界。
基于 ContextForge Goal Harness 重建技术实现。
不要背旧 WP0-WP17 的模块兼容债。
```

当前 phase、已完成/未完成状态、下一工作包和验收门以 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 为准，不以本文为执行源。

截至 2026-05-22，仓库已经超过最初的“只做入口和依赖对齐”阶段：

- `third_party/contextforge` 已指向新版 ContextForge Goal Harness 主线。
- 根目录 `AGENT_BRIEF_WP*.md` 已归档。
- `src/skillfoundry/contracts.py` 的 contract bridge 已存在。
- offline Goal Harness build/verified runtime、workers v2、graph v2、Front Desk v2 slices、verification bridge 和 registry evidence gate 已存在。
- graph v2 repair route 已能执行 Goal Harness-backed repair，并在 repair 后重新经过 verifier、acceptance coverage、ContextForge bridge 和 registry gate。

当前仍不能说 v2 重构已经完成。下一阶段不再是“从 `contracts.py` 开始”，而是按 canonical 重构蓝图继续：

1. 让 `graph_v2.py` 成为唯一产品 build / verify / repair / registry 主骨架。
2. 补齐 API/UI 对 repair、human-review 和 registry evidence 的摘要体验。
3. 隔离或退役旧 `graph.py`、legacy prompt/context/worker 路径。

在这条 v2 product path 收敛前，仍不建议把新上下文能力继续堆到旧 `src/skillfoundry/context.py`。
