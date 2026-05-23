# SkillFoundry Front Desk Agent Roadmap

版本：v0.2
日期：2026-05-17
适用范围：SkillFoundry WP13-WP17，面向真实 LLM 需求澄清、规格冻结、验收覆盖和真实 builder 试点

> 状态说明：本文是 Front Desk WP13-WP17 设计形成文档。WP15B Front Desk Loop、WP16 Acceptance Coverage Bridge、WP17 Owned LLM Builder Pilot 已在后续实现中完成。本文中 “next / blocking / blocked” 等状态只保留为历史上下文。当前 v2 技术执行源是 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`，当前接手状态见 `HANDOFF.md`；`docs/DEVELOPMENT_ROADMAP.md` 仅作为 v0 / WP0-WP17 能力基线和产品经验记录。

## 1. 一句话结论

SkillFoundry 下一阶段最重要的不是马上增强 builder，而是先把需求澄清层做成真实可用的双 Agent 系统：

```text
Requirements Elicitor Agent
+ Spec Auditor Agent
+ deterministic FrontDeskFreezeGate
+ LangGraph clarification loop
+ ContextForge owned LLM call record
+ frozen SkillSpec / AcceptanceCriteria / FeasibilityReport
```

核心原则：

- Front Desk 决定平台上限；
- Builder 决定执行下限；
- 需求没澄清清楚时，任何 builder 都不应该启动；
- Elicitor 负责主动推进对话；
- Auditor 负责客观审查风险、缺口和可行性；
- FrontDeskFreezeGate 负责用确定性规则决定是否允许冻结规格；
- 所有自有 LLM 调用必须通过 ContextForge 记录；
- 所有最终规格必须落入 workspace 文件，并被 hash、manifest 和后续 QA/Verifier 使用。

## 2. 历史基线快照

以下内容是 WP15 附近的历史基线说明，不代表当前待办状态。当前 v2 重构蓝图见 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`，当前接手状态见 `HANDOFF.md`；WP0-WP17 完成状态只应从 `docs/DEVELOPMENT_ROADMAP.md` 读取为历史能力基线。

截至 WP15，SkillFoundry 已经具备：

```text
LangGraph refs-only workflow
ContextForge owned LLM call adapter
Workspace file-as-context protocol
WorkerAdapter / FakeWorker / CodexWorker pilot boundary
Independent Verifier
QA Lab
Registry
Feedback + Versioning
Ops health / observability / cleanup
Front Desk schema/workspace protocol
RequirementsElicitor owned LLM boundary
SpecAuditor owned LLM boundary
deterministic FrontDeskFreezeGate
```

当前默认路径仍然是离线 deterministic worker。WP14/WP15 已经把真实 LLM 节点的边界、schema、落盘和失败兜底做出来，但默认测试仍使用 fake/scripted client，不调用真实 provider。

当时的重要状态修正：

- WP13-WP15 已完成的是 `schema/workspace`、`RequirementsElicitor`、`SpecAuditor`、`FrontDeskFreezeGate` 的部件级实现；
- 这还不等于 Front Desk 端到端闭环完成；
- `ask_user -> elicit -> audit -> freeze/human/reject` 的 LangGraph 多轮状态机在当时仍是下一步阻塞项；
- WP16 的验收覆盖闭环完成前，不能把 `planned` coverage 当作 Registry approved 的事实证据；
- WP17 的真实 builder 试点在当时必须等 Front Desk loop 和 WP16 coverage gate 可用后再进入主线。

当时的剩余缺口：

- 没有多轮澄清状态机；
- 没有把 acceptance criteria 稳定转换为 QA/Verifier 输入；
- 没有真实用户对话 transcript 的治理、摘要和冻结机制。
- 没有从 frozen spec 启动真实 builder 的受控试点；
- 没有面向真实 provider 的 opt-in smoke 与成本观测闭环。
- FreezeGate 的风险、隐私、预算确定性策略还需要继续硬化；
- Elicitor 输出到 draft artifact 的自动物化还没有接入流水线。

## 3. 目标

构建一个真实可用的 Front Desk 层，将模糊自然语言需求转化为可构建、可验证、可审计的 Skill 需求规格。

目标输出：

```text
runs/<job_id>/
  conversation.jsonl
  clarification_summary.md
  elicitation_report.json
  draft_skill_spec.yaml
  acceptance_criteria.yaml
  feasibility_report.json
  spec_audit_report.json
  freeze_manifest.json
  skill_spec.yaml
  verification_spec.yaml
  build_contract.yaml
  worker_input.md
```

最终 `skill_spec.yaml`、`acceptance_criteria.yaml`、`verification_spec.yaml`、`build_contract.yaml` 和 `worker_input.md` 必须成为后续 builder、Verifier、QA Lab、Registry 的输入事实。

## 4. 非目标

本阶段不做：

- 不实现完整生产级客服系统；
- 不做多租户权限；
- 不做通用 Agent OS；
- 不让 Codex Agent Thread 接管需求澄清大脑；
- 不让 builder 自行决定需求是否清楚；
- 不让 LLM judge 成为唯一验收门；
- 不把完整原始对话塞进 LangGraph state；
- 不要求一开始接真实 CodexWorker；
- 不要求本阶段完成知识图谱或多 Skill 自动组合。

Codex Agent / CodexWorker 可以在后续作为 builder 使用，但 Front Desk 的主控逻辑应该由 SkillFoundry 自己通过 OpenAI API + ContextForge + LangGraph 实现。

## 5. 总体架构

```text
User Conversation
  |
  v
+--------------------------------------------------------------+
| LangGraph Front Desk Loop                                    |
| state: refs, round_count, readiness, risk_flags, next_action |
+--------------------------------------------------------------+
  |
  v
+---------------------------+      +---------------------------+
| Requirements Elicitor     | ---> | Draft Spec / Questions    |
| owned LLM via ContextForge|      | workspace artifacts       |
+---------------------------+      +---------------------------+
  |
  v
+---------------------------+      +---------------------------+
| Spec Auditor / Critic     | ---> | Audit decision            |
| owned LLM via ContextForge|      | feasibility + testability |
+---------------------------+      +---------------------------+
  |
  v
+---------------------------+      +---------------------------+
| FrontDeskFreezeGate       | ---> | deterministic gate result |
| non-LLM validation node   |      | freeze manifest decision  |
+---------------------------+      +---------------------------+
  |
  +--> needs_more_clarification --> ask_user
  |
  +--> approved --> freeze SkillSpec / AcceptanceCriteria / VerificationSpec
  |
  +--> infeasible --> reject_or_human_review
  |
  +--> human_review_required --> human_gate
```

### 5.1 为什么不让 Codex Agent 做 Front Desk

Front Desk 的核心不是写代码，而是决定：

- 问什么问题；
- 为什么这些信息足够；
- 哪些假设仍然不安全；
- 是否可以进入构建；
- 验收标准是否可测试。

这些判断必须被平台审计、复现和路由。Codex Agent Thread 更适合作为高能力 builder，而不是平台大脑。

推荐分工：

```text
OpenAI API + ContextForge + LangGraph:
  Front Desk, Brain, Spec, Acceptance Criteria, Audit Gate

CodexWorker / CodexAgentThreadWorker:
  Factory Floor builder, scripts, package generation, code edits
```

### 5.2 为什么 Auditor 也不能单独冻结规格

Auditor 虽然是独立 critic，但它仍然是 LLM 调用。它可以发现缺口、打分、建议追问和路由，但不能单独决定进入构建。

真正的冻结动作必须由确定性节点完成：

```text
Elicitor output
  + Auditor output
  + schema validation
  + risk policy
  + acceptance coverage precheck
  + manifest/hash checks
  -> FrontDeskFreezeGate
  -> freeze or ask_user/human_review/reject
```

这保持了既有工程纪律：

- LLM 可以建议；
- LangGraph deterministic node 做路由；
- Verifier/QA/Registry 继续作为后续质量和资产边界；
- builder 永远只能在 frozen spec 之后启动。

## 6. 双 Agent 职责

### 6.1 Requirements Elicitor Agent

职责：

- 主动理解用户模糊需求；
- 识别缺失字段；
- 追问最小但关键的问题；
- 将对话压缩成结构化 draft spec；
- 生成初版 acceptance criteria；
- 维护当前理解和风险提示；
- 避免过早进入构建。

输入：

```text
conversation.jsonl
previous_clarification_summary.md
SkillSpec schema
AcceptanceCriteria schema
platform capability boundary
optional registry summary
```

输出：

```json
{
  "schema_version": "skillfoundry.elicitation_report.v1",
  "readiness_guess": "needs_clarification | ready_for_audit",
  "current_understanding": "...",
  "known_fields": {},
  "missing_fields": [],
  "risk_flags": [],
  "next_questions": [],
  "draft_skill_spec": {},
  "draft_acceptance_criteria": [],
  "assumptions": []
}
```

要求：

- 单轮最多追问 3-7 个问题；
- 问题必须按影响排序；
- 不允许问宽泛的“请补充更多信息”；
- 必须解释每个问题对应的缺失字段；
- 如果用户已经给出足够信息，必须输出 `ready_for_audit`。
- Elicitor 只能写 draft、report、questions 和 summary，不能写 frozen spec，不能触发 build。

建议 `next_questions` 使用结构化格式：

```json
{
  "question_id": "Q-001",
  "text": "...",
  "missing_field_path": "input.format",
  "reason": "...",
  "priority": "must | should | could",
  "answer_type": "free_text | enum | file | example",
  "blocks_build": true
}
```

### 6.2 Spec Auditor / Critic Agent

职责：

- 从客观审核方角度判断需求是否真的清楚；
- 审核 draft spec 是否可构建、可测试、可安全执行；
- 审核 acceptance criteria 是否可验证；
- 判断是否需要人工熔断；
- 给出最少必要追问问题；
- 给出路由建议。

输入：

```text
conversation.jsonl
elicitation_report.json
draft_skill_spec.yaml
acceptance_criteria.yaml
platform capability boundary
registry summary optional
QA/Verifier capability boundary
```

输出：

```json
{
  "schema_version": "skillfoundry.spec_audit_report.v1",
  "decision": "approved | needs_more_clarification | infeasible | human_review_required",
  "clarity_score": 0.0,
  "feasibility_score": 0.0,
  "testability_score": 0.0,
  "risk_score": 0.0,
  "missing_requirements": [],
  "unsafe_assumptions": [],
  "required_followup_questions": [],
  "spec_patch_suggestions": [],
  "routing_recommendation": "reuse_existing | prompt_only | rag | script_required | codex_worker | human_review",
  "approval_rationale": ""
}
```

硬规则：

- Auditor 不能因为 Elicitor 自信就批准；
- `approved` 必须要求 clarity、feasibility、testability 达到阈值；
- 存在不可验证验收标准时不得批准；
- 存在隐私、合规、外部 API、真实世界高风险判断时必须标记风险；
- 如果只差少量信息，输出最少必要追问，而不是泛泛拒绝。
- Auditor 只能写 audit、feasibility 和 recommendation，不能写 frozen spec，不能触发 build。
- Auditor 的 `approved` 只是 FrontDeskFreezeGate 的输入之一，不是最终冻结决定。

`FeasibilityReport` 默认由 Auditor 产出，由 FrontDeskFreezeGate 校验。Elicitor 不生成最终 feasibility，避免“写作者自评可行性”。

### 6.3 FrontDeskFreezeGate

职责：

- 用非 LLM 规则决定能否冻结规格；
- 校验 Elicitor 和 Auditor 输出是否结构化、完整、可追溯；
- 校验风险、预算、人工门、验收覆盖和 manifest；
- 写入 `freeze_manifest.json`；
- 生成或触发生成 `build_contract.yaml`；
- 给 LangGraph 返回确定性的 `next_action`。

输入：

```text
conversation.jsonl
clarification_summary.md
elicitation_report.json
draft_skill_spec.yaml
acceptance_criteria.yaml
feasibility_report.json
spec_audit_report.json
frontdesk config / risk policy
```

输出：

```json
{
  "schema_version": "skillfoundry.frontdesk_freeze_gate.v1",
  "decision": "freeze | ask_user | human_review_required | reject",
  "blocking_reasons": [],
  "warnings": [],
  "frozen_artifact_refs": {},
  "freeze_manifest_ref": "frontdesk/freeze_manifest.json",
  "next_action": "route_to_build"
}
```

必检项：

- schema round-trip；
- unknown field fail；
- score range；
- required field completeness；
- unresolved assumptions；
- risk tags；
- acceptance criterion id 唯一；
- must criteria evidence coverage；
- LLM-only must criterion 禁止；
- manual-only criterion 进入 human gate；
- PII/secret redaction status；
- provider usage/cost budget；
- manifest/hash 完整性；
- `skill_spec.yaml`、`acceptance_criteria.yaml`、`verification_spec.yaml`、`worker_input.md`、`build_contract.yaml` 全部被锁定。

## 7. 状态机

LangGraph state 只保存轻量引用：

```json
{
  "job_id": "...",
  "stage": "front_desk",
  "clarification_round": 2,
  "readiness": "needs_clarification",
  "latest_elicitation_report_ref": "frontdesk/elicitation_report_002.json",
  "latest_audit_report_ref": "frontdesk/spec_audit_report_002.json",
  "skill_spec_ref": null,
  "acceptance_criteria_ref": null,
  "verification_spec_ref": null,
  "next_action": "ask_user",
  "human_review_required": false
}
```

状态流转：

```text
new_conversation
  -> elicit
  -> validate_elicitation_output
  -> audit
  -> validate_audit_output
  -> deterministic_readiness_gate
  -> ask_user
  -> elicit
  -> audit
  -> deterministic_readiness_gate
  -> freeze_spec
  -> freeze_manifest_written
  -> route_to_build
```

失败和熔断：

```text
round_limit_exceeded -> human_review_required
unsafe_request -> reject_or_human_review
infeasible -> reject_or_human_review
low_testability -> needs_more_clarification
provider_failure -> fail_closed
parse_repair_retry_exhausted -> fail_closed
manual_only_must_criterion -> human_review_required
freeze_gate_failed -> ask_user_or_human_review
human_review_resolved -> freeze_spec_or_reject
```

建议默认参数：

```text
max_clarification_rounds = 10
min_clarity_score = 0.75
min_feasibility_score = 0.70
min_testability_score = 0.75
max_followup_questions_per_round = 1
max_frontdesk_model_calls = 40
max_parse_repair_attempts = 2
provider_timeout_seconds = 60
max_output_tokens_per_call = 4096
```

Front Desk state 仍然只保存轻量引用，不保存完整 conversation、raw prompt 或完整 model output。

建议增加引用字段：

```json
{
  "frontdesk_budget_ref": "frontdesk/budget.json",
  "risk_report_ref": "frontdesk/risk_report.json",
  "freeze_gate_result_ref": "frontdesk/freeze_gate_result.json",
  "freeze_manifest_ref": "frontdesk/freeze_manifest.json",
  "acceptance_coverage_plan_ref": "frontdesk/acceptance_coverage_plan.json"
}
```

## 8. 文件和 Schema

### 8.1 新增 workspace 路径

```text
runs/<job_id>/
  frontdesk/
    conversation.jsonl
    elicitation_report_001.json
    spec_audit_report_001.json
    elicitation_report_002.json
    spec_audit_report_002.json
    clarification_summary.md
    draft_skill_spec.yaml
    acceptance_criteria.yaml
    feasibility_report.json
    freeze_gate_result.json
    freeze_manifest.json
    budget.json
    risk_report.json
```

冻结后同步到现有根级输入：

```text
runs/<job_id>/
  skill_spec.yaml
  acceptance_criteria.yaml
  verification_spec.yaml
  build_contract.yaml
  worker_input.md
```

`build_contract.yaml` 必须在 Front Desk freeze 后生成，或由紧随其后的 build preparation 节点生成。无论由谁生成，都必须在 builder 启动前写入 locked input hashes，并进入 artifact manifest。

`freeze_manifest.json` 至少记录：

```json
{
  "schema_version": "skillfoundry.freeze_manifest.v1",
  "conversation_summary_hash": "...",
  "conversation_turn_range": [1, 8],
  "elicitation_report_ref": "frontdesk/elicitation_report_002.json",
  "spec_audit_report_ref": "frontdesk/spec_audit_report_002.json",
  "skill_spec_ref": "skill_spec.yaml",
  "acceptance_criteria_ref": "acceptance_criteria.yaml",
  "verification_spec_ref": "verification_spec.yaml",
  "worker_input_ref": "worker_input.md",
  "build_contract_ref": "build_contract.yaml",
  "artifact_hashes": {}
}
```

### 8.2 新增 schema

建议新增：

```text
ConversationTurn
ElicitationReport
AcceptanceCriterion
AcceptanceCriteriaSet
FeasibilityReport
SpecAuditReport
FrontDeskState
FrontDeskConfig
```

`AcceptanceCriterion` 建议结构：

```yaml
id: AC-001
description: ""
source_requirement: ""
source_turn_ids: []
requirement_id: ""
test_method: static | fixture | llm_judge | human_review | manual_check
pass_condition: ""
failure_examples: []
required_evidence: []
evidence_kind: file | command | qa_report | verifier_check | human_note | model_judge
priority: must | should | could
risk_tags: []
data_sensitivity: public | internal | confidential | restricted
verifier_check_id: ""
fixture_ref: ""
manual_authority: ""
coverage_status: planned | covered | manual_only | uncovered
unverifiable_reason: ""
```

### 8.3 与现有 SkillSpec 的关系

现有 `SkillSpec.acceptance_criteria` 是字符串列表，可继续作为兼容字段。

新增 `acceptance_criteria.yaml` 是更强结构：

```text
SkillSpec.acceptance_criteria:
  人类可读摘要，保持兼容

AcceptanceCriteriaSet:
  QA/Verifier 可用的结构化验收标准
```

## 9. ContextForge 集成

Front Desk 的两类 LLM 调用都是 SkillFoundry-owned LLM call，必须通过 ContextForge：

```text
SkillFoundry FrontDeskAgent
  -> ContextRequest
  -> PromptView
  -> ModelCallEnvelope
  -> ContextKernel.invoke_model()
  -> ModelCallRecord
  -> replay artifact
  -> workspace artifact
```

每次调用必须记录：

- agent role：`requirements_elicitor` 或 `spec_auditor`；
- model name；
- prompt view hash；
- input artifact refs；
- output artifact refs；
- structured output parse result；
- usage；
- error；
- replay artifact ref。

如果真实 provider 不可用，测试路径必须使用 fake/deterministic model client。

安全和隐私要求：

- 原始 `conversation.jsonl` 视为不可信用户输入；
- 用户文本不得被当作 system/developer 指令；
- registry summary、platform boundary、schema 和用户输入必须分块标注 trust boundary；
- 对 secrets、客户名、凭据、内部项目代号等敏感内容记录 redaction status；
- 外部 API、文件读取、联网和凭据使用必须在 spec 中显式声明权限；
- raw conversation 不直接进入后续 builder prompt，必须经过 summary/governance；
- cleanup/retention 必须保留 provenance，同时允许按策略清理或脱敏敏感 transcript。

成本和稳定性要求：

- 每个 job 必须有 token/cost/model-call budget；
- 每次 provider 调用必须有 timeout；
- structured output parse 失败只允许有限次 repair；
- usage 不可得时必须记录 reason；
- 默认测试不得依赖真实 provider；
- live provider smoke 必须 opt-in。

## 10. QA/Verifier 接入

Front Desk 不能只生成漂亮文档，必须把 acceptance criteria 接入后续质量系统。

建议路径：

```text
AcceptanceCriteriaSet
  -> VerificationSpec generator
  -> QA test plan generator
  -> Verifier static checks
  -> optional LLM judge input
  -> final_report coverage section
```

QA Lab 至少应该输出：

```json
{
  "acceptance_coverage": {
    "total": 8,
    "covered": 6,
    "manual_only": 1,
    "uncovered": 1
  }
}
```

硬规则：

- Verifier 仍是主质量门；
- LLM judge 不能单独放行；
- `manual_check` 类型必须进入人工验收或 beta reviewer note；
- 未覆盖的 must criteria 不能注册为 approved。
- QA Lab/Verifier 负责计算 acceptance coverage 和 pass/fail；
- Registry 只消费 Verifier/QA 输出的 hash、pass 字段和 provenance，不计算 coverage，不承担评价逻辑。

## 11. 分阶段开发计划

```text
+------+--------------------------------+-------------------------------+------------------------------+------------------------------+
| WP   | Phase                          | Primary Output                | Core Gate                    | Status                       |
+------+--------------------------------+-------------------------------+------------------------------+------------------------------+
| WP13 | Front Desk Schema + Workspace  | conversation/spec/audit files | deterministic schema tests   | done                         |
| WP14 | LLM Elicitor Agent             | elicitation node + artifacts  | asks targeted questions      | done                         |
| WP15 | Auditor + Freeze Gate          | objective audit + hard gate   | no premature build           | component done               |
| WP15B| Front Desk LangGraph Loop      | multi-round clarification     | route/freeze/human/reject    | historical: now done         |
| WP16 | Acceptance Criteria to QA       | QA/Verifier coverage bridge   | criteria drive evaluation    | historical: now done         |
| WP17 | Real Builder Integration       | Codex/LLM builder from spec   | verified real skill output   | historical: pilot now done   |
+------+--------------------------------+-------------------------------+------------------------------+------------------------------+
```

当前实现证据：

```text
WP13 commit: 3197858 Add Front Desk schema workspace foundation
WP14 commit: f94ecab Add Requirements Elicitor frontdesk agent
WP15 component commit: 84ade40 Add Spec Auditor and Front Desk freeze gate
Targeted Front Desk tests: 74 passed
```

### WP13：Front Desk Schema + Workspace

目标：

- 建立需求澄清文件协议；
- 定义 conversation、elicitation、audit、acceptance criteria、feasibility schema；
- 扩展 workspace 初始化和 manifest；
- 保持所有测试离线确定性。

交付物：

- `src/skillfoundry/frontdesk_schema.py` 或扩展 `schema.py`
- `src/skillfoundry/frontdesk_workspace.py`
- `tests/test_frontdesk_schema.py`
- `tests/test_frontdesk_workspace.py`
- docs 更新

验收门：

- schema round-trip；
- unknown field fail；
- score range validation；
- acceptance criteria id 唯一；
- conversation append-only；
- frontdesk artifacts 进入 manifest；
- LangGraph state 不保存完整 conversation。

### WP14：LLM Requirements Elicitor Agent

目标：

- 用 OpenAI API 或可替换 model client 实现真实需求澄清；
- 默认测试使用 deterministic fake model；
- 输出结构化 elicitation report；
- 可生成下一轮追问或 ready_for_audit。

交付物：

- `src/skillfoundry/frontdesk.py`
- `RequirementsElicitor`
- prompt template / prompt builder
- ContextForge call wrapper
- `tests/test_frontdesk_elicitor.py`

验收门：

- 模糊需求会产生目标明确的追问；
- 已清晰需求会进入 `ready_for_audit`；
- 单轮问题数受限；
- 每个问题关联 missing field；
- 输出可 parse、可 validate、可落盘；
- provider failure 会 fail-closed，不生成假 spec。

### WP15：Spec Auditor + FrontDeskFreezeGate

目标：

- 实现独立审核 Agent；
- 实现确定性 FrontDeskFreezeGate；
- 阻止不清楚、不可行、不可测试需求进入构建；
- 输出 feasibility、routing 和最少追问。

交付物：

- `SpecAuditor`
- `FrontDeskFreezeGate`
- audit rubric
- freeze rubric
- `freeze_manifest.json`
- `tests/test_frontdesk_auditor.py`
- `tests/test_frontdesk_freeze_gate.py`

验收门：

- 缺输入格式时不得 approved；
- 缺验收标准时不得 approved；
- 不可测试标准不得 approved；
- 高风险需求进入 human_review；
- approved 后冻结 `skill_spec.yaml`、`acceptance_criteria.yaml`、`verification_spec.yaml`；
- 冻结前必须生成或触发生成 `build_contract.yaml`；
- frozen artifacts 必须写入 `freeze_manifest.json` 和 artifact manifest；
- Auditor approved 但 FreezeGate fail 时不能进入构建；
- round limit 进入 human review。

当时状态：

- `SpecAuditor` 已实现为 ContextForge owned LLM call；
- `FrontDeskFreezeGate` 已实现为 non-LLM deterministic gate；
- 单元级测试已覆盖 auditor/freeze gate；
- `frontdesk_graph` 和多轮 loop 不归入 WP15 已完成范围，拆到 WP15B。

### WP15B：Front Desk LangGraph Loop

目标：

- 把 Elicitor、Auditor、FreezeGate 串成真正可执行的多轮 Front Desk；
- 支持 `ask_user -> elicit -> audit -> freeze/human/reject` 路由；
- 保持 LangGraph state refs-only，不保存完整 conversation、raw prompt 或完整 model output；
- 将 Elicitor 的 `draft_skill_spec`、`draft_acceptance_criteria` 自动物化为 workspace artifacts；
- 增加 summary/redaction/retention 的最小治理接口，避免长对话直接无限进入 prompt。

交付物：

- `frontdesk_graph` 或等价 LangGraph node 组合；
- `FrontDeskLoopState` 或现有 `FrontDeskState` 的路由字段扩展；
- `tests/test_frontdesk_loop.py`；
- draft artifact materializer；
- round limit / human gate / provider failure / parse failure 路由测试；
- conversation summary artifact 接入点。

验收门：

- 模糊需求第一轮进入 `needs_clarification`，不会启动 builder；
- 用户补充信息后能重新进入 Elicitor/Auditor；
- Auditor approved 但 FreezeGate fail 时回到 clarification 或 human gate；
- high-risk / privacy / unsafe data access 进入 human review；
- round limit 到达后进入 human review；
- frozen 后写入 locked refs，后续 builder 只能读取 frozen inputs；
- LangGraph state 中没有完整 transcript、raw prompt、raw model output、大文本 blob；
- 默认测试不调用真实 provider、网络或 Codex。

### WP16：Acceptance Criteria to QA/Verifier

目标：

- 将结构化验收标准转为 QA/Verifier 可执行计划；
- 在 final report 中展示 acceptance coverage；
- 未覆盖 must criteria 不进入 approved registry。

交付物：

- `AcceptanceCriteriaPlanner`
- `VerificationSpec` 生成增强；
- QA Lab coverage report；
- final report coverage section；
- registry provenance gate 增强；
- `tests/test_acceptance_coverage.py`

验收门：

- freeze/build 前允许 `planned` coverage，但 Registry approved 前不允许 must criteria 停留在 `planned`；
- must criteria 必须有实际 evidence 或明确 manual authority；
- manual-only criteria 被明确标记；
- bad skill 能按 criteria fail；
- good skill 能按 criteria pass；
- coverage 写入 final_report；
- QA/Verifier 对未覆盖 must criteria 输出 fail；
- registry 只检查 QA/Verifier pass、coverage result hash 和 provenance，不自己计算 coverage。

关键语义：

```text
planned          只表示 build 前覆盖计划，不是验收事实
covered/pass     有证据且通过
covered/fail     有证据但失败
manual_only      需要人工验收权威
uncovered        没有可接受证据
```

Registry 只能消费 `acceptance_coverage_result.json` 的 `passed=true`、hash 和 provenance；不能自己重新计算 coverage，也不能因为 LLM judge 的文字判断而批准资产。

### WP17：Real Builder Integration

目标：

- 在 Front Desk 输出可信 spec 后，接入真实 builder；
- 可以先接 OpenAI API skill builder，也可以接 CodexAgentThreadWorker；
- builder 仍然必须通过 WorkerAdapter 和 Verifier。

交付物：

- `LLMSkillBuilderWorker` 或 `CodexAgentThreadWorker`
- real builder pilot docs
- live opt-in tests / manual pilot
- builder boundary evidence

验收门：

- 给定 frozen spec，builder 不读取 raw conversation；
- builder 不修改 locked inputs；
- builder 输出完全基于 frozen spec；
- Verifier/QA/Registry 仍是最终 gate；
- Codex 内部仍作为 external boundary，不被 ContextForge 假装 replay。

## 12. 风险和控制

```text
+------+--------------------------------------+------------------------------------------+
| Risk | Description                          | Control                                  |
+------+--------------------------------------+------------------------------------------+
| R1   | Elicitor 过早认为需求清楚            | Auditor gate + score thresholds          |
| R2   | Auditor 过度保守导致体验差           | 最少必要追问 + round limit + human gate  |
| R3   | LLM 输出 JSON 不稳定                 | schema validation + repair parse retry   |
| R4   | 成本失控                             | ContextForge usage + max rounds + budget |
| R5   | prompt injection                     | trust boundary + governed artifacts      |
| R6   | 验收标准不可测试                     | testability score + QA coverage gate     |
| R7   | conversation 太长                    | summary artifact + refs-only state       |
| R8   | Codex builder 黑盒污染需求判断       | builder only after frozen spec           |
| R9   | fake tests 掩盖真实 provider failure | opt-in live smoke + failure fixtures      |
| R10  | LLM Auditor 被误当硬 gate            | deterministic FrontDeskFreezeGate        |
| R11  | 原始对话含敏感信息                   | redaction status + retention policy      |
| R12  | Registry 职责漂移                    | consume verified hashes, no evaluation   |
+------+--------------------------------------+------------------------------------------+
```

Front Desk observability 至少记录：

- clarification rounds；
- questions count；
- audit decision distribution；
- human review rate；
- provider failures；
- parse retries；
- token/cost；
- latency；
- acceptance coverage ratio；
- must uncovered count；
- freeze gate failure reason。

## 13. 最小可用演示

目标 demo：

```text
用户：我想做一个帮团队写周报的 skill。

Elicitor：
1. 周报输入来自聊天记录、git commit、工单，还是手动输入？
2. 输出格式是个人周报、团队周报，还是管理层摘要？
3. 是否需要过滤敏感客户名、金额或内部项目代号？
4. 什么样的结果算通过？请给一个好周报样例或评价标准。

用户回答后：
  -> Elicitor 生成 draft spec
  -> Auditor 判断缺少数据来源权限说明
  -> 再追问一次
  -> Auditor approved
  -> freeze SkillSpec + AcceptanceCriteria
  -> FakeWorker build
  -> Verifier/QA/Registry
```

成功标准：

- 用户能感受到 Agent 在主动引导；
- 平台不会在需求不清楚时启动构建；
- 最终 spec 和 acceptance criteria 可读、可审查、可追溯；
- 后续 builder 和 QA 不再凭空猜需求。

负向 demo：

```text
用户：我想让 skill 自动读取公司所有聊天记录和客户合同，然后总结销售风险。

预期：
  -> Elicitor 识别数据权限、隐私、合规和输入边界缺失
  -> Auditor 标记 high risk / human_review_required
  -> FrontDeskFreezeGate 不允许进入构建
  -> final/frontdesk report 说明阻塞原因
```

真实 provider 和 CodexWorker 只作为 opt-in smoke，不作为默认 demo 成功条件。

## 14. 推荐立即执行顺序

```text
1. WP13 schema/workspace
2. WP14 Elicitor with deterministic fake model tests
3. WP15 Auditor + FreezeGate and clarification loop
4. WP16 criteria-to-QA bridge
5. WP17 real builder pilot
```

工程判断：

```text
先让需求变清楚，再让 builder 变聪明。
```

只有 Front Desk 能稳定产出高质量 frozen spec，CodexWorker 或 CodexAgentThreadWorker 的真实能力才会被正确使用。

## 15. 第三方审核结论

独立 `gpt-5.5 xhigh` 架构审核结论：`approve_with_changes`。

审核认可：

- 双 Agent 方向科学；
- WP13-WP17 顺序基本可实施；
- 没有让 Codex 接管 Front Desk；
- 保持了 LangGraph refs-only、ContextForge owned LLM call、文件即上下文、Verifier/QA/Registry 边界。

审核要求的关键修正已经纳入本文：

- 增加确定性 `FrontDeskFreezeGate`，Auditor 不再单独冻结规格；
- 明确 Elicitor、Auditor、FreezeGate 的写权限和决策权限；
- 补齐 `build_contract.yaml` 与 locked input/hash/manifest 链路；
- 增加 `freeze_manifest.json`；
- 收紧 WP16 边界：QA/Verifier 计算 coverage，Registry 只消费 pass/hash/provenance；
- 扩展状态机的 validation、provider failure、parse retry、human gate、freeze gate 状态；
- 补充成本、安全、prompt injection、PII/redaction、retention、observability 要求。
