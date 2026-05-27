# Controlled LLM Steering Upgrade Plan

最后更新：2026-05-27

## 文档地位

本文定义下一轮升级方向：在当前 deterministic adaptive steering 的基础上，引入受约束的大模型智能节点，使系统在复杂任务中具备更强的语义判断、战术规划、失败解释和路线修订能力，同时保持可控、透明、可验证。

本文不是立即下沉 ContextForge / ForgeUnit 公共 API 的任务单。

本文也不是把系统改成“全流程 LLM 接力”。相反，它明确：

```text
LLM 提出候选。
Harness 校验边界。
Code 提交状态。
Verifier 证明事实。
Reviewer 仲裁质量和越权。
```

本文承接：

- `docs/AGENT_WORK_SUBSTRATE_VISION.md`
- `docs/RECURSIVE_AGENT_ORGANIZATION_VISION.md`
- `docs/CONTROL_SYSTEM_ARCHITECTURE_HEALTH_REPORT.md`
- `docs/ADAPTIVE_STEERING_SUBSTRATE_EXTRACTION_PLAN.md`
- `src/skillfoundry/adaptive.py`
- `src/forgeunit_skillfoundry/adaptive_graph.py`
- `src/forgeunit_skillfoundry/adaptive_codex.py`

## 背景判断

当前系统已经证明了一个重要方向：

```text
强 agent 可以在 bounded contract 内自由战术执行；
系统只在目标、边界、证据、恢复、验收、协作上治理。
```

当前 adaptive steering 已经具备：

- `CapabilityStateEstimate`
- `RoutePlan`
- `NextStepContract`
- `ObservationReport`
- `StateCorrection`
- `DecisionLedger`
- repeated failure -> `review_required`
- verifier evidence -> closure
- worker self-report is not acceptance
- refs-only graph/product state
- baseline/upgraded benchmark

但当前 `adaptive_graph.py` 的 steering policy 主要还是 deterministic：

```text
缺 package/SKILL.md -> 生成 SKILL.md
缺 package/skillfoundry.bundle.json -> 生成 manifest
ProductGradeGate 失败 -> repair packet
重复失败 -> review_required
BundleVerifier 通过 -> closure
```

这足以验证 MVP，但不够支撑真实复杂任务。

真实任务中会出现：

- 需求实际需要从 prompt-only pivot 到 code-runtime；
- worker 发现当前 contract 太窄或太宽；
- verifier failure 表面原因和根因不同；
- observation 出现新的 unknown；
- repair packet 需要拆分成多个 work units；
- frozen spec 本身可能不完整，需要 spec revision；
- final bundle 虽然过了 schema gate，但架构质量不足；
- 多 agent / 多 worktree 并行时需要调度和依赖判断。

这些判断很难靠固定代码穷举。

因此下一步不是去掉约束，而是在关键不确定性节点引入受约束的大模型智能。

## 核心动机

这套系统的目标不是把大模型排除在控制系统之外，而是把大模型放进正确的位置。

错误方式：

```text
LLM decides everything:
  plan
  act
  verify
  accept
  expand scope
  close task
```

这会让系统不可控、不可审计、不可复现。

另一种错误方式：

```text
Code decides everything:
  fixed route
  fixed repair
  fixed contract size
  fixed product profile
```

这会让系统僵硬，无法处理复杂开放任务。

目标方式：

```text
LLM handles semantic uncertainty.
Code handles authority and truth boundaries.
Verifier handles reality.
Reviewer handles strategy and quality.
```

中文：

```text
大模型处理语义不确定性。
代码处理权力边界和状态提交。
Verifier 处理事实。
Reviewer 处理质量和策略。
```

这就是“把智力关进笼子里”的工程含义：不是压制智能，而是把智能的输出变成可校验、可拒绝、可回放、可追责的 proposal。

## 当前节点实际执行方式

当前主线默认行为如下。

| 流程节点 | 当前默认执行方式 | 是否 live LLM |
| --- | --- | --- |
| FrontDesk 澄清 | deterministic Goal Harness / fake workers；可注入 live client | 默认否，可选是 |
| frozen spec / acceptance criteria | FrontDesk artifacts + deterministic FreezeGate | 否 |
| ContextForge 生成受治理上下文 | 固定代码编译 refs、contracts、forbidden context、ledger | 否 |
| Adaptive Steering 决定下一步 | `adaptive_graph.py` deterministic policy | 否 |
| ForgeUnit 发 bounded work unit | 固定代码生成 task pack / worker boundary | 否 |
| Codex / worker 实现 | 默认 fake command；可显式 command bridge 到 Codex | 默认否，可选是 |
| ObservationReport 回收现实反馈 | 固定代码聚合 worker result / artifacts / verifier evidence | 否 |
| Verifier / ProductGate 判断真假 | deterministic schema/hash/file/test/product checks | 否 |
| StateCorrection 修正状态 | deterministic route policy | 否 |
| repair / continue / closure | deterministic route | 否 |
| Registry 注册 | deterministic registry gate | 否 |
| Final summary | deterministic refs-only read model | 否 |

因此当前系统是：

```text
deterministic control skeleton
+ optional LLM FrontDesk clients
+ optional external Codex worker boundary
```

下一步升级要补的是：

```text
controlled LLM proposal nodes inside steering/review/observation interpretation
```

而不是让 LLM 拿走提交权。

## 目标架构

目标闭环：

```text
StateEstimate / RoutePlan
  -> LLM Steering Proposal
  -> Harness Proposal Validation
  -> committed NextStepContract
  -> ForgeUnit WorkUnit
  -> Codex / Worker
  -> ObservationReport
  -> Verifier / ProductGate
  -> LLM Observation Interpretation
  -> Harness StateCorrection Commit
  -> continue / repair / review / spec_revision / closure
```

关键变化：

1. LLM 可以提出下一步 contract 候选；
2. LLM 可以解释 observation 中的新 unknown、根因和 repair direction；
3. LLM 可以提出 contract shrink / expand / split / pivot；
4. LLM 可以作为 independent reviewer 判断质量和策略；
5. 任何 LLM 输出都只作为 proposal / signal / review packet；
6. graph state 和 durable truth 仍由 code/harness 提交；
7. closure 仍由 verifier evidence 和 registry gate 决定。

## LLM 应进入的节点

### 1. FrontDesk Semantic Elicitor

当前已有 `RequirementsElicitor` / `SpecAuditor` 的 LLM-backed 接口，但默认 API 不启用 live client。

目标：

```text
FrontDesk 使用 live LLM 完成需求澄清、结构化、spec draft、audit draft。
FreezeGate 继续 deterministic。
```

输入：

- `frontdesk/conversation.jsonl`
- FrontDesk config
- clarification summary
- semantic lock / coverage artifacts

输出：

- elicitation report
- draft `skill_spec.yaml`
- `acceptance_criteria.yaml`
- spec audit report
- feasibility report

权限边界：

- LLM 不能冻结 spec；
- LLM 不能直接 route to build；
- LLM 输出必须 schema validate；
- FreezeGate 决定是否冻结。

### 2. Capability Design Proposer

当前 Capability Design 主要由 product contracts、FrontDesk artifacts 和 deterministic policy 支撑。

目标新增一个 LLM proposal node，用来判断 bundle 形态：

```text
prompt_only
script_tool
code_runtime
knowledge_runtime
mcp_runtime
service_runtime
full_runtime_bundle
```

候选输出：

```json
{
  "schema_version": "skillfoundry.capability_design_proposal.v1",
  "proposal_id": "capability-design-001",
  "input_refs": [
    "skill_spec.yaml",
    "acceptance_criteria.yaml",
    "verification_spec.yaml"
  ],
  "recommended_profile": "code_runtime",
  "runtime_surface": ["cli", "tests"],
  "rationale": "Acceptance requires executable duplicate-path checks.",
  "risks": ["Verifier must run script smoke tests."],
  "required_evidence": ["package/scripts/check_plan.py", "package/tests/test_check_plan.py"],
  "authority_required": "reviewer_if_profile_changes_frozen_spec"
}
```

提交规则：

- LLM 只写 proposal artifact；
- profile 写入 frozen spec 前必须经过 policy/reviewer；
- 已 frozen 的目标不能被 proposal 静默修改。

### 3. Steering Proposal Generator

这是本次升级的核心。

当前 `_build_next_step_contract(...)` 是 deterministic policy。

目标新增：

```text
StateEstimate + latest RoutePlan + latest Observation + verifier evidence
  -> LLM proposes one or more NextStepContract candidates
  -> code validates and selects/commits one contract
```

候选 schema：

```json
{
  "schema_version": "skillfoundry.steering_proposal.v1",
  "proposal_id": "steering-proposal-003",
  "job_id": "job-001",
  "iteration": 3,
  "input_refs": [
    "adaptive/capability_state.json",
    "adaptive/route_plan_002.json",
    "adaptive/observation_report_002.json",
    "verifier/bundle_verification_result.json"
  ],
  "recommended_route": "repair",
  "proposed_contract": {
    "next_objective": "Repair the failing runtime fixture coverage only.",
    "allowed_scope": ["package/tests", "qa", "adaptive/attempts/003"],
    "visible_refs": [
      "skill_spec.yaml",
      "acceptance_criteria.yaml",
      "qa/product_repair_packet.json"
    ],
    "expected_outputs": [
      "package/tests/test_check_plan.py",
      "adaptive/attempts/003/repair_evidence.md"
    ],
    "exit_criteria": [
      "ProductGradeGate is rerun.",
      "Runtime fixture finding is removed."
    ],
    "stop_conditions": [
      "Repair requires changing frozen requirements."
    ]
  },
  "rationale": "The failure is localized to fixture coverage; broad package rewrites would hide causality.",
  "risks": [
    "If script behavior is also wrong, this repair may be too narrow."
  ],
  "alternatives": [
    {
      "route": "review_required",
      "reason": "Escalate if the same fixture failure repeats."
    }
  ],
  "confidence": 0.72
}
```

提交规则：

- `proposed_contract` 必须转换成正式 `NextStepContract` 后才能执行；
- harness 必须校验 safe refs、allowed scope、expected outputs；
- proposal 不允许扩大 frozen spec；
- proposal 不允许写 forbidden paths；
- proposal 不允许设置 closure；
- proposal 不允许直接修改 graph state；
- rejected proposal 也要进入 decision ledger。

### 4. Contract Adjustment Request

worker 在前线执行时可能发现 contract 有问题。

当前只有 `recommended_next_steps` 文本字段。

目标新增一等 schema：

```json
{
  "schema_version": "skillfoundry.contract_adjustment_request.v1",
  "request_id": "contract-adjustment-002",
  "job_id": "job-001",
  "iteration": 2,
  "contract_ref": "adaptive/next_step_contract_002.json",
  "requested_change": "split",
  "reason": "The contract asks for script implementation and test repair in one step; verifier failure would be ambiguous.",
  "evidence_refs": [
    "adaptive/observation_report_002.json",
    "evidence/manifest.json"
  ],
  "proposed_contracts": [
    {
      "next_objective": "Implement script behavior only.",
      "allowed_scope": ["package/scripts", "adaptive/attempts/003"]
    },
    {
      "next_objective": "Add focused runtime tests only.",
      "allowed_scope": ["package/tests", "adaptive/attempts/004"]
    }
  ],
  "authority_required": "harness",
  "risk_if_rejected": "The next repair loop may not isolate the failing boundary."
}
```

Allowed changes:

- `shrink`
- `expand`
- `split`
- `reorder`
- `pivot`
- `spec_revision`
- `review_required`

规则：

- worker 可以请求；
- LLM steering node 可以请求；
- harness 决定；
- spec revision 必须走 reviewer/human gate；
- expansion outside current allowed scope 必须 review。

### 5. Observation Interpreter

当前 ObservationReport 直接收集 worker result、failures、new_unknowns、recommended_next_steps。

目标新增一个可选 LLM interpreter，把复杂 observation 归一化为安全信号。

候选 schema：

```json
{
  "schema_version": "skillfoundry.observation_signal.v1",
  "signal_id": "observation-signal-004",
  "observation_ref": "adaptive/observation_report_004.json",
  "signal_type": "root_cause",
  "safe_summary": "The verifier failure is caused by missing test fixture coverage, not by package entrypoint content.",
  "source_refs": [
    "adaptive/observation_report_004.json",
    "qa/product_grade_report.json"
  ],
  "trust_level": "llm_interpretation",
  "recommended_action": "repair",
  "affected_contract_fields": ["expected_outputs", "exit_criteria"],
  "confidence": 0.68,
  "requires_verifier_confirmation": true
}
```

规则：

- 不把 raw worker claim 原样塞进 route plan；
- route plan 使用 `safe_summary` 和 `source_refs`；
- graph state 只保存 signal refs；
- signal 不能直接变成事实；
- StateCorrection 使用 verifier evidence + signal 共同决策。

### 6. Repair Strategist

当前 repair 主要由 deterministic policy 和 ProductGradeGate repair packet 驱动。

目标：

```text
失败观察 + repair packet + verifier evidence
  -> LLM repair strategy proposal
  -> harness 生成 focused repair contract
```

适用场景：

- verifier failure 很长；
- ProductGradeGate findings 多；
- 修复可能需要排序；
- 多个 failures 之间存在依赖；
- 需要避免 over-repair。

规则：

- repair strategist 不执行；
- 不改 frozen spec；
- 不决定 closure；
- 每个 repair proposal 必须引用 failure refs。

### 7. Independent Reviewer Agent

当前 `review_required` 是 route boundary，但 reviewer agent 还没有成为默认一等实现。

目标：

```text
当 repeated failure、scope expansion、spec contradiction、quality uncertainty 出现时，
生成 review packet，并允许独立 LLM reviewer 输出 reviewer decision。
```

Reviewer 检查：

- route plan 是否过期；
- next-step contract 是否过大/过小；
- worker 是否隐藏问题；
- verifier 是否太弱；
- 是否需要 spec revision；
- 是否应该 continue / repair / redesign / stop / closure。

规则：

- worker 不能自审；
- reviewer output 是 review artifact；
- review approval 不替代 verifier evidence；
- human authority gate 不能由 LLM reviewer 代替。

## 不该让 LLM 接管的节点

以下必须继续由 deterministic code 控制：

- schema validation；
- safe path validation；
- write scope enforcement；
- locked input tamper check；
- artifact hash；
- command exit code；
- test result；
- forbidden path / forbidden claim；
- graph state persistence；
- registry approval；
- final closure status；
- budget accounting；
- authority escalation；
- human acceptance。

LLM 可以解释这些结果，但不能伪造、覆盖或绕过这些结果。

## 权限模型

新增 LLM 节点必须遵守以下权限等级。

| 权限 | LLM 是否拥有 | 说明 |
| --- | --- | --- |
| propose | 是 | 可以提出 route、contract、repair、review 建议 |
| interpret | 是 | 可以解释 failure、unknown、recommendation |
| execute | 只有 worker LLM 拥有 | 只能在 ForgeUnit allowed scope 内执行 |
| commit state | 否 | 只能由 harness/code 写入 durable graph state |
| verify truth | 否 | 由 Verifier / ProductGate / command result 负责 |
| approve registry | 否 | 由 registry gate 负责 |
| expand mission | 否 | 需要 reviewer/human authority |
| revise frozen spec | 否 | 需要 spec revision gate |
| close task | 否 | closure 只能来自 verifier evidence + code route |

## 状态和证据原则

新增 LLM 输出必须遵守：

```text
No raw prompt in graph state.
No raw transcript in graph state.
No package body in graph state.
No command string in API response.
No worker claim as acceptance.
No LLM proposal as fact.
```

所有 LLM proposal 应保存为 artifact refs：

```text
adaptive/proposals/003/steering_proposal.json
adaptive/proposals/003/observation_signal.json
adaptive/proposals/003/contract_adjustment_request.json
adaptive/reviews/003/reviewer_decision.json
```

graph state 只保存：

```json
{
  "latest_steering_proposal": "adaptive/proposals/003/steering_proposal.json",
  "latest_observation_signal": "adaptive/proposals/003/observation_signal.json",
  "latest_contract_adjustment_request": "adaptive/proposals/003/contract_adjustment_request.json"
}
```

## Evidence Reliability

本升级需要开始显式化 evidence reliability，先用离散等级，不做复杂数学权重。

候选等级：

```text
untrusted_worker_claim
llm_interpretation
artifact_ref
command_result
test_result
schema_validation
verifier_result
reviewer_decision
human_acceptance
```

StateCorrection 可以使用这些等级解释为什么修正状态：

```json
{
  "corrected_field": "known_bad",
  "source_ref": "qa/product_grade_report.json",
  "trust_level": "verifier_result",
  "correction": "Runtime fixture coverage is incomplete."
}
```

原则：

```text
高可信 observation 大幅修正状态。
LLM interpretation 只能提出 semantic hypothesis。
worker claim 只能作为 advisory input。
```

## 代码落点

### Product-layer 先行

本升级应先落在 SkillFoundry product layer：

- `src/skillfoundry/adaptive.py`
- `src/skillfoundry/adaptive_workspace.py`
- `src/forgeunit_skillfoundry/adaptive_graph.py`
- `src/forgeunit_skillfoundry/adaptive_codex.py`
- `src/forgeunit_skillfoundry/adaptive_benchmark.py`
- `tests/test_adaptive_schema.py`
- `tests/test_adaptive_workspace.py`
- `tests/test_adaptive_graph.py`
- `tests/test_adaptive_steering_benchmark.py`

不要直接重写 ContextForge / ForgeUnit。

原因：

- 当前 schema 仍带 SkillFoundry 领域语义；
- 真实 pilot 还不够；
- 需要先验证 LLM proposal pattern；
- 底座 API 过早冻结会制造错误抽象。

### 未来下沉候选

如果跨多个 product/pilot 稳定，可下沉：

- `WorkUnitContract`
- `WorkUnitObservation`
- `ContractAdjustmentRequest`
- `ObservationSignal`
- `StateCorrection`
- `DecisionLedger`
- `EvidenceReliability`
- `ReviewerDecision`

归属建议：

```text
ForgeUnit:
  WorkUnitContract
  WorkUnitObservation
  ContractAdjustmentRequest
  WorkerEvidenceManifest

ContextForge:
  StateEstimate
  StateCorrection
  DecisionLedger
  ObservationSignal
  EvidenceReliability
  Checkpoint / Replay

SkillFoundry:
  CapabilityBundleManifest
  ProductGradeGate
  BundleVerifier
  Registry policy
  SkillFoundry product profiles
```

## 实现路径

### Phase 0: Lock current behavior

目标：

```text
确保默认 deterministic/offline path 不变。
```

要求：

- `make test` 仍不调用 live LLM；
- `adaptive_codex` 无 command 时仍使用 fake command；
- FrontDesk 无 `frontdesk_client_factory` 时仍走 fake/goal-harness path；
- current adaptive benchmark 不退化。

新增测试：

- no live LLM by default；
- LLM proposal mode opt-in only；
- graph state 不出现 raw prompt / raw model output。

### Phase 1: Add schema objects

在 `src/skillfoundry/adaptive.py` 增加：

- `SteeringProposal`
- `ContractAdjustmentRequest`
- `ObservationSignal`
- `EvidenceReliability`
- `ReviewerDecision`

要求：

- JSON round trip；
- unknown fields fail；
- unsafe refs fail；
- forbidden raw keys fail；
- confidence finite in `[0, 1]`；
- `authority_required` enum；
- `trust_level` enum；
- `requested_change` enum。

### Phase 2: Add workspace artifact helpers

在 `src/skillfoundry/adaptive_workspace.py` 增加 refs：

```text
adaptive/proposals/{iteration}/steering_proposal.json
adaptive/proposals/{iteration}/contract_adjustment_request.json
adaptive/proposals/{iteration}/observation_signal.json
adaptive/reviews/{iteration}/reviewer_decision.json
```

要求：

- manifest-tracked；
- refs stable；
- safe path；
- locked input checks still pass；
- read/write helpers round trip。

### Phase 3: Deterministic fake proposers

先不要接 live LLM。

实现 deterministic fake proposer，用于证明协议：

- fake steering proposer；
- fake observation interpreter；
- fake reviewer；
- fake contract adjustment requester。

目标：

```text
先证明 proposal -> validation -> commit 的机制正确。
```

测试场景：

- valid proposal committed；
- malformed proposal rejected；
- unsafe scope rejected；
- closure proposal rejected；
- spec revision proposal routes to review；
- accepted proposal writes decision ledger；
- rejected proposal also writes decision ledger。

### Phase 4: Harness proposal validation

在 adaptive graph 中增加 proposal validation layer。

候选函数：

```text
_validate_steering_proposal(...)
_contract_from_accepted_proposal(...)
_validate_contract_adjustment_request(...)
_observation_signal_from_interpreter(...)
```

Validation 必须检查：

- `job_id` match；
- `iteration` match；
- all refs safe；
- proposed `allowed_scope` subset policy；
- no forbidden paths；
- expected outputs under allowed scope；
- no closure route unless verifier already supports closure；
- no frozen spec mutation；
- no raw prompt/transcript fields；
- proposal has source refs；
- confidence exists but does not grant authority。

### Phase 5: Opt-in LLM proposal mode

增加 opt-in config：

```python
AdaptiveGraphConfig(
    steering_policy="deterministic" | "llm_proposal",
)
```

或更保守：

```python
AdaptiveGraphConfig(
    llm_steering_proposals=False,
)
```

默认必须是 `False`。

LLM proposal node 通过 ContextForge owned LLM call 执行：

```text
StateEstimate + RoutePlan + Observation refs + verifier refs
  -> prompt/context projection
  -> JSON proposal
  -> schema validation
  -> harness validation
  -> committed contract
```

要求：

- live client 必须显式注入；
- 无 client 时 fail closed 或走 fake proposer；
- provider/model/usage 写入 evidence；
- raw prompt/model output 不进入 graph state。

### Phase 6: Observation interpretation mode

增加 opt-in observation interpreter：

```text
ObservationReport + VerifierResult + ProductGradeReport
  -> LLM ObservationSignal
  -> StateCorrection input
```

StateCorrection 仍由 code 提交。

测试：

- signal captured by ref；
- state uses safe summary only；
- raw recommendation 不进入 graph state；
- LLM signal 不能让 failed verifier 变 closure。

### Phase 7: Reviewer agent gate

把 `review_required` 从终态边界升级为可恢复 review protocol：

```text
review_required
  -> review packet
  -> independent reviewer decision
  -> resume / redesign / spec_revision / stop
```

要求：

- reviewer != worker；
- stale review rejected；
- reviewer approval 不替代 verifier；
- human authority gate 不由 reviewer agent 代替。

### Phase 8: Benchmark upgrade

扩展 `tests/test_adaptive_steering_benchmark.py`。

新增压力场景：

1. contract too broad -> LLM proposes split；
2. contract too narrow -> LLM proposes expand within authority；
3. verifier failure root cause ambiguous -> observation interpreter identifies likely root cause；
4. worker asks spec revision -> review_required；
5. LLM proposes unsafe scope -> rejected；
6. LLM proposes closure without verifier -> rejected；
7. reviewer rejects stale route plan -> redesign；
8. live-like fake proposer improves iteration count over deterministic baseline。

指标：

- final verified bundle success；
- average iterations；
- repair loop count；
- unsafe proposal rejection count；
- accepted proposal count；
- rejected proposal count；
- review boundary count；
- graph state raw leakage count；
- verifier false-success resistance。

### Phase 9: Live pilot

只有 deterministic protocol 稳定后，才做 live pilot。

推荐顺序：

1. prompt-only simple skill；
2. script_tool skill；
3. code-runtime Codexarium-like bundle；
4. knowledge-runtime bundle；
5. MCP-like bundle；
6. service-runtime bundle。

每个都跑：

```text
baseline deterministic steering
vs
LLM proposal steering
```

比较：

- success rate；
- iterations；
- repair loops；
- product-grade pass；
- final bundle usefulness；
- cost；
- latency；
- rejected proposal rate；
- reviewer intervention rate。

## 成功标准

这次升级成功，不是因为“用了 LLM”。

成功标准是：

```text
LLM proposal 提升复杂任务适应能力，
但没有削弱边界、证据、验收和可审计性。
```

具体标准：

- deterministic default path 不退化；
- live LLM 仍显式 opt-in；
- LLM proposal 全部 manifest-tracked；
- unsafe proposal 被拒绝；
- failed verifier 不能被 LLM 改成 closure；
- worker claim 不能成为 acceptance；
- accepted/rejected proposal 都进入 DecisionLedger；
- review_required 可以接 reviewer packet；
- benchmark 显示复杂场景质量提升；
- graph/product state 仍 refs-only；
- SkillFoundry product rules 不下沉到 ForgeUnit / ContextForge。

## 最终结论

下一轮升级的核心不是“更多代码约束”，也不是“更多大模型自由”。

核心是：

```text
在不确定性最高的节点引入 LLM 超级智能，
但把它输出的所有判断都降级为可验证 proposal。
```

当前系统已经有笼子：

- frozen spec；
- refs-only state；
- bounded work unit；
- verifier；
- review boundary；
- registry gate；
- deterministic default path。

下一步要做的是：

```text
给笼子里的智能更多战术判断空间，
但不交出状态提交权、验收权和边界扩张权。
```

这将把当前 adaptive steering 从：

```text
deterministic product-layer control loop
```

推进到：

```text
controlled LLM-assisted adaptive steering loop
```

这也是通向通用 agent work substrate 的关键一步。
