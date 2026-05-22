# SkillFoundry x ContextForge 重构蓝图

最后更新：2026-05-22

状态：v2 canonical refactor baseline

目标读者：第一次接手 SkillFoundry 的工程师或 agent。读者不需要读完整历史对话，也不需要先理解 WP0-WP17 的旧执行过程。

## 0. 人话结论

SkillFoundry 应该围绕当前 ContextForge Goal Harness 重建，但不应该重做 Codex、Claude Code 或任何黑盒 agent 产品。

新的总判断是：

```text
ContextForge = agent 工作外骨骼
LangGraph = 多阶段骨架
Codex SDK thread / GPT-5.5 / external worker = 肌肉和智能
Verifier = 免疫系统
Ledger / Replay / Checkpoint = 神经记录
PromptCachePlan = 成本控制器
SkillFoundry = 第一座工厂和第一个产品化场景
```

这套体系可以良好运转，但前提是边界必须硬：

- Front Desk 把用户的模糊需求整理成受治理 artifact。
- 用户审查和 FreezeGate 把需求冻结成稳定合同。
- LangGraph 只管大阶段、路由、重试和人工门。
- ContextForge 给每个强 agent node 套上上下文视界、缓存计划、工具权限、写范围、checkpoint、证据和验证边界。
- Worker 负责做事，但不拥有事实权。
- Verifier 和 Registry 决定产物是否真的通过、是否可以复用。

一句话：

```text
不要把强模型拆碎成一堆弱 agent。
也不要把复杂任务完全交给黑盒 agent。
用 ContextForge 给强 worker 戴上可控、可审计、可缓存、可验证的工作外骨骼。
```

## 1. 本文权威和阅读顺序

本文是 SkillFoundry 基于当前 ContextForge Goal Harness 重构的集成蓝图。

它回答的是：

```text
在 SkillFoundry 没有线上兼容包袱的前提下，
如何保留原有 agent 协作思想，
并用新版 ContextForge Goal Harness 重建产品级技术路径。
```

本文不替代：

- ContextForge 自身架构文档；
- SkillFoundry 产品白皮书；
- 每个阶段的 PR 说明；
- 上线前必须补齐的 security / ops / deployment 文档。

如果本文和旧 WP 路线冲突：

```text
v2 技术实现以本文和当前 Goal Harness 方向为准。
旧 WP0-WP17 文档只作为历史经验和业务规则输入。
```

推荐新用户阅读顺序：

1. `README.md`
2. `HANDOFF.md`
3. 本文
4. `docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md`
5. `docs/SKILLFOUNDRY_V2_BASELINE.md`
6. `docs/CONTEXTFORGE_AGENT_EXOSKELETON_PRODUCT_VISION.md`
7. `third_party/contextforge/README.md`
8. `third_party/contextforge/docs/architecture.md`
9. `third_party/contextforge/docs/goal-harness-quickstart.md`

`docs/DEVELOPMENT_ROADMAP.md`、`docs/ROADMAP.md`、`docs/ROADMAP_EXECUTION_PLAN.md`、`docs/FRONT_DESK_AGENT_ROADMAP.md` 和 `docs/archive/agent-briefs/` 是历史材料，不再约束 v2 模块边界。

不要读错：

- 不要从 WP0-WP17 agent briefs 开始理解当前仓库。
- 不要按旧 rebuild plan 的 “Immediate Next PR = Phase 1 contracts” 开工；那是历史记录，Phase 1/2 已经落地。
- 当前 phase 编号以本文第 11 节为准。
- 当前下一步不是重做 ContextForge 或重做 Codex，而是让 graph v2 成为唯一产品 build / verify / repair / registry 主路径，并补齐 human-review/API-UI evidence 体验与 legacy 隔离。

### 1.1 已核对的 ContextForge 事实

本文对 ContextForge 的判断已按当前 submodule 核对：

```text
third_party/contextforge = 2a0838bce6a7a2607b9ca1e095e044080fdc6759
```

已核对事实：

- `third_party/contextforge/docs/architecture.md` 明确 ContextForge 当前定位是 Agent Exoskeleton Runtime。
- ContextForge 主路径是 `GoalContract + AgentNodeContract -> ContextView -> PromptView / PromptCachePlan -> WorkerRun -> VerificationResult -> CheckpointRecord -> GoalRunRecord`。
- `CodexThreadWorker` 是 boundary-only worker；ContextForge 不声称掌握 Codex 内部 prompt、cache、compaction 或 tool loop。
- `PromptCachePlan` 记录 stable prefix、dynamic suffix、cache epoch、cache telemetry 和 cache break reason；它是成本控制计划和遥测载体，不保证 provider 一定命中缓存。

## 2. 当前代码事实

SkillFoundry 当前处于混合状态。

它不是一个已经完成的新架构，也不是一个必须兼容的线上系统。它同时包含：

- v0 原型中验证过的产品资产；
- 已经落地的一批 v2 Goal Harness 桥接模块；
- 仍在运行路径上的旧 Front Desk、worker、graph、prompt/context 代码。

### 2.1 有价值的 v0 资产

这些思想应该保留：

- Front Desk 负责发现真实需求，而不是直接把用户原话丢给 builder。
- 不清楚需求不能进入 build。
- 方案需要用户审查。
- FreezeGate 是确定性门。
- Workspace 文件是上下文和 artifact 的事实源。
- 路径安全、locked input、hash manifest 必须保留。
- Worker self-report is never acceptance。
- Verifier / QA / Acceptance Coverage 是独立质量门。
- Registry 只批准 verified asset。
- 默认测试必须离线、确定性、可复现。

### 2.2 已经存在的 v2 核心模块

`src/skillfoundry/contracts.py`

- 把 frozen SkillFoundry artifacts 映射成 ContextForge `GoalContract`、`AgentNodeContract`、`VerificationGate`。
- 明确禁止 raw Front Desk conversation 进入 builder context。
- 基于 frozen hash、可见上下文、权限和写范围生成 cache epoch。

`src/skillfoundry/goal_runtime.py`

- 跑通离线 deterministic build node。
- 记录 `ContextView`、`PromptView`、`PromptCachePlan`、`WorkerRun`、`VerificationResult`、`GoalRunRecord`、checkpoint。

`src/skillfoundry/workers_v2.py`

- 提供 `FakeSkillBuilderWorker`、`OwnedLLMSkillBuilderWorker`、`CodexThreadSkillBuilderWorker`、`ExternalAgentSkillBuilderWorker`。
- 正确区分 owned LLM 的白盒调用和 Codex / external worker 的黑盒边界。

`src/skillfoundry/graph_v2.py`

- 提供 refs-only LangGraph spine。
- 根据 ContextForge verification status 和 registry/verifier evidence 路由。
- 明确拒绝 raw prompt、raw transcript、raw logs、package content 进入 state。

`src/skillfoundry/frontdesk_v2.py`

- 为 Front Desk 三个节点生成 ContextForge contracts：
  - core need discovery；
  - solution planner；
  - spec auditor。
- 明确把 raw conversation 标为 forbidden provenance。

`src/skillfoundry/frontdesk_goal_runtime.py`

- 已经能用 Goal Harness 跑 Front Desk v2 deterministic slices。
- Core Need Discovery、Solution Planner、Spec Auditor 都有离线 runtime。
- Spec Auditor 需要 approved plan review 和 source hash 才能成功。

`src/skillfoundry/verification_bridge.py`

- 把 SkillFoundry verifier 和 acceptance coverage 结果桥接成 ContextForge `VerificationResult`。
- 拒绝缺失、过期、伪造、self-report 替代的验证证据。

`src/skillfoundry/registry.py`

- 可以要求 ContextForge verification evidence。
- 仍然保留 registry 作为资产事实源的角色。

### 2.3 仍未完成的迁移

当前不能说“重构已经完成”。

事实是：

```text
核心 Goal Harness bridge 已经存在。
Front Desk v2 slices 已经存在。
verified offline build path 已经存在。
产品主路径还没有完全收敛到这套新骨架。
```

仍需迁移或收敛的旧路径：

- `src/skillfoundry/frontdesk_loop.py`
  - 仍包含旧 orchestration 形态。
  - approved plan 后的 audit/freeze 路径需要收敛到 Front Desk Spec Auditor Goal Harness runtime。
  - legacy elicitor / auditor 路径仍可能把 raw conversation 交给旧 prompt 组装逻辑，即使它带 trust label；这不是 v2 允许的长期边界。

- `src/skillfoundry/context.py`
  - 仍是旧 owned LLM call adapter 假设。
  - 不应继续作为新上下文架构的中心。

- `src/skillfoundry/worker.py`
  - 旧 WorkerAdapter 协议仍有价值，但不应继续决定 v2 worker 边界。

- `src/skillfoundry/llm_builder.py`
  - 旧 prompt 拼接方式应被 ContextView / PromptCachePlan 替代。

- `src/skillfoundry/graph.py`
  - 旧 graph 是历史骨架。
  - v2 产品路径应以 `graph_v2.py` 为主。

- API/UI
  - 已有部分 ContextForge observability。
  - 还不是完整 v2 产品外壳。

### 2.4 当前实现矩阵

| 区域 | 当前状态 | 说明 | 下一步 |
| --- | --- | --- | --- |
| `third_party/contextforge` | implemented | 已指向 Goal Harness 主线，提供 GoalContract、AgentNodeContract、GoalHarness、PromptCachePlan、WorkerRun、VerificationResult、Checkpoint 等核心对象。 | 继续按 submodule API 使用，不在 SkillFoundry 内重造。 |
| `src/skillfoundry/contracts.py` | implemented | frozen SkillFoundry artifacts 能映射到 ContextForge contracts，并排除 raw Front Desk conversation。 | 保持 contract hash/cache epoch/forbidden context 回归测试。 |
| `src/skillfoundry/goal_runtime.py` | implemented / partial | 离线 Goal Harness build/verify/registry runtime 已存在；repair worker boundary 能记录 WorkerRun、ContextView、PromptCachePlan、checkpoint 和 `RepairAttempt` 证据，且 repaired output 能重新进入 verifier、acceptance coverage、ContextForge bridge 和 registry gate。 | 继续作为 graph v2 产品路径的 verified build/repair runtime，并收敛 legacy 路径。 |
| `src/skillfoundry/workers_v2.py` | implemented / partial | Fake、owned LLM、Codex thread boundary、external agent worker 边界已存在；默认路径仍应离线 deterministic。 | live provider / real Codex 继续保持 opt-in pilot，不进入默认测试。 |
| `src/skillfoundry/graph_v2.py` | implemented / partial | refs-only spine、verified build/registry nodes、API happy path runner 已存在；failed verification route 可以进入 Goal Harness-backed repair node，并能在 repaired output 通过 verifier/coverage/bridge 后进入 registry gate；graph v2 仍不是唯一产品主骨架。 | 将旧 `graph.py` 退役或隔离为 compatibility wrapper，并继续完善 human-review/API-UI evidence。 |
| `src/skillfoundry/frontdesk_v2.py` | implemented | Front Desk 三类 Goal Harness contract 已存在。 | 保持 raw conversation 为 forbidden provenance。 |
| `src/skillfoundry/frontdesk_goal_runtime.py` | implemented | Core Need、Solution Planner、Spec Auditor Goal Harness slices 已存在，默认 no-key Front Desk 路径已接入；Front Desk-generated criteria 已映射到 deterministic verifier checks。 | 后续保持 raw conversation forbidden 和 approved-review/freeze gate。 |
| `src/skillfoundry/verification_bridge.py` | implemented | SkillFoundry verifier / acceptance coverage 能桥接到 ContextForge VerificationResult，并消费 Front Desk deterministic verifier check IDs。 | 加强语义验收和 post-verifier evidence hash binding。 |
| `src/skillfoundry/registry.py` | implemented / partial | Registry 已要求 verifier / coverage / ContextForge evidence，拒绝 self-report/stale/fabricated evidence；默认 Front Desk frozen job 可通过 graph v2 API happy path register。 | 继续覆盖 repair/human-review/manual acceptance 场景。 |
| API/UI | implemented / partial | API 可以创建 Front Desk job、plan review，并通过 `/frontdesk/jobs/{job_id}/build` 运行 graph v2 verified build/registry happy path；ContextForge status 暴露 v2 refs/status 摘要。 | 继续完善 UI 的 registry outcome、repair/human-review route 和 evidence 摘要。 |
| live provider / real Codex SDK thread | future opt-in | 当前不是默认路径，也不是生产承诺。 | 等离线 v2 主路径稳定后做内部 pilot，并记录 usage unavailable reason / telemetry。 |

## 3. ContextForge 当前能力边界

ContextForge 当前已经是适合 SkillFoundry v2 的内核，但它不是完整平台。

### 3.1 应直接复用的能力

ContextForge 已经提供：

- `GoalContract`
- `AgentNodeContract`
- `ContextView`
- `PromptView` / `PromptBlock`
- `PromptCachePlan`
- `ToolPermission`
- `WriteScope`
- `GoalHarness`
- `WorkerRun`
- `GoalRunRecord`
- `VerificationGate`
- `VerificationResult`
- `CheckpointRecord`
- `FakeWorker`
- `CodexThreadWorker`
- `ExternalAgentWorker`
- LangGraph 风格 refs-only adapter
- MetaLoop compatibility mapping

SkillFoundry 不应重造这些底层抽象。

### 3.2 不应对 ContextForge 过度承诺

ContextForge 当前还不是：

- SaaS 服务；
- UI 产品；
- 多用户权限系统；
- 后台 daemon / scheduler / agent pool；
- 生产沙箱；
- LangGraph 替代品；
- 完整 provider SDK worker；
- 真正执行 Codex SDK thread 的完整运行器。

尤其重要：

```text
ContextForge 不控制 Codex SDK thread 内部 prompt、cache、compaction 或 tool loop。
```

对 Codex SDK thread 这类强 worker，ContextForge 的姿势应该是 boundary-first：

- 记录输入合同；
- 记录可见上下文和 forbidden context；
- 记录工具权限和写范围；
- 记录 transcript/diff/artifact refs；
- 记录 changed files；
- 记录 usage unavailable reason；
- 交给 Verifier 判断真假。

## 4. 非谈判约束

这些约束比任何具体文件更重要。

### 4.1 Worker self-report is never acceptance

无论 worker 是什么，都不能自证通过：

- fake worker；
- owned LLM worker；
- Codex SDK thread worker；
- GPT-5.5 direct worker；
- Claude Code style worker；
- external agent worker。

允许 worker 返回：

- 做了什么；
- artifact refs；
- changed files；
- transcript refs；
- diff refs；
- usage summary；
- failure class；
- open questions。

禁止 worker 决定：

- verifier passed；
- registry approved；
- acceptance covered；
- human authority satisfied；
- production ready。

这里的真实防线不是某个 `worker_self_report_is_not_acceptance=true` 标记本身，而是：

- verifier 必须基于 frozen inputs 和 artifacts 独立运行；
- acceptance coverage 必须独立通过；
- registry 只消费当前且可复验的 verifier / coverage / ContextForge verification evidence。

### 4.2 Raw Front Desk conversation

Raw Front Desk conversation 是 provenance，不是 builder-visible context。

允许：

```text
raw conversation
  -> governed / redacted Front Desk summaries
  -> core_need_brief.json
  -> solution_plan.json
  -> approved plan_review record
  -> frozen skill spec / acceptance criteria
  -> builder-visible ContextView
```

禁止：

```text
raw conversation
  -> builder prompt
```

Raw conversation 不得进入：

- builder prompt；
- repair prompt；
- registry decision；
- LangGraph state；
- build node included context；
- 未治理的 downstream Front Desk prompt。

### 4.3 LangGraph state

LangGraph state 只保存 refs / IDs。

允许：

- `job_id`
- `stage`
- `status`
- `route`
- `attempt_count`
- artifact refs
- hashes
- ContextForge IDs
- verification status
- human review flag

禁止：

- raw prompt；
- raw conversation；
- raw model response；
- worker transcript；
- package content；
- raw tool logs；
- replay bundle content；
- 大段临时总结。

### 4.4 默认离线路径

默认测试必须：

- deterministic；
- offline；
- 不需要 provider key；
- 不需要真实 Codex SDK；
- 不依赖网络；
- 可在本地全量复现。

真实 provider 和 Codex SDK thread 只能作为 opt-in smoke / pilot。

## 5. 目标架构

目标架构不是传统的“很多弱 agent 互相聊天”。

目标架构是：

```text
User / Product Owner
  -> SkillFoundry API/UI
  -> Front Desk
      -> Core Need Discovery Goal Harness node
      -> Solution Planner Goal Harness node
      -> User Review Gate
      -> Spec Auditor Goal Harness node
      -> deterministic FreezeGate
  -> Contract Bridge
      -> GoalContract
      -> AgentNodeContract(s)
      -> VerificationGate
      -> cache epoch inputs
  -> LangGraph v2
      -> build goal node
      -> verify route
      -> repair goal node
      -> human review
      -> registry gate
      -> final report
  -> ContextForge Goal Harness
      -> ContextLedger
      -> ContextView
      -> PromptView
      -> PromptCachePlan
      -> WorkerRun
      -> VerificationResult
      -> CheckpointRecord
      -> GoalRunRecord
  -> Worker Layer
      -> FakeSkillBuilderWorker
      -> OwnedLLMSkillBuilderWorker
      -> CodexThreadSkillBuilderWorker
      -> ExternalAgentSkillBuilderWorker
  -> Verifier / QA / Acceptance Coverage
  -> Registry
```

干净的依赖方向：

```text
Product domain
  -> workspace artifacts
  -> contract bridge
  -> ContextForge runtime
  -> verifier bridge
  -> registry
```

应该避免的方向：

```text
legacy prompt builder
  -> direct model call
  -> ad hoc result
  -> registry
```

## 6. 产品主流程

### 6.1 Intake

用户提交自然语言需求。

系统把原始对话保存在 Front Desk workspace artifact 中，但不把它塞进 graph state。

第一目标不是 build，而是理解真实需求。

### 6.2 Core Need Discovery

输出：

- `frontdesk/core_need_brief.json`
- `frontdesk/core_need_discovery_report.json`

未来即使用强模型，也必须跑在 ContextForge node contract 内：

- visible governed summaries；
- raw conversation forbidden；
- Front Desk write scope only；
- budget evidence；
- checkpoint。

### 6.3 Solution Planning

输出：

- `frontdesk/solution_plan.json`
- `frontdesk/solution_plan.md`
- `frontdesk/draft_skill_spec.yaml`
- `frontdesk/acceptance_criteria.yaml`

注意：

```text
solution plan 是 draft，不是 freeze approval。
```

### 6.4 User Review Gate

用户审查生成 `PlanReviewRecord`。

Spec Auditor 和 FreezeGate 必须验证：

- decision 是 approve；
- review ref 是当前 routed review record；
- solution plan ref 指向当前 `solution_plan.json`；
- source hash 匹配当前 solution plan bytes。

没有 approved plan review，就不能 audit/freeze 成功。

### 6.5 Spec Audit

Spec Auditor 可见：

- core need brief；
- approved solution plan；
- routed plan review；
- draft skill spec；
- acceptance criteria。

Spec Auditor 输出：

- `frontdesk/spec_audit_report_001.json`
- `frontdesk/feasibility_report.json`

缺少 plan approval 或 source hash 证据时必须 fail closed。

### 6.6 Freeze

FreezeGate 是确定性门，不是 LLM opinion。

Freeze 产出：

- frozen skill spec；
- acceptance criteria；
- verification spec；
- build contract；
- artifact manifest；
- hash refs。

### 6.7 Build

LangGraph 路由到 build Goal Harness node。

Build node 接收：

- `GoalContract`
- build `AgentNodeContract`
- `VerificationGate`
- frozen workspace artifacts
- allowed tools
- write scope
- cache policy

Worker 只能写 candidate package artifacts 和 attempt evidence。

### 6.8 Verify

SkillFoundry verifier 和 acceptance coverage 基于 frozen inputs 与 candidate package artifacts 运行。

结果通过 `verification_bridge.py` 映射为 ContextForge `VerificationResult`。

### 6.9 Repair

Repair 是另一个 Goal Harness node，不是简单继续拼接 builder prompt。

Repair 可以看：

- frozen inputs；
- prior `WorkerRun` refs；
- verifier failures；
- governed tool output；
- checkpoint summary。

Repair 不能看：

- raw Front Desk conversation；
- ungoverned logs；
- 未被当前 freeze 引用的旧 rejected plans。

### 6.10 Registry

Registry 只批准 verified asset。

必要条件：

- package hash 匹配；
- SkillFoundry verifier passed；
- acceptance coverage passed；
- ContextForge verification evidence 当前且有效；
- manual authority record 存在，若需要；
- no forbidden paths；
- no stale evidence；
- no worker self-approval。

## 7. 上下文和缓存策略

用户之前担心的问题是对的：

```text
模型是无状态函数。
上下文管理直接决定质量、成本和可恢复性。
```

但答案不是“无限 append”，也不是“每次都让模型总结全部历史”。

正确策略：

```text
完整历史进入 ledger / artifacts。
当前调用只编译 bounded ContextView。
稳定合同内容进入 stable prefix。
attempt-specific 状态进入 dynamic suffix。
checkpoint summary 只在事件触发时更新。
cache epoch 只在 frozen boundary 改变时换代。
```

### 7.1 Stable prefix

Stable prefix 应包含：

- node policy；
- worker role；
- goal objective；
- success criteria；
- non-goals；
- constraints；
- tool permissions；
- write scope；
- frozen skill spec summary；
- acceptance criteria；
- verification gate summary；
- output contract。

Stable prefix 应避免：

- timestamp；
- attempt id；
- raw logs；
- current failure text；
- unordered JSON；
- raw conversation；
- volatile diagnostics。

### 7.2 Dynamic suffix

Dynamic suffix 应包含：

- current stage intent；
- current attempt id；
- latest verifier failure summary；
- governed tool diagnostics；
- latest checkpoint summary；
- current repair plan；
- 显式请求的 selected memory hits。

### 7.3 Cache epoch

`cache_epoch_id` 应该在这些情况变化：

- `GoalContract` hash 变化；
- `AgentNodeContract` hash 变化；
- `VerificationGate` hash 变化；
- 用户批准了新方案；
- tool permissions 变化；
- write scope 变化；
- risk/security policy 变化；
- major workflow phase 变化。

不应该因为这些变化：

- attempt id；
- 当前 timestamp；
- retry count；
- verifier failure suffix；
- 相同内容的 artifact ordering noise。

### 7.4 必须记录的指标

每次 run 至少记录：

- stable prefix block IDs；
- dynamic suffix block IDs；
- stable prefix hash；
- dynamic suffix hash；
- provider payload hash；
- expected cacheable tokens；
- actual cached tokens，若 provider 返回；
- cache telemetry status；
- usage unavailable reason，若 provider 不返回；
- cache break reason。

这使 PromptCachePlan 成为可测成本控制器，而不是口头上的“记忆系统”。

## 8. Agent Node 设计判断

“只要定好 agent node 的角色、要求、可见内容、权限和视界管理，是否能覆盖 90% 以上场景？”

结论：

```text
对 SkillFoundry 这类系统，基本是的。
```

一个可执行 agent node 需要的核心字段是：

- `node_id`
- `goal_id`
- `role`
- `mission`
- `visible_context`
- `forbidden_context`
- `allowed_tools`
- `write_scope`
- `output_contract`
- `worker`
- `budgets`
- `cache_policy`
- `checkpoint_policy`
- `stop_conditions`
- `verification_gate_id`
- `handoff_policy`

难点不是继续加字段，而是执行这些字段：

- required context 缺失时 fail closed；
- forbidden context 泄漏时 fail closed；
- write scope 违规时 fail closed；
- plan review 缺失时 fail closed；
- verification 过期时 fail closed；
- manual authority 缺失时 fail closed。

## 9. Worker 策略

所有 worker 都应该挂在同一套 ContextForge worker boundary 后面。

### 9.1 Fake worker

用途：

- deterministic tests；
- offline demo；
- contract bridge validation；
- regression safety。

这是默认路径。

### 9.2 Owned LLM worker

用途：

- SkillFoundry 自有 LLM 调用；
- 白盒 prompt/cache/replay；
- provider usage 和 cache telemetry，若可得。

规则：

- 不再手写 mega prompt；
- 使用 `ContextView` 和 `PromptCachePlan`；
- provider call 经过 ContextForge model-call boundary；
- 只通过 workspace-safe artifact function 写文件；
- 输出必须被解析成结构化 candidate artifacts。

### 9.3 Codex SDK thread worker

用途：

- 高能力 build / repair；
- 长时间 repo 级阅读、修改、测试；
- 复杂工具循环交给强 agent 自己完成。

规则：

- ContextForge 只记录 boundary evidence；
- transcript/diff/artifact refs 尽量必填；
- changed files 运行后检查 write scope；
- usage 不可得时必须写明原因；
- Verifier 仍然是最终事实源。

这就是为什么不应该“重写 Codex”，但也不应该“纯黑盒依赖 Codex”。

### 9.4 External agent worker

用途：

- 接入其他 agent 系统；
- 保留 SkillFoundry 的 verification 和 registry gate。

规则：

- artifact refs 必须存在；
- evidence refs 必须存在；
- no self-approval；
- write scope enforced。

## 10. 模块处置

### 10.1 保留并演进

这些模块的领域价值应保留：

- `src/skillfoundry/workspace.py`
- `src/skillfoundry/security.py`
- `src/skillfoundry/schema.py`
- `src/skillfoundry/frontdesk_schema.py`
- `src/skillfoundry/frontdesk_workspace.py`
- `src/skillfoundry/verifier.py`
- `src/skillfoundry/acceptance.py`
- `src/skillfoundry/qa.py`
- `src/skillfoundry/registry.py`

### 10.2 作为 v2 核心硬化

这些模块是新骨架：

- `src/skillfoundry/contracts.py`
- `src/skillfoundry/goal_runtime.py`
- `src/skillfoundry/workers_v2.py`
- `src/skillfoundry/graph_v2.py`
- `src/skillfoundry/frontdesk_v2.py`
- `src/skillfoundry/frontdesk_goal_runtime.py`
- `src/skillfoundry/verification_bridge.py`

### 10.3 重写或退役

这些旧形态不应该继续承载新特性：

- `src/skillfoundry/context.py`
- `src/skillfoundry/worker.py`
- `src/skillfoundry/llm_builder.py`
- `src/skillfoundry/graph.py`
- legacy prompt assembly paths
- old WP-oriented docs as execution source

### 10.4 小心收敛 FrontDeskLoop

`src/skillfoundry/frontdesk_loop.py` 是最需要谨慎迁移的地方。

目标状态：

```text
ready_for_audit
  -> materialize core need and solution plan
  -> await user plan review

approved plan review
  -> run Front Desk Spec Auditor through Goal Harness
  -> deterministic FreezeGate
  -> graph v2 build path
```

## 11. Migration Phases

### Phase 0: 入口和依赖对齐

状态：基本完成。

要求：

- `third_party/contextforge` 指向 Goal Harness 版本；
- 旧 root agent briefs 已归档；
- README 说明 v2 baseline；
- 旧 roadmap 文档标记为历史；
- 默认测试离线。

退出条件：

```text
新用户能安装、跑测试，并理解 v2 不受 v0 模块结构约束。
```

### Phase 1: Contract bridge hardening

状态：已实现，仍需作为核心保护。

要求：

- frozen SkillFoundry inputs 映射到 `GoalContract`；
- build node 映射到 `AgentNodeContract`；
- verification spec / acceptance coverage 映射到 `VerificationGate`；
- contract hash deterministic；
- raw conversation 被排除且被 forbidden；
- cache epoch 来自 frozen hashes 和 boundary policy。

测试：

```bash
.venv/bin/python -m pytest tests/test_contracts.py -q
```

退出条件：

```text
contracts 可确定性重建，并能通过 ContextForge schema round-trip。
```

### Phase 2: Offline Goal Harness vertical slice

状态：已实现。

要求：

- build node 通过 ContextForge `GoalHarness`；
- `ContextView`、`PromptView`、`PromptCachePlan`、`WorkerRun`、`VerificationResult`、`GoalRunRecord`、checkpoint 被持久化；
- graph state 只保存 IDs / refs；
- fake worker 是默认 worker。

测试：

```bash
.venv/bin/python -m pytest tests/test_goal_harness_slice.py tests/test_goal_harness_verified_runtime.py -q
```

退出条件：

```text
离线 job 能 build、verify、bridge、register，不依赖 live provider 或 Codex。
```

### Phase 3: Front Desk v2 runtime consolidation

状态：基本完成，仍需 bridge hardening。

要求：

- Core Need Discovery 通过 Goal Harness；
- Solution Planner 通过 Goal Harness；
- User Review Gate 必须保留；
- Spec Auditor 只在 approved plan review 后通过 Goal Harness 执行；
- `FrontDeskLoop` 不再保留旧 same-round audit/freeze 假设；
- FreezeGate 消费 routed review/audit/feasibility refs。
- Front Desk 生成的 acceptance criteria 必须能被 verified build / registry 路径确定性消费。

测试：

```bash
.venv/bin/python -m pytest tests/test_frontdesk_v2.py tests/test_frontdesk_goal_runtime.py -q
.venv/bin/python -m pytest tests/test_frontdesk_loop.py tests/test_frontdesk_api.py tests/test_frontdesk_freeze_gate.py -q
```

退出条件：

```text
Front Desk 产品路径生成 governed artifacts，等待用户方案审查，只审查 approved plan，冻结 builder inputs，且 raw conversation 不泄漏；冻结结果可以进入 verified build / registry 路径。
```

### Phase 4: LangGraph v2 成为产品主骨架

状态：happy path 已接入 API，repair route 已能进入 Goal Harness-backed repair node，并能重新通过 verifier / acceptance coverage / ContextForge bridge / registry gate；仍不是唯一产品主路径。

要求：

- `graph_v2.py` 成为 canonical build/verify/repair/registry route；
- 旧 `graph.py` 被退役或隔离为 compatibility wrapper；
- 每个 graph node 只存 refs / IDs；
- repair 是 Goal Harness node；
- route decision 使用 ContextForge verification status 和 SkillFoundry verifier/registry evidence。

测试：

```bash
.venv/bin/python -m pytest tests/test_graph_v2.py tests/test_graph_v2_runtime.py -q
```

退出条件：

```text
主产品路径能从 frozen inputs 跑到 registry 或 human review。
```

当前实现证据：

- `POST /frontdesk/jobs/{job_id}/build` 会从 approved/frozen Front Desk job 进入 graph v2 verified build / verify / registry happy path。
- graph v2 final state 持久化为 `contextforge/graph_v2_state.json`，并通过 refs-only validator。
- failed verification route 可以执行 repair Goal Harness node，记录 governed verifier-failure context、WorkerRun、ContextView、PromptCachePlan、checkpoint、repair instructions、repair runtime result 和 `attempts/002/repair_attempt.json`。
- repair 输出会重新通过 SkillFoundry verifier、acceptance coverage、ContextForge verification bridge 和 registry gate；repair worker self-report 仍不是 acceptance，失败的 repair verification 会进入 human review 而不是 registry。

### Phase 5: Worker migration

状态：worker boundaries 已存在，产品选择路径仍需收敛。

要求：

- Fake worker 仍为默认 deterministic path；
- Owned LLM worker 走 ContextForge model-call boundary；
- Codex thread worker 为 boundary-first opt-in；
- External worker 需要 evidence refs；
- worker factory 由 config 选择，并被记录；
- worker 无法绕过 verifier/registry。

测试：

```bash
.venv/bin/python -m pytest tests/test_workers_v2.py tests/test_goal_harness_verified_runtime.py -q
```

退出条件：

```text
同一合同可以由 fake、owned LLM、Codex thread boundary 或 external worker 执行，但 verification 语义不变。
```

### Phase 6: Verification / Registry finalization

状态：核心已实现，Front Desk 默认 criteria 的 deterministic check 映射已完成。

要求：

- SkillFoundry verifier 是产品 verifier；
- acceptance coverage 是 registry 前置硬门；
- ContextForge `VerificationResult` 记录 bridge evidence；
- Registry 拒绝 missing / stale / fabricated / self-reported evidence；
- manual-only criteria 需要 manual authority artifacts。
- Front Desk-generated `acceptance_criteria.yaml` 必须包含可被 verifier/coverage 解析的 `verifier_check_id`。

测试：

```bash
.venv/bin/python -m pytest tests/test_verification_bridge.py tests/test_registry.py tests/test_acceptance_coverage.py -q
```

退出条件：

```text
Registry 只批准当前 artifacts 与 verifier、acceptance coverage、ContextForge verification evidence 全部匹配的 package。
```

### Phase 7: API/UI productization

状态：部分完成；Front Desk no-key 默认路径和 graph v2 build/registry happy path 已接入，repair/human-review/UI evidence 仍需收敛。

要求：

- API 创建 Front Desk jobs；
- API 支持 plan review；
- API 支持 approved/frozen Front Desk job 进入 graph v2 build/verify/registry；
- API 暴露 ContextForge status，但不泄漏 raw prompt / raw payload；
- UI 展示当前阶段、需要用户做什么、方案审查、验证结果和 registry outcome；
- UI 默认不展示内部 raw prompts/transcripts。

测试：

```bash
.venv/bin/python -m pytest tests/test_api.py tests/test_frontdesk_api.py -q
```

退出条件：

```text
用户能提交需求、审查方案、批准方案、运行受治理 build path，并查看证据摘要。
```

### Phase 8: Live provider / Codex SDK pilots

状态：未来 opt-in。

要求：

- provider keys opt-in；
- live calls 不进入默认测试；
- usage/cache telemetry 可得则记录；
- usage 不可得则记录原因；
- Codex thread worker 记录 transcript/diff/artifact boundary refs；
- Codex run 后检查 write scope；
- Verifier 仍是最终门。

退出条件：

```text
3-5 个内部真实需求跑完全路径，记录成本、缓存、失败、修复、验证和人工介入数据。
```

### Phase 9: Legacy retirement

状态：未来。

要求：

- v2 product path 成为 canonical；
- legacy prompt/context/worker/graph modules 删除或归档；
- README / HANDOFF / docs 指向同一执行源；
- 历史文档明确标注 historical。

退出条件：

```text
新 contributor 不需要理解 WP0-WP17 内部实现，就能修改当前 v2 产品路径。
```

## 12. 验收门

每个非平凡实现切片都应至少运行：

```bash
.venv/bin/python -m pytest -q
git diff --check
```

按领域的 focused gates：

```bash
.venv/bin/python -m pytest tests/test_contracts.py -q
.venv/bin/python -m pytest tests/test_goal_harness_slice.py tests/test_goal_harness_verified_runtime.py -q
.venv/bin/python -m pytest tests/test_frontdesk_v2.py tests/test_frontdesk_goal_runtime.py -q
.venv/bin/python -m pytest tests/test_graph_v2.py tests/test_graph_v2_runtime.py -q
.venv/bin/python -m pytest tests/test_workers_v2.py tests/test_verification_bridge.py tests/test_registry.py -q
```

必须独立 review 的变更：

- 架构判断；
- 生产就绪声明；
- live Codex / provider 集成；
- 删除 legacy modules；
- raw conversation visibility 变化；
- registry acceptance 语义变化；
- PromptCachePlan / cache epoch 策略变化。

必须由人类授权的变更：

- external publication；
- production deployment；
- destructive migration；
- secrets / credential policy；
- legal / compliance claim。

## 13. 新 contributor checklist

开始改代码前：

1. 读本文和 `docs/SKILLFOUNDRY_V2_BASELINE.md`。
2. 跑全量测试。
3. 看 `git status`，不要误改 unrelated dirty files。
4. 判断目标路径是 v2 core 还是 legacy。
5. 新功能优先进入 v2 modules。
6. 不要为了省事继续扩大旧 `context.py` / `worker.py` / `llm_builder.py` / `graph.py`。
7. 改 context visibility 时必须加 raw conversation exclusion 测试。
8. 改 worker / verifier / registry 时必须证明 worker self-report 不能通过。
9. 改 graph / API state 时必须证明 state 仍然 refs-only。
10. 架构风险变更必须找独立 reviewer。

## 14. 关键风险

### 14.1 误以为已经完成

风险：

仓库已经有很多 v2 模块，容易误判“重构已经完成”。

缓解：

- 看 product path evidence，不看模块数量。
- 只有 API / Front Desk / Graph / Verifier / Registry 全链路跑通，才能说产品路径完成。

### 14.2 Raw context 泄漏

风险：

raw conversation 或 raw logs 通过调试字段、summary、API response 或 state 泄漏进 prompt。

当前迁移阶段还有一个更具体的风险：

```text
legacy Front Desk elicitor / auditor prompt path 仍可能直接消费 raw conversation。
```

这条旧路径只能作为迁移事实存在，不能成为 v2 contract、builder、repair 或 refs-only graph state 的默认输入边界。

缓解：

- forbidden selectors；
- state validators；
- API shape tests；
- prompt/content leakage tests。

### 14.3 Cache churn

风险：

timestamp、attempt id、unordered JSON、failure logs 混入 stable prefix，破坏缓存命中。

缓解：

- frozen contracts 放 prefix；
- volatile diagnostics 放 suffix；
- cache epoch 变化必须有理由；
- 记录 prefix hash 和 provider payload hash。

### 14.4 Codex opacity

风险：

把 Codex SDK thread 包进 ContextForge 后，就错误声称掌握了 Codex 内部上下文管理。

缓解：

- 文档和 metadata 都写 boundary-only；
- usage unavailable reason 显式记录；
- transcript/diff/artifact refs；
- post-run write-scope check；
- independent verifier。

### 14.5 Verifier 被稀释

风险：

LLM judge、Spec Auditor、builder summary 或 worker completed 被当作 truth。

缓解：

- Registry 必须要求 verifier 和 acceptance coverage；
- LLM judge 默认 advisory；
- Worker self-report is never acceptance。

### 14.6 Legacy drift

风险：

继续 patch 旧 `context.py`、`worker.py`、`llm_builder.py`、`graph.py`，把错误架构延寿。

缓解：

- 新功能进入 v2 modules；
- legacy 改动必须说明迁移或退役理由；
- README / HANDOFF / docs 指向 v2 路线。

## 15. 内部产品可用定义

SkillFoundry 达到内部产品可用，至少需要：

- 用户能通过 API/UI 提交需求；
- Front Desk 生成 core need 和 solution plan；
- 用户批准是 audit/freeze 前置条件；
- Freeze 生成 deterministic frozen inputs；
- Graph v2 跑 build / verify / repair / registry；
- ContextForge ledger 记录 context view、prompt cache plan、worker run、verification、checkpoint refs；
- Verifier 和 acceptance coverage 是 registry 前置硬门；
- Registry 拒绝 stale / fabricated evidence；
- API 暴露 observability，但不泄漏 prompt/raw payload；
- 默认全量测试离线通过；
- 至少 3 个内部真实任务记录 cost/cache/failure/repair metrics。

生产级还需要：

- auth；
- tenant isolation；
- queue / job runner；
- sandbox；
- secrets management；
- audit log retention；
- incident response；
- deployment / rollback；
- monitoring / alerting；
- human review operations。

在这些能力存在前，不要宣称 production-ready。

## 16. Reviewer Packet

独立 reviewer 需要检查：

- 本文是否准确区分 ContextForge、LangGraph、worker、verifier、registry 的责任；
- 本文是否没有声称 ContextForge 控制 Codex SDK thread 内部 prompt/cache/tool loop；
- 本文是否把 Raw Front Desk conversation 当作 forbidden provenance；
- 本文是否明确 Worker self-report is never acceptance；
- 本文是否包含从当前混合代码迁移到 v2 产品主路径的阶段计划；
- 本文是否包含足够明确的验收门；
- 本文是否能让新 contributor 不读历史对话也能接手。

历史 review 结果记录：

```text
reviewer: Mencius / independent gpt-5.5 xhigh reviewer
model: gpt-5.5 xhigh
decision: approved_with_residual_risks
blocking_findings: none
residual_risks: 产品主路径还没有完全收敛到 v2 Goal Harness 骨架；入口文档后续需要同步本文权威。
```

当前入口文档 review 记录：

```text
reviewer: Russell / independent gpt-5.5 xhigh reviewer
model: gpt-5.5 xhigh
initial_decision: approve_with_required_changes
final_decision: approve
blocking_findings_fixed_in_this_revision:
  - stale rebuild-plan immediate next PR;
  - inconsistent phase numbering between the two main docs;
  - missing current implementation matrix;
  - DEVELOPMENT_ROADMAP still claiming execution authority;
  - historical reviewer notes not labeled as historical.
status: approved, no remaining blockers
```
