# Control/System Architecture Health Report

最后更新：2026-05-27

## 文档地位

本文是对当前 SkillFoundry 以及更长期 agent work substrate vision 的架构体检。

它不是新的路线图，也不是学术化白皮书。它只回答三个问题：

1. 这套约束框架是否仍然有必要？
2. 当前实现是否符合“最小必要治理 + 最大强 agent 自由度”？
3. 下一步最应该防止什么架构偏移？

本文基于当前主线文档和实现：

- `docs/AGENT_WORK_SUBSTRATE_VISION.md`
- `docs/RECURSIVE_AGENT_ORGANIZATION_VISION.md`
- `docs/SKILLFOUNDRY_CAPABILITY_BUNDLE_VISION.md`
- `docs/FORGEUNIT_SKILLFOUNDRY_COMPOSITION.md`
- `docs/ADAPTIVE_STEERING_SUBSTRATE_EXTRACTION_PLAN.md`
- `src/forgeunit_skillfoundry/adaptive_graph.py`
- `src/forgeunit_skillfoundry/adaptive_codex.py`
- `src/skillfoundry/adaptive.py`
- `tests/test_adaptive_steering_benchmark.py`
- `tests/test_frontdesk_adaptive_build.py`

## 总体结论

当前方向基本正确。

更准确地说：

```text
SkillFoundry 当前已经接近 mission-command style governed freedom：
底座给目标、边界、证据、恢复、验收、协作；
强 agent 在边界内保持战术自由。
```

这套框架不是因为模型不够聪明才需要，而是因为开放式复杂任务需要稳定闭环。
LLM 越强，越需要清楚地区分：

- 谁提出战术；
- 谁能改目标；
- 谁能写持久状态；
- 谁能证明完成；
- 谁能扩大边界；
- 谁能终止任务。

如果没有这些分权，强 agent 的能力会变成不稳定放大器：它可以更快地产生代码、解释和计划，也可以更快地产生未经证据约束的漂移。

因此，正确目标不是“更多约束”，而是：

```text
用最少、最稳定、最可解释的约束，
保持最高的 agent 战术自由度和系统长期稳定性。
```

当前实现总体符合这个方向，但还不应声称已经完成通用 meta substrate。它仍是一个被 SkillFoundry 产品语义验证过的 product-layer prototype。

## 控制系统映射

当前 vision 的控制论结构是自洽的：

| 控制系统角色 | 当前对应模块 | 健康判断 |
| --- | --- | --- |
| Objective / mission | FrontDesk frozen spec, acceptance criteria | 健康。最终目标和边界不由 worker 临场改写 |
| Controller | adaptive graph / route decision | 基本健康。现在是确定性策略，适合 MVP |
| State estimator | CapabilityStateEstimate / ContextForge-style refs | 健康但仍偏产品层 |
| Control input | NextStepContract | 健康，是最强的 substrate candidate 之一 |
| Actuator | ForgeUnit command boundary / Codex worker | 健康。worker 有执行自由但有写入边界 |
| Sensor | Verifier / BundleVerifier / ProductGradeGate / acceptance coverage | 健康。worker 自报不是验收 |
| Observation | ObservationReport | 健康。失败、unknown、recommendation 都结构化进入系统 |
| Correction | StateCorrection / DecisionLedger | 健康但还不够通用 |
| Stop / escalation | repeated failure -> review_required, closure only after gates | 健康。避免无限 repair loop |
| Durable memory | refs-only artifacts / manifest / product summary | 健康。避免 raw prompt/transcript 污染 state |

这个结构的关键优点是它把“计划赶不上变化”处理成闭环控制问题，而不是把 worker 降级成死命令执行器。

当前闭环是：

```text
RoutePlan / StateEstimate
-> NextStepContract
-> ForgeUnit WorkUnit
-> Codex / worker execution
-> ObservationReport
-> independent verification
-> StateCorrection
-> continue / repair / review / closure
```

这比一次性 plan-and-execute 稳定，也比完全自由的 agent loop 可控。

## 当前健康点

### 1. 分权是清楚的

当前代码没有让 worker 自己决定 closure。

`adaptive_codex.py` 明确把 ForgeUnit/Codex worker result 当作 evidence only；closure 由 SkillFoundry Verifier、acceptance coverage、BundleVerifier、ProductGradeGate 和 registry gate 决定。

这是最重要的健康信号。

### 2. LangGraph 目前足够薄

`adaptive_graph.py` 主要负责 node ordering、conditional loop、route after correction。

它没有吞掉：

- evidence reliability；
- product verifier authority；
- worker execution logic；
- bundle policy；
- registry policy。

这符合当前 vision：

```text
LangGraph owns topology.
It should stay thin.
```

### 3. NextStepContract 的边界有效

当前 contract 已经具备重要控制字段：

- `next_objective`
- `why_now`
- `allowed_scope`
- `visible_refs`
- `expected_outputs`
- `exit_criteria`
- `stop_conditions`
- `risk_if_too_large`
- `risk_if_too_small`
- `route_plan_ref`

这让 worker 不是被微观指挥，而是在一个可验证的一步边界内自主执行。

### 4. RoutePlan 升级方向正确

当前 RoutePlan 解决了一个真实问题：

任务导向不等于没有计划。强 agent 仍然应该基于当前认知形成路线、Plan B、假设、pivot triggers 和 evidence strategy。

实现上，系统现在是：

```text
先有 route plan prior。
每一步发 next-step contract。
观察后根据 failures / unknowns / recommendations 修订 route plan。
```

这符合“走一步看一步”，而不是“完全不规划”。

### 5. 对 false success 有抵抗力

测试覆盖了 worker 自称成功但 BundleVerifier 失败的场景。

`tests/test_adaptive_graph.py` 中，worker 返回 `verification_status="passed"` 但写入 invalid manifest，系统仍路由到 repair，而不是 closure。

这是控制系统里最关键的传感器校准能力。

### 6. refs-only state 纪律有效

当前 graph state 和 product summary 避免持久化 raw prompt、raw transcript、package body、worker input、command string。

相关测试覆盖：

- adaptive state 不包含 raw worker strings；
- product state / evidence summary 只暴露 selected refs；
- API response 不泄漏 command bridge 字符串；
- wrapper diagnostics 不包含 raw stdout/stderr/prompt。

这对长期 agent 系统很关键，因为 context 污染会导致状态漂移、隐私泄漏和不可回放。

### 7. 有 baseline/upgraded 对照验证意识

`tests/test_adaptive_steering_benchmark.py` 已经把 upgraded RoutePlan steering 与 baseline 做了确定性对照，覆盖：

- false success；
- worker recommendation pivot；
- new unknown；
- product-grade repair；
- repeated failure；

这说明项目没有只验证“文件存在”，而是在验证复杂任务控制质量。

## 主要风险

### R1. Product policy 泄漏到底座

当前最重要的架构风险是把 SkillFoundry 产品规则误下沉为通用 substrate。

明显产品层规则包括：

- `package/SKILL.md`
- `package/skillfoundry.bundle.json`
- Capability Bundle manifest；
- SkillFoundry registry；
- prompt-only / code-runtime / knowledge-runtime profile；
- Rust/Cargo/verifier/test fixtures 的特定提示；
- ProductGradeGate 和 BundleVerifier 的 SkillFoundry 语义。

这些规则在 SkillFoundry 层是必要的，但不能变成 ForgeUnit / ContextForge 的通用 API。

健康边界应该是：

```text
Substrate owns:
  WorkUnitContract
  ObservationReport
  StateEstimate
  StateCorrection
  DecisionLedger
  EvidenceReliability
  Checkpoint / Replay

SkillFoundry owns:
  Capability Bundle
  SKILL.md
  bundle manifest
  product verifier profiles
  registry policy
```

当前文档已经有这个判断，但后续实现必须继续守住。

### R2. 当前 NextStep 生成仍偏固定产品工艺

`_build_next_step_contract` 目前按 SkillFoundry 的最小 bundle 工艺推进：

```text
缺 SKILL.md -> 生成 SKILL.md
缺 bundle manifest -> 生成 manifest
否则 closure
```

这对 MVP 是正确的，但对 full runtime bundle、MCP runtime、service runtime、EDA/知识库场景不够。

下一阶段不应该把这段逻辑泛化到底座。更好的方向是：

```text
底座提供 WorkUnitContract schema 和 safety boundary。
产品 policy / planner 决定下一步 contract。
worker 可以提出 contract adjustment request。
```

### R3. worker recommendation 还不是一等公民

当前 worker 可以通过 `recommended_next_steps` 影响 RoutePlan 修订，但它不是正式的 contract patch 协议。

这会带来两个问题：

1. worker 的战术发现只能作为文本建议进入 route plan；
2. harness 缺少结构化方式判断建议是 shrink、expand、split、pivot、repair，还是 spec revision。

建议后续引入：

```text
ContractAdjustmentRequest:
  requested_change: shrink | expand | split | reorder | pivot | spec_revision
  reason
  evidence_ref
  proposed_allowed_scope
  proposed_expected_outputs
  affected_acceptance
  risk
  authority_required
```

worker 可以提议，substrate 决定是否采纳。

### R4. Evidence reliability 仍是隐含规则

当前系统已经隐含证据等级：

- worker self-report 低可信；
- artifact refs 中可信；
- verifier/test/hash 高可信；
- reviewer 高可信但成本高。

但 schema 里还没有显式 `EvidenceReliability`。

短期没有问题，MVP 不需要过度建模。长期要支持多 agent 集群和跨 worker 调度时，证据可信度需要显式化，否则系统很难解释为什么某个 observation 足以改变 state。

### R5. RoutePlan artifact 可能携带未归一化 worker 文本

当前 graph state 不保存 raw worker strings，这是对的。

但 RoutePlan artifact 会吸收 `recommended_next_steps`，测试里也明确允许 recommendation marker 出现在 route plan artifact 中。

这对当前 benchmark 是合理的，但长期有风险：worker recommendation 可能包含 raw prompt、私有路径、未经验证的 claim 或过长文本。

建议后续加一层 observation normalization：

```text
worker raw recommendation
-> normalized advisory signal
-> route plan revision
```

artifact 可以保留 source ref，但 route plan 应尽量保存归一化后的判断，而不是原样复制 worker 文本。

### R6. Verifier 可能被产品 gate 过拟合

Verifier 是 truth gate，但它只能证明它会检查的东西。

当前 ProductGradeGate 和 BundleVerifier 对 SkillFoundry 很必要，但系统必须避免把“通过 gate”误认为“真实高质量”。

后续需要继续用真实复杂任务验证：

- Codexarium clean-room rebuild；
- reference-heavy knowledge runtime；
- MCP-like runtime；
- service runtime；
- EDA-like professional workflow。

这些任务要检查最终产物是否真的可用，而不是只满足 schema。

### R7. 还没有进入真正多 agent 组织层

当前实现支持 strong worker + verifier + reviewer boundary 的雏形，但还不是完整 recursive agent organization。

缺口包括：

- Scheduler；
- ResourceBudget；
- CapabilityRegistry for workers；
- RuntimeSession / event stream；
- lease / lock / abort / resume；
- verifier pool；
- multi-worktree / multi-worker dispatch protocol；
- cross-worker dependency graph。

这不是当前 MVP 的失败，只是不要过早声称已经完成通用多 agent 组织底座。

## 是否“搞复杂了”

红方问题是合理的：模型越来越强，是否还需要这么复杂的框架？

结论是：需要，但只需要控制复杂度，不需要流程复杂度。

不该复杂的是：

- 微观步骤；
- prompt choreography；
- 固定 waterfall；
- 让 harness 替 worker 思考所有实现细节；
- 为了抽象而抽象的庞大 schema。

必须存在的是：

- 目标边界；
- 写入边界；
- 可见上下文边界；
- evidence refs；
- 独立 verifier；
- state correction；
- stop/review boundary；
- replay/checkpoint；
- product policy 和 substrate primitive 的分层。

换句话说，复杂性应该集中在少数稳定控制点，而不是散落到每个 prompt 和每段业务代码里。

## 当前评分

| 维度 | 评分 | 判断 |
| --- | --- | --- |
| 架构方向 | A- | 分权、闭环、refs-only、verification-first 都是正确方向 |
| 当前 SkillFoundry 落地 | B+ | 已经可验证，但仍偏产品层 prototype |
| 底座抽象成熟度 | B- | primitive 候选清楚，但还不能冻结为通用 API |
| 强 agent 自由度 | B+ | 有战术自由，但 NextStep 生成仍偏固定工艺 |
| 稳定性设计 | A- | false success、repeat failure、review boundary 都有覆盖 |
| 多 agent 扩展性 | C+ | 理论清楚，实现还没到 recursive organization |
| 产品/底座边界 | B | 文档清楚，代码里仍有 product policy 需要持续隔离 |
| 证据体系 | B+ | refs-only 和 verifier gate 好，EvidenceReliability 尚未显式化 |

总体健康等级：

```text
Healthy product-layer control prototype.
Not yet a mature generic substrate.
```

中文：

```text
健康的产品层控制原型。
尚未完成通用底座成熟化。
```

## 推荐决策

### P0. 不要立刻重写底座

当前最佳策略仍然是：

```text
Keep SkillFoundry implementation stable.
Use real pilots as abstraction filter.
Extract only repeated stable primitives.
```

过早把当前 product-layer shape 冻结进 ForgeUnit / ContextForge，会制造错误抽象。

### P1. 明确 product policy profile

把 SkillFoundry 特有规则收束成明确的 product policy profile：

```text
SkillFoundryBundlePolicy
SkillFoundryVerifierProfile
SkillFoundryWorkerPromptProfile
SkillFoundryRegistryPolicy
```

底座只知道它们是 policy/profile，不知道 SKILL.md、bundle manifest、Rust/Cargo 的具体业务含义。

### P1. 引入 ContractAdjustmentRequest

这是下一步最值得做的 substrate candidate。

它能解决当前的核心张力：

```text
harness 要保留治理权；
strong agent 要能基于前线发现调整计划。
```

原则：

```text
Worker proposes.
Substrate commits.
Verifier proves.
Reviewer arbitrates when authority is exceeded.
```

### P1. 给 observation 增加 normalization 层

不要让 worker recommendation 原样进入 strategy artifact。

建议结构：

```text
ObservationReport.raw_worker_claims/ref
ObservationSignal.normalized_kind
ObservationSignal.trust_level
ObservationSignal.safe_summary
ObservationSignal.source_ref
```

这样既保留 worker 智能，又减少 context pollution。

### P2. 显式化 EvidenceReliability

先不做复杂权重模型，只做离散等级即可：

```text
untrusted_worker_claim
artifact_ref
command_result
test_result
schema_validation
verifier_result
reviewer_decision
human_acceptance
```

这会让 state correction 更可解释。

### P2. 把 benchmark 从确定性扩展到真实 pilot

当前 deterministic benchmark 很有价值，但不能替代真实强 agent 任务。

下一批实验建议：

1. Codexarium clean-room code-runtime bundle；
2. reference-heavy knowledge-runtime bundle；
3. MCP-like runtime bundle；
4. service-runtime bundle；
5. EDA-like professional workflow。

每个都跑 baseline/upgraded 对照：

- 成功率；
- 迭代次数；
- repair loops；
- review boundary 命中；
- verifier false positive/false negative；
- worker recommendation 是否被正确吸收；
- 最终 bundle 是否真的可运行、可安装、可复用。

### P2. 增加 constraint cost 指标

判断框架是否过重，不能只看能不能成功，还要看约束成本。

建议记录：

- 每轮 wall time；
- token / command cost；
- verifier latency；
- 因边界过窄导致的 failed attempt；
- 因边界过宽导致的 ambiguous repair；
- worker request for contract adjustment；
- human/reviewer intervention count。

如果约束增加质量但成本失控，就需要减约束或延迟 gate。

## 最终体检结论

这条路线值得继续。

但成功条件不是“把框架做得更大”，而是持续证明：

```text
少数稳定约束，能够让强 agent 在复杂开放任务中长期自由行动，
同时保持可验证、可恢复、可审计、可协作、可停止。
```

当前 SkillFoundry 已经证明了第一段：

```text
强 agent 不需要被微观命令控制。
它可以在 bounded contract 内自主战术执行。
系统只在目标、边界、证据、恢复、验收、协作上治理。
```

还没有完全证明第二段：

```text
这套 primitives 已经足够通用，
可以稳定支撑任意复杂度的多 agent 集群。
```

所以当前最正确的工程姿态是：

```text
继续以 SkillFoundry 为试验场。
保持 adaptive_codex opt-in。
用 Codexarium / runtime bundle / MCP / service pilots 增加证据。
把可重复出现的 primitive 下沉。
把 SkillFoundry 产品规则留在产品层。
```

一句话：

```text
方向对，边界要继续守，抽象要继续等证据。
```
