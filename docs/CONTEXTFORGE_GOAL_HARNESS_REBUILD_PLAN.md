# SkillFoundry x ContextForge Goal Harness 重构计划

最后更新：2026-05-22

状态：historical execution plan + implementation evidence

当前权威：v2 phase 编号、当前下一步和新 contributor 执行入口以 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 为准。本文保留最初的重构计划、字段级设计、风险门和历史执行证据；其中早期 “Phase 1/2/Immediate Next PR” 已经完成或被后续蓝图 supersede。

历史独立审查：原始版本已由第三方 `gpt-5.5 xhigh` reviewer 静态审查，结论为 `approve_with_required_clarifications`。审查要求已经合入历史计划：明确文档权威、限定第一阶段为离线 deterministic vertical slice、避免继续 patch 旧 `context.py` / `worker.py` / `llm_builder.py`。

## 0. 人话结论

SkillFoundry v2 应该基于新版 ContextForge Goal Harness 重建技术骨架。

这不是因为 v0 原型失败，而是因为前提变了：

- SkillFoundry 没有上线用户；
- 没有外部 API 兼容承诺；
- 没有生产数据迁移负担；
- ContextForge 已经从“上下文运行时”升级为“强 agent 工作外骨骼”。

因此，SkillFoundry 不应该继续围着旧 `SkillFoundryContextAdapter`、旧 worker boundary、旧 owned LLM call wrapper 做增量补丁。更合理的路线是：

```text
保留 SkillFoundry 的 agent 协作思想。
保留 v0 验证过的产品边界。
围绕 ContextForge Goal Harness 重建实现。
```

最终目标：

```text
SkillFoundry = ContextForge Agent Exoskeleton Runtime 的第一个产品化应用

Front Desk 理解需求。
LangGraph 管大阶段。
ContextForge 管每个强 agent node 的工作外骨骼。
Codex SDK thread / GPT-5.5 / external agent 做智能执行。
Verifier / QA / Acceptance Coverage 判断真假。
Registry 只批准 verified asset。
```

## 1. 本文用途

本文是 SkillFoundry v2 重构的原始工程执行计划和历史证据记录。

### 1.1 文档权威

从当前版本开始，SkillFoundry 后续 **v2 技术重建** 以 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 为 canonical 执行源。本文用于解释原始设计、字段级 contract bridge、PromptCachePlan 策略、worker taxonomy 和历史 reviewer 结论。

文档分工如下：

| 文档 | v2 中的地位 |
| --- | --- |
| `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` | v2 当前 canonical 蓝图、phase 编号和下一步执行源。 |
| `docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md` | 原始重构执行计划、字段级设计和历史执行证据。 |
| `docs/SKILLFOUNDRY_V2_BASELINE.md` | v2 前提和边界声明。 |
| `docs/CONTEXTFORGE_AGENT_EXOSKELETON_PRODUCT_VISION.md` | 长期产品愿景和架构隐喻。 |
| `docs/DEVELOPMENT_ROADMAP.md` | v0/WP0-WP17 历史能力基线和产品经验输入，不再约束 v2 模块边界。 |
| `HANDOFF.md` | 当前仓库状态和接手提醒；应引用 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 作为 v2 执行源，并把本文作为历史计划和证据。 |
| `docs/archive/agent-briefs/` | 历史 agent brief 归档，只用于追溯旧实现。 |

如果本文与旧 `DEVELOPMENT_ROADMAP.md`、`ROADMAP.md`、`ROADMAP_EXECUTION_PLAN.md`、`FRONT_DESK_AGENT_ROADMAP.md` 出现冲突：

```text
v2 技术实现以 SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md 为准。
本文中与 canonical 蓝图冲突的 phase 编号或 next PR 描述，按历史记录处理。
旧 roadmap 只作为历史设计输入和业务规则来源。
```

特别是旧文档中“ContextForge 主要管 SkillFoundry owned LLM call”的叙述已经过期。v2 的新前提是：

```text
ContextForge 管 SkillFoundry 每个强 agent node 的工作外骨骼。
```

它承接：

- `docs/SKILLFOUNDRY_V2_BASELINE.md`
- `docs/CONTEXTFORGE_AGENT_EXOSKELETON_PRODUCT_VISION.md`
- `third_party/contextforge/docs/architecture.md`
- `third_party/contextforge/docs/goal-harness-quickstart.md`

它不替代：

- 产品白皮书；
- ContextForge 自身架构文档；
- 未来每个阶段的具体 PR 说明；
- 真实上线前的 security / ops / deployment 文档。

本文要回答的问题是：

```text
在 SkillFoundry 没有上线兼容负担的前提下，
如何保留 agent 协作思想，
并用新版 ContextForge Goal Harness 重建 SkillFoundry 技术骨架。
```

不要读错：

- 不要把本文第 15 节的 original phase 编号当作当前任务编号。
- 不要执行本文旧版第 19 节的 “Immediate Next PR = Phase 1 contracts”；`contracts.py` 和离线 vertical slice 已经落地。
- 当前下一步以 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 第 11 节和 `HANDOFF.md` 为准。
- `PromptCachePlan` 记录缓存规划和 telemetry；除非 provider 返回实际 cached token 数据，否则不能宣称真实 cache hit。

## 2. 设计输入

### 2.1 SkillFoundry 当前事实

当前 SkillFoundry 仓库是 v0 原型和知识资产，不是生产系统。

已经存在的有价值资产：

- Front Desk 的 core need discovery / solution planning / user review / freeze 思想；
- refs-only graph state 约束；
- workspace 文件即上下文协议；
- path safety、artifact hash、locked input；
- worker self-report 不能通过验收的规则；
- verifier / QA / acceptance coverage / registry gate；
- CodexWorker 只能作为 external boundary 的判断；
- 默认测试离线 deterministic 的工程纪律。

当前不应继续强绑定的旧实现：

- `src/skillfoundry/context.py` 中的旧 ContextForge adapter；
- 旧 owned LLM call replay wrapper；
- 旧 `LLMSkillBuilderWorker` 手写 prompt 拼接方式；
- 旧 worker boundary 到 ContextForge evidence 的旁路桥；
- 旧 LangGraph skeleton 的 WP2 状态模型；
- 旧 WP0-WP17 work-package 代码边界；
- 为旧 ContextForge 假设写的文档叙述。

### 2.2 ContextForge 当前事实

`third_party/contextforge` 当前指向新版 Goal Harness 主线：

```text
2a0838bce6a7a2607b9ca1e095e044080fdc6759
```

SkillFoundry 本地 `.venv` 已验证可导入：

```text
GoalHarness
GoalContract
AgentNodeContract
VerificationGate
```

ContextForge 当前已经提供：

- `GoalContract`
- `AgentNodeContract`
- `ContextView`
- `PromptView` / `PromptBlock`
- `PromptCachePlan`
- `ToolPermission`
- `WriteScope`
- `WorkerRun`
- `GoalRunRecord`
- `VerificationGate`
- `VerificationResult`
- `CheckpointRecord`
- `FakeWorker`
- `CodexThreadWorker`
- `ExternalAgentWorker`
- LangGraph-style ID-only adapter helpers

ContextForge 当前还没有提供：

- 真实 Codex SDK thread 执行器；
- 生产级 provider SDK worker；
- 多节点 scheduler；
- SaaS / API / UI；
- 生产沙箱；
- 多租户权限系统。

所以 SkillFoundry v2 的正确姿势是：

```text
使用 ContextForge 已有 Goal Harness 边界。
不要假装 ContextForge 已经提供生产平台能力。
SkillFoundry 自己负责产品语义、workspace、verifier、registry 和 API/UI。
```

### 2.3 已核对的 source-of-truth facts

当前事实已按 `third_party/contextforge` submodule 核对：

```text
third_party/contextforge = 2a0838bce6a7a2607b9ca1e095e044080fdc6759
```

核对结果：

- `docs/architecture.md` 明确 ContextForge 是 Agent Exoskeleton Runtime。
- Goal Harness 主路径包含 `ContextView`、`PromptView`、`PromptCachePlan`、`WorkerRun`、`VerificationResult`、`CheckpointRecord`、`GoalRunRecord`。
- `CodexThreadWorker` 只记录 transcript/diff/artifact/changed file/policy evidence；它不 replay Codex 内部 prompt/cache/tool loop。
- `PromptCachePlan` 是成本控制计划和 telemetry artifact；它可以记录 expected cacheable tokens、cache epoch、cache break reason 和 provider cache telemetry，但不能保证 provider cache hit。

### 2.4 当前实现矩阵

这张表是本文区别“历史计划”和“当前代码事实”的权威索引。若它和第 15 节 original phase 描述冲突，以这张表和 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 为准。

| 区域 | 当前状态 | 当前事实 | 后续动作 |
| --- | --- | --- | --- |
| ContextForge submodule | implemented | Goal Harness 主线已接入，核心 schema/runtime 可导入。 | 不在 SkillFoundry 内重造 ContextForge。 |
| `contracts.py` | implemented | Phase 1 contract bridge 已落地。 | 保持 raw context exclusion、hash、cache epoch 测试。 |
| `goal_runtime.py` | implemented / partial | 离线 verified Goal Harness runtime 已存在，并被 graph v2 API happy path 调用；repair Goal Harness runtime 能记录 WorkerRun、ContextView、PromptCachePlan、checkpoint、repair instructions、repair runtime result 和 `RepairAttempt`。 | 补齐 repair 后的复验/注册闭环。 |
| `workers_v2.py` | implemented / partial | Fake/owned LLM/Codex boundary/external worker taxonomy 已存在。 | live provider 和 real Codex 仍是 opt-in pilot。 |
| `graph_v2.py` | implemented / partial | refs-only spine、verified build/registry nodes、API happy path runner 已存在；failed verification route 可以执行 Goal Harness-backed repair node 并保持 graph state refs-only。 | 补齐 repair -> verify -> registry loop，并将旧 `graph.py` 退役或隔离为 compatibility wrapper。 |
| `frontdesk_v2.py` | implemented | Front Desk node contracts 已存在。 | 继续把 raw conversation 固定为 forbidden provenance。 |
| `frontdesk_goal_runtime.py` | implemented | Core Need、Solution Planner、Spec Auditor Goal Harness slices 已存在；默认 no-key Front Desk 路径已接入；Front Desk criteria 已使用 deterministic verifier check IDs。 | 保持 approved-review/freeze gate 和 raw conversation exclusion。 |
| `verification_bridge.py` | implemented | Verifier / acceptance coverage 到 ContextForge VerificationResult 的桥已存在，并能消费 Front Desk deterministic criteria。 | 加强语义验收和 evidence hash binding。 |
| Registry evidence gate | implemented / partial | Registry 会拒绝 missing/stale/fabricated/self-reported evidence；默认 Front Desk graph v2 happy path 能 register。 | 继续覆盖 repair/human-review/manual acceptance 场景。 |
| API/UI | implemented / partial | Front Desk job、message、plan review、offline default path、`POST /frontdesk/jobs/{job_id}/build` graph v2 happy path 已存在；status 暴露 v2 refs 摘要。 | 完善 repair/human-review route 和 UI evidence 体验。 |
| live provider / real Codex SDK thread | future opt-in | 不属于默认测试路径或生产承诺。 | 离线 v2 主路径稳定后再试点。 |

## 3. 不变的架构思想

以下判断不允许在 v2 重构中被推翻。

### 3.1 Front Desk 不是 Codex 黑盒

Front Desk 负责理解用户真实需求，不能直接交给 Codex SDK thread 黑盒处理。

Front Desk 必须产出：

- core need；
- solution plan；
- risk report；
- acceptance criteria；
- user review record；
- frozen spec candidate。

### 3.2 不清楚需求不能进入 builder

Builder 只能读取 frozen inputs。

禁止：

- builder 直接读取 raw conversation；
- builder 自己补齐缺失业务目标；
- builder 自己修改 acceptance criteria；
- builder 自己放宽风险/权限约束。

### 3.3 LangGraph 管大阶段

LangGraph 负责：

- intake；
- clarification；
- planning；
- freeze；
- build；
- repair；
- verify；
- registry；
- feedback；
- human review。

LangGraph 不负责：

- 拼 prompt；
- 长上下文存储；
- worker transcript 存储；
- verifier 语义判断；
- 强 agent 内部工具循环。

LangGraph state 只保存 refs / IDs。

### 3.4 ContextForge 管 agent node 工作外骨骼

ContextForge 管：

- goal contract；
- node contract；
- context visibility；
- prompt cache plan；
- tool permission；
- write scope；
- checkpoint；
- worker run evidence；
- verification record；
- ledger / replay / telemetry。

ContextForge 不替代：

- SkillFoundry 产品语义；
- LangGraph orchestration；
- Skill-specific verifier；
- registry；
- UI/API；
- Codex SDK thread 内部 prompt/cache/tool loop。

### 3.5 Worker 不能自证通过

不管 worker 是 fake、owned LLM、GPT-5.5、Codex SDK thread、Claude Code 还是 external agent：

```text
worker self-report != acceptance
worker completed != registry approved
worker summary != verifier evidence
```

Worker 只能提交 candidate artifacts 和 evidence refs。

### 3.6 Verifier 是质量事实源

Verifier / QA / Acceptance Coverage 是判断产物是否满足 frozen spec 的事实源。

Registry 只能消费 verified evidence，不能自己相信 builder 输出。

## 4. 目标架构

SkillFoundry v2 采用以下分层：

```text
Product Layer
  Front Desk
  user review
  API/UI
  registry product semantics

Domain Layer
  CoreNeed
  SolutionPlan
  FrozenSkillSpec
  SkillPackageManifest
  AcceptanceCriteria
  RegistryDecision

Workspace Layer
  artifact refs
  locked inputs
  path safety
  hash manifests
  resume briefs

Contract Bridge Layer
  FrozenSkillSpec -> GoalContract
  StageSpec -> AgentNodeContract
  VerificationSpec + AcceptanceCoverage -> VerificationGate

Orchestration Layer
  LangGraph stage graph
  refs-only state
  route by GoalRunRecord / VerificationResult / RegistryDecision

ContextForge Runtime Layer
  ContextLedger
  GoalHarness
  ContextView
  PromptCachePlan
  WorkerRun
  CheckpointRecord
  GoalRunRecord

Worker Layer
  FakeSkillBuilderWorker
  OwnedLLMSkillBuilderWorker
  CodexThreadSkillBuilderWorker
  ExternalAgentSkillBuilderWorker

Verification Layer
  SkillVerifier
  QA Lab
  AcceptanceCoverageEvaluator
  manual authority record
  ContextForge VerificationResult mapping

Registry Layer
  approval gate
  versioning
  quarantine
  reuse candidates
  feedback
```

## 5. 事实源边界

v2 必须明确四类事实源。

### 5.1 Workspace 是文件事实源

Workspace 保存：

- raw user conversation artifact；
- core need brief；
- solution plan；
- plan review；
- frozen spec；
- acceptance criteria；
- verification spec；
- build package；
- test output；
- verifier report；
- QA report；
- registry decision。

Workspace 文件必须：

- 使用安全相对路径；
- 有 artifact hash；
- 被 manifest 或 ledger 引用；
- 不通过 graph state 直接携带大内容。

### 5.2 ContextForge Ledger 是运行事实源

ContextForge ledger 保存：

- context items；
- prompt views；
- prompt cache plans；
- context views；
- worker runs；
- verification results；
- checkpoints；
- goal run records。

Ledger 不应该保存 SkillFoundry 的全部业务对象替代 workspace。它保存运行证据和引用。

### 5.3 LangGraph State 是控制事实源

Graph state 只保存：

```json
{
  "job_id": "job-123",
  "stage": "build",
  "status": "running",
  "refs": {
    "goal_contract": "contextforge/goal_contract.json",
    "build_node_contract": "contextforge/build_node_contract.json",
    "verification_gate": "contextforge/verification_gate.json"
  },
  "contextforge": {
    "last_goal_run_id": "goal-run-...",
    "last_worker_run_id": "worker-run-...",
    "last_context_view_id": "context-view-...",
    "last_prompt_cache_plan_id": "cache-plan-...",
    "last_verification_status": "failed",
    "next_route": "repair"
  }
}
```

禁止 graph state 保存：

- raw prompt；
- raw conversation；
- worker transcript；
- tool logs；
- package contents；
- replay bundle；
- raw model response。

### 5.4 Registry 是资产事实源

Registry 保存：

- skill id；
- version；
- approval status；
- package hash；
- verifier result ref/hash；
- acceptance coverage ref/hash；
- manual review refs；
- provenance；
- quarantine / rollback state。

Registry 不保存完整运行历史。运行历史在 workspace 和 ContextForge ledger。

## 6. 推荐 v2 模块结构

建议逐步收敛为：

```text
src/skillfoundry/
  domain.py
  workspace.py
  contracts.py
  graph.py
  frontdesk.py
  workers.py
  verification.py
  registry.py
  api.py
  cli.py

tests/
  test_contracts.py
  test_goal_harness_slice.py
  test_graph_v2.py
  test_workers_v2.py
  test_verification_v2.py
  test_registry_v2.py
  test_frontdesk_v2.py
```

短期不要立刻删除旧模块。建议先新增 v2 模块，跑通 vertical slice，再迁移或删除旧模块。

## 7. 旧模块处置表

| 旧模块 / 文档 | v2 处置 | 理由 |
| --- | --- | --- |
| `src/skillfoundry/schema.py` | port then simplify | 有 `SkillSpec`、`BuildContract`、`VerificationSpec`、hash/JSON 工具，值得保留语义，但不应继续承载所有边界。 |
| `src/skillfoundry/frontdesk_schema.py` | port selected domain | CoreNeed、SolutionPlan、AcceptanceCriterion 有价值；旧状态字段可重建。 |
| `src/skillfoundry/workspace.py` | keep and evolve | path safety、locked inputs、manifest 是关键资产。 |
| `src/skillfoundry/security.py` | keep | 路径安全必须保留。 |
| `src/skillfoundry/context.py` | rewrite | 旧假设是 owned LLM call adapter，不符合 Goal Harness 形态。 |
| `src/skillfoundry/worker.py` | port concepts, rewrite protocol | worker confinement、execution report 有价值，但应适配 ContextForge `WorkerAdapter`。 |
| `src/skillfoundry/llm_builder.py` | rewrite | 旧 prompt 拼接应改为 ContextView / PromptCachePlan。 |
| `src/skillfoundry/verifier.py` | keep domain, add bridge | Skill-specific verifier 是事实源；需要映射到 ContextForge `VerificationResult`。 |
| `src/skillfoundry/acceptance.py` | keep domain, add bridge | Acceptance Coverage 是 registry 前置硬门。 |
| `src/skillfoundry/qa.py` | keep domain, add bridge | QA evidence 应进入 VerificationGate / evidence refs。 |
| `src/skillfoundry/registry.py` | keep domain, modernize | Registry gate 规则正确；需要消费 ContextForge verification refs。 |
| `src/skillfoundry/graph.py` | rewrite | 旧 WP2 graph 是 skeleton；v2 graph 应以 Goal Harness node 为中心。 |
| `src/skillfoundry/frontdesk_loop.py` | rewrite orchestration | 思想保留，状态和 ContextForge 集成重建。 |
| `src/skillfoundry/api.py` | defer / rewrite after slice | API/UI 不应先驱动核心重构。 |
| `docs/DEVELOPMENT_ROADMAP.md` | historical / partial input | 记录 v0 路线，但不再约束 v2 技术实现。 |
| `docs/archive/agent-briefs/` | archive | 只用于追溯旧 WP0-WP17。 |

## 8. Contract Bridge 设计

`src/skillfoundry/contracts.py` 是 v2 第一阶段最重要的模块。

它负责把 SkillFoundry domain artifacts 转成 ContextForge contracts。

### 8.1 输入

输入 artifacts：

```text
frontdesk/core_need_brief.json
frontdesk/solution_plan.json
frontdesk/plan_review_*.json
frontdesk/risk_report.json
skill_spec.yaml
acceptance_criteria.yaml
verification_spec.yaml
build_contract.yaml
artifact_manifest.json
```

### 8.2 输出

输出 artifacts：

```text
contextforge/goal_contract.json
contextforge/build_node_contract.json
contextforge/repair_node_contract.json
contextforge/verification_gate.json
contextforge/cache_policy.json
contextforge/contract_manifest.json
```

### 8.3 GoalContract 映射

SkillFoundry -> ContextForge：

| SkillFoundry 来源 | ContextForge 字段 |
| --- | --- |
| `SkillSpec.title` / `CoreNeedBrief.problem` | `objective` |
| `AcceptanceCriteriaSet.must` | `success_criteria` |
| non-trigger scenarios / explicit exclusions | `non_goals` |
| constraints / security notes / risk policy | `constraints` |
| assumptions from plan | `assumptions` |
| budget artifact | `budgets` |
| verification gate id | `verification_gate_id` |
| freeze timestamp / plan review timestamp | `locked_at` |
| source hashes | `metadata.source_hashes` |

Rules:

- `success_criteria` must not be empty.
- source artifact hashes must be recorded.
- no raw conversation enters `objective`.
- contract hash must be computed through ContextForge `with_computed_hash`.

### 8.4 AgentNodeContract 映射

Build node contract:

```text
node_id: build_skill
role: skill_builder
mission: generate a candidate Codex Skill package from frozen inputs
visible_context:
  required: frozen skill spec
  required: acceptance criteria
  required: verification gate summary
  required: build contract
  optional: latest checkpoint
  optional: latest verifier failure when repairing
forbidden_context:
  raw frontdesk conversation
  secrets
  unapproved plan drafts
  rejected plan revisions
allowed_tools:
  filesystem write under package/ and attempts/
  test runner if enabled by contract
  no network by default
write_scope:
  package/
  attempts/<attempt_id>/
output_contract:
  candidate package artifact refs and execution summary
worker:
  fake_model | llm | codex_sdk_thread | external_agent
cache_policy:
  stable_prefix with cache_epoch_id derived from frozen contract hashes
```

Repair node contract:

```text
visible_context:
  frozen inputs
  previous WorkerRun refs
  verifier failures
  governed tool output
  checkpoint summary
forbidden_context:
  raw logs not governed
  raw conversation
  old rejected plans not referenced by current freeze
write_scope:
  package/
  attempts/<repair_attempt_id>/
```

Verifier-assist node contract, if any:

```text
role: verifier_assist
mission: produce advisory analysis only
output_contract: advisory report, never acceptance
verification_gate_id: none or advisory-only gate
metadata: cannot approve registry
```

### 8.5 VerificationGate 映射

SkillFoundry `VerificationSpec` + `AcceptanceCoveragePlan` maps to ContextForge `VerificationGate`:

```text
validators:
  schema/package static checks
  path confinement
  locked input hash checks
  acceptance coverage checks
  smoke checks
required_evidence:
  package/SKILL.md
  artifact_manifest.json
  verifier/verification_result.json
  qa/acceptance_coverage_result.json
artifact_hashes:
  frozen inputs
  package manifest
  verifier report
forbidden_paths:
  .env
  secrets
  parent traversal
forbidden_claims:
  self-approved
  verified without verifier evidence
  registry approved by builder
review_required:
  true when human review or manual authority is needed
human_authority_required:
  true when acceptance requires human-only authority
```

Important:

ContextForge's built-in `VerificationRunner` is generic. SkillFoundry-specific verifier remains product-domain logic. The bridge should record/mirror results into ContextForge `VerificationResult`, not delete SkillFoundry verifier prematurely.

## 9. v2 Runtime Flow

The first v2 vertical slice should be:

```text
Requirement fixture
  -> FrontDeskFakeFreeze
  -> FrozenSkillSpec artifacts
  -> contracts.py
      -> GoalContract
      -> AgentNodeContract(build)
      -> VerificationGate
  -> seed ContextLedger with frozen context items
  -> GoalHarness.run_single_node()
      -> FakeSkillBuilderWorker
      -> ContextView
      -> PromptView
      -> PromptCachePlan
      -> WorkerRun
  -> SkillFoundry Verifier / AcceptanceCoverage
  -> ContextForge VerificationResult mapping
  -> Registry gate
  -> GoalRunRecord
  -> CheckpointRecord
```

The first implementation can use `FakeWorker` or a thin `FakeSkillBuilderWorker`.

The point is not to prove generation quality. The point is to prove:

- contracts are valid；
- ContextView policy works；
- prompt cache plan is generated；
- worker evidence is recorded；
- verifier result blocks/permits registry；
- graph state remains ID-only；
- old v0 glue is no longer required for the core path。

## 10. PromptCachePlan Strategy

Prompt cache is a first-class product concern.

### 10.1 Stable Prefix

Stable prefix should include:

- platform/developer policy；
- worker role；
- `GoalContract` stable fields；
- `AgentNodeContract` stable fields；
- allowed tools；
- write scope；
- frozen skill spec summary；
- acceptance criteria；
- verification gate summary；
- output contract。

Stable prefix must avoid:

- current attempt id；
- recent failure text；
- raw logs；
- timestamp noise；
- unordered JSON；
- user conversation history；
- changing diagnostics。

### 10.2 Dynamic Suffix

Dynamic suffix should include:

- current stage intent；
- current attempt id；
- latest checkpoint summary；
- latest verifier failures；
- governed tool output；
- selected memory hits；
- current repair plan。

### 10.3 Cache Epoch

`cache_epoch_id` should change when:

- GoalContract hash changes；
- AgentNodeContract hash changes；
- VerificationGate hash changes；
- permission/write scope changes；
- user approves a new plan；
- security/risk policy changes；
- major workflow phase changes。

It should not change for:

- attempt id only；
- verifier failure suffix only；
- runtime timestamp；
- artifact path ordering changes with same content hash。

### 10.4 Metrics

Each run should expose:

- expected cacheable tokens；
- stable prefix block IDs；
- dynamic suffix block IDs；
- prefix churn；
- cache break reason；
- usage unavailable reason when provider does not report cache info。

## 11. Worker Strategy

SkillFoundry v2 should support four worker classes.

### 11.1 FakeSkillBuilderWorker

Purpose:

- deterministic tests；
- offline smoke；
- contract bridge validation。

It writes a small valid or invalid package based on fixture mode.

### 11.2 OwnedLLMSkillBuilderWorker

Purpose:

- white-box owned LLM execution；
- full PromptView / replay / usage / cache visibility。

Rules:

- no hand-built mega prompt from frozen files；
- use ContextForge `ContextView` and `PromptCachePlan`；
- every provider call goes through `ContextKernel.invoke_model` or a future ContextForge LLM worker；
- write only through workspace-safe adapter。

### 11.3 CodexThreadSkillBuilderWorker

Purpose:

- high-capability code/package generation；
- long tool loops；
- repo-level understanding。

Rules:

- ContextForge records boundary, not internal Codex prompt；
- must include transcript ref, diff refs, artifact refs, changed files；
- write scope must be enforced after run；
- usage may be unavailable, but must say why；
- verifier remains final gate。

### 11.4 ExternalAgentSkillBuilderWorker

Purpose:

- integrate other worker systems；
- preserve ContextForge boundary even when internals are black-box。

Rules:

- artifact refs required；
- evidence refs required；
- no self-approval；
- write scope and forbidden paths checked。

## 12. Checkpoint / Resume Strategy

Checkpoints should be created at:

- freeze complete；
- build complete；
- verifier failure；
- repair start；
- repeated failure；
- handoff；
- context pressure；
- budget threshold；
- manual review boundary。

Checkpoint content:

```text
goal contract hash
node contract hash
verification gate hash
current best result
latest diagnosis
failed attempts not to repeat
next plan
evidence refs
open risks
```

Resume should read checkpoint refs, not raw conversation.

## 13. Verification And Registry Strategy

### 13.1 Verifier

SkillFoundry verifier remains the product-domain verifier.

It should output:

- `verifier/verification_result.json`
- `verifier/static_report.json`
- `verifier/sandbox.log`
- optional judge report
- evidence refs

Then bridge to ContextForge:

```text
SkillFoundry VerificationResult
  -> ContextForge VerificationResult
  -> GoalRunRecord.verification_result_id
  -> route_by_verification
```

### 13.2 Acceptance Coverage

Acceptance Coverage remains mandatory before registry approval.

Rules:

- uncovered must criteria fail；
- covered/fail must criteria fail；
- manual-only must criteria require manual acceptance record；
- LLM-only must criteria are advisory unless explicitly configured；
- coverage result hash must be checked by registry。

### 13.3 Registry

Registry approval requires:

- ContextForge goal run reached completion or equivalent verified state；
- SkillFoundry verifier passed；
- acceptance coverage passed；
- artifact hashes match；
- no stale manual review；
- no forbidden paths；
- no builder self-approval。

Registry must reject:

- missing verification result；
- stale verification result；
- tampered coverage result；
- missing manual acceptance artifact；
- worker self-report as approval；
- package hash mismatch。

## 14. LangGraph v2 Shape

Recommended stage graph:

```text
START
  -> intake
  -> frontdesk_core_need
  -> solution_plan
  -> user_review
  -> freeze_contracts
  -> build_goal_node
  -> verify
  -> route_after_verification
      -> repair_goal_node -> verify
      -> registry_gate -> emit_report -> END
      -> human_review -> END
      -> reject -> END
```

State shape:

```python
class SkillFoundryV2State(TypedDict, total=False):
    job_id: str
    stage: str
    status: str
    attempt_count: int
    refs: dict[str, str]
    hashes: dict[str, str]
    contextforge: dict[str, str]
    next_route: str
    human_review_required: bool
```

State validator must reject:

- raw conversation；
- prompt；
- model output；
- worker transcript；
- package content；
- tool logs；
- replay bundle。

## 15. Phased Execution Plan

本节保留原始重构计划的 phase 顺序，用于追溯设计来源。当前执行时必须使用 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 的 canonical phase 编号。

Canonical phase map:

| 本节 original phase | Canonical phase | 当前状态 |
| --- | --- | --- |
| Original Phase 0: Entry Cleanup | Canonical Phase 0 | done |
| Original Phase 1: Contract Bridge | Canonical Phase 1 | implemented |
| Original Phase 2: Offline Goal Harness Slice | Canonical Phase 2 | implemented |
| Original Phase 3: LangGraph v2 Spine | Canonical Phase 4 | implemented / partial |
| Original Phase 4: Worker Migration | Canonical Phase 5 | implemented / partial |
| Original Phase 5: Verification Bridge And Registry Gate | Canonical Phase 6 | implemented |
| Original Phase 6: Front Desk Migration | Canonical Phase 3 | mostly implemented |
| Original Phase 7: API/UI Productization | Canonical Phase 7 | implemented / partial |

### Original Phase 0: Entry Cleanup And Dependency Alignment

Status: done.

Delivered:

- `third_party/contextforge` points to Goal Harness mainline。
- root `AGENT_BRIEF_WP*.md` moved to `docs/archive/agent-briefs/`。
- `docs/SKILLFOUNDRY_V2_BASELINE.md` created。
- ContextForge Goal Harness API import verified。
- existing tests pass with new submodule。

### Original Phase 1: Contract Bridge

Status: implemented. This phase created `src/skillfoundry/contracts.py` and `tests/test_contracts.py`; do not treat it as the current next PR.

Goal:

Create `src/skillfoundry/contracts.py`.

Deliverables:

- `build_goal_contract(...)`
- `build_agent_node_contract(...)`
- `build_verification_gate(...)`
- `write_contextforge_contract_artifacts(...)`
- `contextforge/contract_manifest.json`

Tests:

- contracts hash deterministically；
- required fields fail closed；
- raw conversation is not used；
- visible/forbidden selectors are correct；
- cache epoch derives from frozen hashes；
- generated payloads round-trip through ContextForge schemas。

Exit gate:

```text
pytest tests/test_contracts.py -q
```

and full suite remains green.

### Original Phase 2: Offline Goal Harness Vertical Slice

Status: implemented. `src/skillfoundry/goal_runtime.py`, the fake builder path, ContextForge run artifacts, and verified offline runtime now exist.

Goal:

Run one build node through ContextForge Goal Harness using fake worker.

Deliverables:

- `src/skillfoundry/goal_runtime.py`
- `FakeSkillBuilderWorker`
- ledger seeding from frozen artifacts；
- workspace artifacts for contextforge run IDs；
- first `GoalRunRecord` tied to SkillFoundry job。

Tests:

- `ContextView` includes frozen inputs；
- forbidden raw conversation excluded；
- `PromptCachePlan` generated；
- `WorkerRun` recorded；
- verifier failure routes to repair；
- verifier pass permits registry；
- graph state stores IDs only。

Exit gate:

```text
pytest tests/test_goal_harness_slice.py -q
```

and full suite remains green.

### Original Phase 3: LangGraph v2 Spine

Canonical phase: Phase 4.

Status: implemented / partial. `src/skillfoundry/graph_v2.py` exists and the Front Desk API happy path can now call graph v2 verified build / registry. Failed verification can now route into a Goal Harness-backed repair node that records governed repair evidence, but graph v2 is not yet the only product build/verify/repair/registry path and repair does not yet loop back through verifier/registry.

Goal:

Replace v0 graph skeleton for the new path with Goal Harness node boundaries.

Deliverables:

- `src/skillfoundry/graph_v2.py` or rewritten `graph.py`；
- stage routing by ContextForge verification result；
- checkpoint/resume IDs；
- state validator。

Tests:

- route success；
- route repair；
- route human review；
- reject raw state fields；
- resume from checkpoint refs。

Exit gate:

Graph tests and vertical slice tests pass.

### Original Phase 4: Worker Migration

Canonical phase: Phase 5.

Status: implemented / partial. `src/skillfoundry/workers_v2.py` has fake, owned LLM, Codex thread boundary, and external worker classes. Product-level worker selection and live pilots remain opt-in / unfinished.

Goal:

Move workers behind ContextForge worker protocol.

Order:

1. fake builder；
2. owned LLM builder；
3. Codex thread worker；
4. external agent worker。

Deliverables:

- `workers_v2.py` or rewritten `workers.py`；
- adapter from SkillFoundry workspace writes to ContextForge `WorkerRunResult`；
- changed files / artifact refs / transcript refs mapping；
- write scope enforcement。

Tests:

- fake success；
- fake failure；
- path escape fail closed；
- owned LLM usage/replay；
- Codex black-box boundary evidence；
- worker self-report cannot approve。

### Original Phase 5: Verification Bridge And Registry Gate

Canonical phase: Phase 6.

Status: implemented. `src/skillfoundry/verification_bridge.py` and registry evidence checks exist. Front Desk-generated acceptance criteria now map to deterministic verifier check IDs, so default frozen jobs can pass verified build/registry on the offline happy path.

Goal:

Make SkillFoundry verifier and acceptance coverage feed ContextForge verification records.

Deliverables:

- `verification_bridge.py` or part of `verification.py`；
- mapping to ContextForge `VerificationResult`；
- registry checks ContextForge refs and SkillFoundry evidence。

Tests:

- stale verification rejected；
- missing coverage rejected；
- manual-only missing artifact rejected；
- hash mismatch rejected；
- worker self-approval rejected。

### Original Phase 6: Front Desk Migration

Canonical phase: Phase 3.

Status: mostly implemented. Core Need Discovery, Solution Planner, and Spec Auditor Goal Harness slices exist; default no-key Front Desk API/loop paths use these slices; approved/frozen jobs can enter graph v2 verified build/registry through the API build endpoint.

Goal:

Front Desk LLM nodes become Goal Harness nodes.

Deliverables:

- Core Need Discovery node contract；
- Solution Planner node contract；
- Spec Auditor node contract；
- FreezeGate writes ContextForge contracts；
- conversation summary and redaction as governed context。

Tests:

- raw conversation excluded from builder；
- redaction incomplete blocks freeze；
- approved plan required；
- budget exceeded blocks continuation；
- provider usage/unavailable reason recorded。

### Original Phase 7: API/UI And Productization

Canonical phase: Phase 7.

Status: implemented / partial. API can create Front Desk jobs, record plan reviews, freeze approved plans, run graph v2 verified build/registry happy path, and expose v2 refs/status summaries. Repair/human-review route UX and richer evidence summaries remain unfinished.

Goal:

Expose the v2 flow through product API/UI.

Deliverables:

- job creation；
- message submission；
- plan review；
- build progress；
- verifier report；
- registry result；
- cache/cost summary；
- checkpoint/resume display。

Tests:

- API smoke；
- HTML or Playwright smoke；
- no raw prompt leakage；
- no registry without verifier。

## 16. Acceptance Criteria For The Full Rebuild

The rebuild is not complete until all are true:

- default test path is offline/deterministic；
- a fixture requirement can produce a verified Skill package through v2 path；
- every build/repair node has `GoalContract` and `AgentNodeContract`；
- every worker run has `WorkerRun` and `GoalRunRecord`；
- every LLM prompt has `PromptView` and `PromptCachePlan`；
- raw conversation never enters builder context；
- forbidden context fails closed；
- verifier failure blocks registry；
- acceptance coverage failure blocks registry；
- manual-only acceptance requires signed artifact；
- graph state contains only refs/IDs；
- checkpoint exists at build/verify/repair boundaries；
- cache metrics are visible per run；
- old v0 context adapter is no longer on the v2 critical path。

## 17. Risk Register

| Risk | Impact | Defense |
| --- | --- | --- |
| Rebuilding too much at once | Long unstable branch | Vertical slice first; keep v0 tests green until replacement is proven. |
| Treating ContextForge as production platform | False architecture claims | Explicitly keep API/UI/scheduler/sandbox in SkillFoundry or future layers. |
| Losing SkillFoundry verifier semantics | Registry becomes weaker | Keep SkillFoundry verifier as product-domain fact source; bridge to ContextForge. |
| Two competing runtime fact sources | Graph routing and registry approval become ambiguous | v2 routing uses ContextForge GoalRunRecord / VerificationResult IDs while SkillFoundry verifier remains product-domain evidence bridged into those records. |
| Codex black-box overclaim | Audit false confidence | Record boundary only; never claim internal prompt/cache replay. |
| Prompt cache poisoned by dynamic noise | Cost savings disappear | Stable prefix policy and cache epoch rules tested. |
| Graph state grows again | checkpoint/resume becomes brittle | State validator rejects raw fields. |
| Raw conversation leaks into builder | privacy and quality risk | forbidden context selector + workspace path policy + tests. |
| Worker self-report bypasses gates | bad assets registered | registry requires verifier and coverage evidence. |
| Manual review becomes stale | invalid approvals | hash gate review against current contract/gate hash. |
| v0 docs confuse contributors | implementation drift | README/HANDOFF and v2 plan mark v0 as historical. |

## 18. Review Checklist

An independent reviewer should check:

- Does this plan preserve the original SkillFoundry agent collaboration idea?
- Does it correctly use ContextForge Goal Harness instead of rebuilding ContextForge inside SkillFoundry?
- Are ContextForge limitations stated clearly?
- Are SkillFoundry product-domain responsibilities still owned by SkillFoundry?
- Is verifier independence preserved?
- Is registry protected from worker self-report?
- Is prompt cache strategy concrete enough to implement?
- Are phase exit gates testable?
- Are old modules categorized realistically?
- Are there any hidden compatibility assumptions from v0?
- Is the first vertical slice small enough to finish?

## 19. Historical Immediate Next PR And Current Next Slice

Historical note:

The original next code PR was Phase 1 only:

```text
src/skillfoundry/contracts.py
tests/test_contracts.py
```

That work has been completed. The warning below remains historically useful because it explains why the first slice was deliberately narrow:

- rewrite graph；
- migrate Front Desk；
- change API/UI；
- replace verifier；
- integrate real Codex；
- call live providers。

Minimal output:

```text
runs/<job_id>/contextforge/goal_contract.json
runs/<job_id>/contextforge/build_node_contract.json
runs/<job_id>/contextforge/verification_gate.json
runs/<job_id>/contextforge/contract_manifest.json
```

Historical warning: if Phase 1 cannot produce valid ContextForge contracts from frozen SkillFoundry artifacts, do not proceed to worker migration.

Completed implementation slice:

```text
Make a default offline Front Desk job flow from:
create job -> governed Front Desk plan -> approved review -> freeze
-> verified Goal Harness build -> verifier -> acceptance coverage
-> ContextForge VerificationResult -> registry approval or explicit failure.
```

Resolved gaps:

- Front Desk-generated `acceptance_criteria.yaml` must contain deterministic `verifier_check_id` values.
- If a criterion asserts raw conversation exclusion, the verifier/bridge needs a deterministic check for that boundary or the criterion must reference an existing equivalent check.
- The registry gate must pass only when verifier, acceptance coverage, and ContextForge verification evidence all match current artifacts.
- `POST /frontdesk/jobs/{job_id}/build` must route approved/frozen Front Desk jobs through graph v2 and persist refs-only `contextforge/graph_v2_state.json`.
- Failed graph v2 verification can execute a ContextForge Goal Harness-backed repair node and persist governed repair context, WorkerRun evidence, checkpoint IDs, repair instructions, repair runtime result, and `attempts/002/repair_attempt.json` without granting worker self-approval or registry approval.

These slices did not introduce live provider calls or real Codex SDK execution.

Current next implementation direction:

```text
Make graph_v2 the only product build/verify/repair/registry route,
connect repair output back through verifier / acceptance coverage / registry,
and isolate or retire legacy graph/context/worker paths.
```

## 20. Independent Reviewer Notes

Historical reviewer: third-party `gpt-5.5 xhigh`.

Decision:

```text
approve_with_required_clarifications
```

Reviewer conclusion:

```text
SkillFoundry v2 基于新版 ContextForge Goal Harness 重建技术骨架，方向成立。
应该尽快从“继续 patch v0 模块”切换为“先跑通 v2 contract bridge + offline vertical slice”。
```

Historical required clarifications accepted into the original version of this document:

- 明确 v2 技术重建必须有单一执行源，旧 roadmap 只作为历史输入。当前单一执行源已经转为 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`。
- 第一阶段严格限定为 contract bridge，不迁移 graph、Front Desk、API/UI、real Codex 或 live provider。
- 第一条运行闭环严格限定为 offline deterministic vertical slice。
- 不继续扩展旧 `src/skillfoundry/context.py` 作为 v2 主路径。
- 不继续沿用旧 `src/skillfoundry/worker.py` 协议作为 v2 worker 协议。
- 不继续沿用旧 `src/skillfoundry/llm_builder.py` 的手写 mega prompt 作为 v2 builder 输入方式。
- SkillFoundry verifier / acceptance / registry 的业务规则必须保留，但要桥接到 ContextForge verification records，避免两套事实源。
- Codex SDK thread 永远按 black-box worker 处理，只记录边界证据，不声称 replay 内部 prompt/cache/tool loop。
- PromptCachePlan 必须定义 stable prefix、dynamic suffix、cache epoch、cache break reason 和 usage unavailable reason。

Reviewer checklist disposition:

| Reviewer check | Disposition |
| --- | --- |
| v2 重建结论是否明确 | Accepted in sections 0, 1.1, 2. |
| 文档权威是否明确 | Accepted in section 1.1. |
| 必须保留的产品/质量边界是否明确 | Accepted in section 3. |
| 废弃实现和替代目标是否明确 | Accepted in section 7. |
| `contracts.py` 字段级映射是否明确 | Accepted in section 8. |
| offline vertical slice 是否清楚 | Accepted in sections 9 and 15 Phase 2. |
| graph state 是否 ID-only | Accepted in sections 5.3 and 14. |
| ledger/artifact store 事实源是否明确 | Accepted in section 5. |
| Acceptance Coverage / manual gate / forbidden claim 是否进入 verification strategy | Accepted in sections 8.5 and 13. |
| Registry 是否防 worker self-report | Accepted in sections 13.3 and 16. |
| worker taxonomy 是否明确 | Accepted in section 11. |
| PromptCachePlan 策略是否可实现 | Accepted in section 10. |
| checkpoint/resume 边界是否明确 | Accepted in section 12. |
| Front Desk 风险防线是否保留 | Accepted in sections 3.1, 3.2, 15 Phase 6. |
| 当前非目标是否明确 | Accepted in sections 2.2, 15, 19. |

Remaining reviewer concern:

```text
README.md / HANDOFF.md / DEVELOPMENT_ROADMAP.md still contain v0 wording in places.
They should either link to this rebuild plan or be explicitly marked historical for v2 implementation.
```

This concern is addressed by:

- section 1.1 in this document；
- README/HANDOFF updates that point v2 execution to `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` and use this document as historical plan/evidence；
- deferring broad rewrites of old roadmap files until they can be edited without mixing unrelated in-progress changes.

Current reviewer gate:

```text
reviewer: Russell / independent gpt-5.5 xhigh reviewer
initial_decision: approve_with_required_changes
final_decision: approve
required_changes:
  - mark this document as historical execution plan or synchronize it with current canonical state;
  - unify phase numbering through a canonical map;
  - add current implementation matrix;
  - replace stale Immediate Next PR;
  - downgrade DEVELOPMENT_ROADMAP authority;
  - label old reviewer conclusions as historical.
status: fixed in this revision, no remaining blockers
```
