# Front Desk Roadmap Independent Audit

日期：2026-05-17
审核方：独立 `gpt-5.5 xhigh` agent
审核对象：`docs/FRONT_DESK_AGENT_ROADMAP.md`、README、主 roadmap、当前 Front Desk 实现和测试

> 历史状态说明：本文是 Front Desk WP13-WP17 设计阶段的独立审核记录。WP15B Front Desk Loop、WP16 Acceptance Coverage Bridge、WP17 Owned LLM Builder Pilot 已在后续实现中完成。当前 v2 技术执行源是 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`，当前接手状态见 `HANDOFF.md`；`docs/DEVELOPMENT_ROADMAP.md` 仅作为 v0 / WP0-WP17 能力基线和产品经验记录。

## 1. 结论

审核结论：`conditional-go / approve_with_changes`。

路线科学、方向正确、可以继续执行。`RequirementsElicitor + SpecAuditor + deterministic FrontDeskFreezeGate` 的职责拆分是合理的，且当前设计没有把 Codex Agent Thread 错误放到 Front Desk 主控位置，也没有声称 ContextForge 能控制 Codex 内部 prompt、tool loop、context compaction、cache 或 cost。

但当前只能按“有条件继续”推进：WP13-WP15 已完成的是部件级能力，不是 Front Desk 端到端闭环。下一阶段必须先补 `Front Desk LangGraph Loop` 和 `Acceptance Criteria -> QA/Verifier` 覆盖桥，再进入 WP17 真实 builder 主线。

## 2. 已通过的设计检查

- Front Desk 不由 Codex Agent Thread 接管；
- Auditor 不代替 deterministic gate；
- FreezeGate 是 non-LLM 决策节点；
- LangGraph state 坚持 refs-only，不保存完整 transcript、raw prompt、raw model output；
- ContextForge 只管 SkillFoundry 自有 LLM 调用和 worker 边界证据；
- CodexWorker 仍是 external builder boundary；
- Registry 没有变成 evaluator，仍以 verified hash/pass/provenance 为边界；
- 默认测试使用 fake/scripted client，不依赖真实 provider、网络或 live Codex。

验证命令：

```bash
.venv/bin/python -m pytest tests/test_frontdesk_schema.py tests/test_frontdesk_workspace.py tests/test_frontdesk_elicitor.py tests/test_frontdesk_auditor.py tests/test_frontdesk_freeze_gate.py -q
```

结果：

```text
74 passed
```

## 3. 高风险问题

### P0：WP15 不是端到端闭环完成

审核时 `RequirementsElicitor`、`SpecAuditor`、`FrontDeskFreezeGate` 都能独立工作，但还没有真正的 LangGraph 多轮状态机。也就是说：

```text
ask_user -> elicit -> audit -> freeze/human/reject
```

这条链路在审核时还没有作为可执行产品闭环完成。后续实现已补 `FrontDeskLoop` 和 `tests/test_frontdesk_loop.py`；当前 v2 状态以 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 与 `HANDOFF.md` 为准，`docs/DEVELOPMENT_ROADMAP.md` 只作为历史基线。

### P0：FreezeGate 风险、隐私、预算策略还不够硬

审核时 FreezeGate 已经是 deterministic gate，但风险、隐私和预算策略还不完整。特别是：

- high-risk / privacy / unsafe data access 不能只依赖 Auditor 自觉标记；
- `redaction_status`、`risk_policy_ref`、`data_sensitivity` 等字段需要进入确定性 gate；
- provider call 数量和成本预算需要进入可审计的 fail-closed 逻辑。

### P1：`planned` coverage 不能被误当成验收事实

WP16 前允许 freeze/build 前存在 `planned` coverage，但 Registry approved 前必须转换成真实结果：

```text
covered/pass
covered/fail
manual_only
uncovered
```

must criteria 不能停留在 `planned` 后进入 approved registry。

### P1：Elicitor draft artifact 当时还没有自动物化

`RequirementsElicitor` 当时会写 `elicitation_report_001.json`，但 draft spec 和 draft acceptance criteria 的 artifact 物化仍主要靠测试手工准备。后续 Front Desk loop 中需要补齐：

- `frontdesk/draft_skill_spec.yaml`
- `frontdesk/acceptance_criteria.yaml`
- 对应 manifest/hash/provenance

### P1：长对话治理仍是缺口

当前没有把长文本塞进 LangGraph state，这是正确的。但 Elicitor/Auditor prompt 仍可能读取完整 `conversation.jsonl`。后续必须补：

- conversation summary；
- redaction；
- retention；
- token/cost budget；
- 长对话截断或摘要注入策略。

## 4. WP16 建议

WP16 的核心不是“报告里显示 coverage”，而是建立确定性 coverage contract。

必须实现：

- `AcceptanceCriteriaPlanner`；
- `acceptance_coverage_plan.json`；
- `acceptance_coverage_result.json`；
- `VerificationSpec` 生成增强；
- QA Lab coverage report；
- final report coverage section；
- Registry provenance gate 只消费 result hash/pass/provenance，不计算 coverage。

必须测试：

- bad skill 按 acceptance criteria fail；
- good skill 按 acceptance criteria pass；
- uncovered must criteria fail；
- manual-only must criteria 进入 human gate；
- LLM-only must criteria 不可注册；
- QA coverage hash 缺失时 Registry 拒绝。

## 5. WP17 建议

WP17 不建议和 WP16 主线并行。进入真实 builder 前，应满足：

- Front Desk loop 可跑；
- 多轮澄清、round limit、human gate 可测；
- WP16 coverage result 可以阻止 registry；
- frozen input hash 和 artifact manifest 可以 preflight；
- builder 不读 raw conversation；
- builder 不修改 locked inputs；
- Verifier + QA coverage + Registry gate 全部通过。

Builder 类型应明确区分：

- `LLMSkillBuilderWorker`：SkillFoundry-owned LLM，可通过 ContextForge 记录和 replay 自有调用；
- `CodexAgentThreadWorker`：external boundary，只记录 transcript、diff、hash、duration、usage unavailable reason，不声称 replay Codex 内部。

## 6. 审核后的执行顺序

```text
1. WP15B Front Desk LangGraph Loop
2. WP16 Acceptance Criteria to QA/Verifier
3. WP17 Real Builder Integration
```

工程判断：

```text
先把需求澄清闭环和验收覆盖做硬，再让真实 builder 进入主线。
```
