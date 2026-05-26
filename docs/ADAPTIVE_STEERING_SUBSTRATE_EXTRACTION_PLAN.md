# Adaptive Steering Substrate Extraction Plan

最后更新：2026-05-24

## 文档用途

本文基于 SkillFoundry adaptive steering MVP 的 Phase 2-8 实际实现，判断哪些抽象应该保留在 SkillFoundry，哪些未来可以下沉到 ForgeUnit / ContextForge，哪些应暂缓。

本文不是立即重构底座的任务单。

当前结论：

```text
先不重写 ContextForge / ForgeUnit。
先把 SkillFoundry 的 adaptive steering 作为已验证 product-layer prototype 保持稳定。
再用真实产品任务继续打磨字段和失败模式。
最后只下沉已经被多场景证明稳定的 primitives。
```

## 已完成的实证基础

本轮实现已经落地：

```text
Phase 1: src/skillfoundry/adaptive.py
Phase 2: src/skillfoundry/adaptive_workspace.py
Phase 3: src/forgeunit_skillfoundry/state.py / report.py adaptive refs-only read model
Phase 4: src/forgeunit_skillfoundry/adaptive_graph.py
Phase 5: src/skillfoundry/bundle.py
Phase 6: src/skillfoundry/bundle_verifier.py
Phase 7: tests/test_code_runtime_pilot.py
Phase 8: tests/test_mini_knowledge_runtime_pilot.py
```

已验证能力：

- adaptive schema 可以 JSON round-trip；
- adaptive artifacts 可以写入 workspace 并登记 manifest；
- product state / evidence summary 只暴露 refs 和摘要；
- adaptive graph 可以跑 happy path、repair path、repeated failure -> review_required；
- adaptive graph closure 由 independent BundleVerifier evidence 决定，不接受 worker 自报 passed；
- graph state 只保存 work-unit result refs 和状态摘要，不保存 worker claim / command / failure 原始字符串；
- bundle manifest 可以表达 prompt-only / code-runtime / knowledge-runtime；
- bundle verifier 可以区分 manifest missing / invalid / valid；
- code runtime pilot 能生成 queryable Python runtime bundle，并完成主 Verifier / registry / final report gate；
- mini knowledge runtime pilot 能生成 synthetic JSONL KB、query script 和 manifest，并完成主 Verifier / registry / final report gate；
- full pytest 已作为阶段门运行。

## 总体判断

当前 adaptive steering 的核心方向成立，但还不应该立刻下沉为通用底座 API。

原因：

- `NextStepContract`、`ObservationReport`、`StateCorrection` 已经表现出通用性；
- 但字段命名、route 语义、bundle closure 规则仍带有 SkillFoundry 领域痕迹；
- code-runtime 和 knowledge-runtime pilot 只证明了两类场景，还不足以覆盖更复杂的 MCP / service / multi-agent long-running cluster；
- ContextForge / ForgeUnit 的公共 API 应保持稳定，避免为了一个产品场景过早抽象。

推荐节奏：

```text
Keep SkillFoundry implementation stable.
Run more real product pilots.
Extract the narrow stable core.
Avoid substrate rewrites until evidence repeats.
```

当前结论已经比文档标题更进一步：

- 这条 adaptive steering 路线已在 SkillFoundry 层验证成立；
- 现在的主要工作不是继续证明它能跑，而是判断哪些字段 / 约束 / gate 值得成为底座候选；
- 因此这里的“Extraction Plan”已经从计划变成了稳定化判读记录。

## Keep / Extract / Defer 总表

| Primitive | 当前落点 | 判断 | 说明 |
| --- | --- | --- | --- |
| `CapabilityBundleManifest` | SkillFoundry | keep | Capability Bundle 是 SkillFoundry 领域语义，不应下沉 |
| `BundleVerifier` | SkillFoundry | keep | bundle profile 检查属于产品 verifier |
| `CapabilityStateEstimate` | SkillFoundry | defer/extract partly | 结构通用，但字段仍是 capability 领域 |
| `NextStepContract` | SkillFoundry | extract candidate | 最像 ForgeUnit work-unit contract |
| `ObservationReport` | SkillFoundry | extract candidate | 最像 ForgeUnit execution/measurement envelope |
| `StateCorrection` | SkillFoundry | extract candidate | 更适合 ContextForge state correction / ledger |
| `DecisionLedger` | SkillFoundry | extract candidate | 可进入 ContextForge ledger，但需要多产品验证 |
| adaptive artifact refs | SkillFoundry | extract candidate | refs-only artifact discipline 应下沉 |
| deterministic adaptive graph policy | SkillFoundry | keep | policy 是产品级策略，不应进入 LangGraph |
| route values | SkillFoundry | defer | `repair` / `closure` / `review_required` 需要跨产品统一 |
| code-runtime pilot | tests | keep | 是产品验证 fixture，不是底座 |
| knowledge-runtime pilot | tests | keep | 是产品验证 fixture，不是底座 |

## 必答问题

### 1. `NextStepContract` 字段是否足够稳定？

结论：

```text
基本稳定，但还不应该直接冻结为 ForgeUnit 公共 API。
```

稳定字段：

- `job_id`
- `iteration`
- `current_state_ref`
- `next_objective`
- `why_now`
- `allowed_scope`
- `visible_refs`
- `expected_outputs`
- `exit_criteria`
- `stop_conditions`
- `risk_if_too_large`
- `risk_if_too_small`

这些字段在 code-runtime 和 knowledge-runtime pilot 中都成立。

仍需观察的字段：

- `estimated_followups`
- `metadata`
- route 与 contract 的关系
- worker 是否应能提出 contract patch
- contract 是否需要 resource budget / timeout / tool permissions

提取建议：

```text
ForgeUnit vNext 可以引入 WorkUnitContract，
字段从 NextStepContract 收窄迁移，
但不要把 Capability Bundle 语义带入 ForgeUnit。
```

候选 ForgeUnit 名称：

```text
WorkUnitContract
BoundedWorkContract
StepContract
```

### 2. `ObservationReport` 是否可以成为 ForgeUnit work-unit report envelope？

结论：

```text
可以作为候选，但需要拆分 worker claim 与 verified evidence。
```

当前稳定字段：

- `contract_ref`
- `produced_artifacts`
- `changed_refs`
- `commands_run`
- `tests_run`
- `failures`
- `verifier_evidence`
- `new_unknowns`
- `recommended_next_steps`

需要谨慎字段：

- `worker_claims`

`worker_claims` 有价值，但必须保持低信任级。它可以进入 observation，但不能进入 verifier pass 条件。

提取建议：

```text
ForgeUnit 可以引入 WorkUnitObservation 或 WorkUnitReport。
其中 worker_claims 必须标记为 untrusted observation。
verifier_evidence / artifact refs 才能推动 closure。
```

### 3. `CapabilityStateEstimate` 是通用 `StateEstimate`，还是 SkillFoundry domain state？

结论：

```text
当前是 domain state。
可以提取出一个更小的通用 StateEstimate envelope。
```

通用部分：

- `job_id`
- `iteration`
- `objective`
- `current_phase`
- `known_good`
- `known_bad`
- `known_unknowns`
- `current_risks`
- `confidence`
- `next_best_step`

领域部分：

- `Capability`
- bundle closure 语义
- package/profile/manifest 状态
- SkillFoundry verifier status

提取建议：

```text
ContextForge 未来可提供 StateEstimateBase：
  state_id
  job_id
  iteration
  objective
  known_good
  known_bad
  known_unknowns
  risks
  confidence
  next_best_step
  source_refs

SkillFoundry 保留 CapabilityStateEstimate 作为 domain extension。
```

### 4. 是否需要 `EvidenceReliability`？

结论：

```text
需要，但暂缓实现。
```

当前系统已经隐含 evidence reliability：

- worker self-report 低可信；
- artifact existence 中可信；
- command/test result 中高可信；
- verifier result 高可信；
- reviewer gate 高可信但成本更高。

暂缓原因：

- 当前 deterministic tests 还不需要复杂权重；
- 过早建模会让 Phase 4 graph 复杂化；
- 需要更多真实 failure case 才能设计字段。

未来候选：

```text
EvidenceReliability:
  source
  evidence_ref
  kind
  trust_level
  freshness
  reproducibility
  verifier_bound
  known_noise
```

落点建议：

```text
ContextForge owns EvidenceReliability.
SkillFoundry only consumes it in product policy.
```

### 5. `DecisionLedger` 应进入 ContextForge ledger，还是留在 product app？

结论：

```text
长期应进入 ContextForge ledger。
短期继续留在 SkillFoundry。
```

理由：

- decision ledger 是 agent work substrate 的核心神经记录；
- 它不属于 Capability Bundle 专属语义；
- 但当前 `DecisionRecord` 字段仍偏产品 policy；
- 需要先证明它在 code runtime、knowledge runtime、MCP/service runtime、多 agent cluster 中都稳定。

推荐迁移方式：

```text
ContextForge:
  DecisionLedgerBase
  append_decision
  read_decisions
  decision refs / hashes / replay

SkillFoundry:
  CapabilityDecisionRecord extension
```

### 6. ForgeUnit 是否应原生理解 next-step contract？

结论：

```text
是，但不是现在。
```

ForgeUnit 最适合承接：

- bounded work unit；
- allowed scope；
- visible refs；
- expected outputs；
- exit criteria；
- stop conditions；
- work-unit observation；
- command boundary；
- worker evidence manifest。

不应承接：

- Capability Bundle profile；
- SkillFoundry bundle manifest policy；
- registry approval；
- product verifier semantics。

提取建议：

```text
ForgeUnit vNext:
  WorkUnitContract
  WorkUnitObservation
  WorkUnitRunner
  WorkUnitBoundaryVerifier
```

但在提取前，应至少完成一个 MCP/runtime-service pilot。

### 7. ContextForge 是否应原生支持 state correction / checkpoint / replay？

结论：

```text
是，这是 ContextForge 的核心价值方向。
```

ContextForge 应承接：

- state estimate；
- state correction；
- evidence refs；
- decision ledger；
- checkpoint；
- replay；
- prompt cache plan；
- refs-only context projection。

SkillFoundry 当前实现只是 product-layer prototype。

建议未来接口：

```text
contextforge.write_state_estimate(...)
contextforge.write_observation(...)
contextforge.correct_state(...)
contextforge.append_decision(...)
contextforge.checkpoint(...)
contextforge.replay(...)
contextforge.project_context(...)
```

但这些 API 应基于更多真实运行证据设计，不在当前 goal 内实现。

### 8. LangGraph route 是否足够薄？

结论：

```text
当前足够薄。
```

Phase 4 的 `adaptive_graph.py` 中，LangGraph 只负责：

- node ordering；
- conditional loop；
- end routing。

它没有拥有：

- evidence reliability；
- bundle policy；
- verifier authority；
- state correction semantics；
- product registry semantics。

这是正确边界。

需要保持：

```text
LangGraph = topology
ForgeUnit = bounded execution
ContextForge = governed state/evidence/context
SkillFoundry = product semantics
Verifier = truth gate
```

### 9. 哪些字段是 Capability Bundle 专属语义，不应下沉？

不应下沉：

- `bundle_id`
- `bundle_type`
- `capability_surface`
- `runtime_assets`
- `data_assets`
- `references`
- `environment`
- `permissions`
- `distribution`
- SkillFoundry registry policy
- prompt-only / code-runtime / knowledge-runtime profile checks
- `package/SKILL.md` specific checks
- `package/skillfoundry.bundle.json` ref

这些属于 SkillFoundry 产品语义。

应下沉的是更小的基础设施语义：

- artifact refs；
- work-unit contract；
- work-unit observation；
- state correction；
- decision record；
- checkpoint；
- replay；
- evidence reliability。

## 推荐下一轮真实验证

完成本 MVP 后，不建议立刻重构底座。

推荐下一轮验证：

1. 用 SkillFoundry 生成一个更完整的 clean-room code-runtime skill；
2. 用 SkillFoundry 生成一个中等规模 reference-heavy knowledge-runtime skill；
3. 增加一个 MCP-like fixture；
4. 增加一个 service-runtime fixture；
5. 观察 contract / observation / state correction 是否仍稳定；
6. 再决定 ForgeUnit / ContextForge API 提取。

## 提取路线

### Step 1: 保持当前 SkillFoundry 实现稳定

当前状态应作为 product prototype 保留。

短期只修 bug 和补 pilot，不做底座重写。

### Step 2: 扩大 pilot 覆盖

至少覆盖：

- prompt-only；
- code-runtime；
- knowledge-runtime；
- MCP-like；
- service-runtime。

### Step 3: 收窄底座 primitives

只提取跨场景重复出现的字段。

如果字段只在 SkillFoundry 有意义，留在 SkillFoundry。

### Step 4: ForgeUnit 提取 work-unit 层

候选：

```text
WorkUnitContract
WorkUnitObservation
WorkUnitEvidenceManifest
WorkUnitBoundaryPolicy
```

### Step 5: ContextForge 提取 governed state 层

候选：

```text
StateEstimateBase
StateCorrection
DecisionLedger
EvidenceReliability
Checkpoint
Replay
ContextProjection
PromptCachePlan
```

### Step 6: 保持 LangGraph 薄

不要把 product semantics 放进 graph。

Graph 只接 route decision。

## 最终判断

本轮实现证明：

```text
adaptive steering 作为 SkillFoundry product-layer MVP 是可行的。
```

但本轮还没有证明：

```text
这些 schema 已经可以成为永久通用底座 API。
```

因此当前最佳决策是：

```text
Keep product implementation.
Extract later.
Use real pilots as the abstraction filter.
```

换成当前项目状态就是：

```text
Keep the verified product implementation.
Treat the stable primitives as substrate candidates.
Do not freeze the whole product-layer shape into the base API yet.
```
