# Development Roadmap Independent Audit

日期：2026-05-17
审核方：独立 `gpt-5.5 xhigh` agent
审核对象：`docs/DEVELOPMENT_ROADMAP.md`、README、历史 roadmap、Front Desk roadmap/audit、LLM Builder pilot、核心 src/tests

## 1. 结论

审核结论：`approve_with_changes`。

路线方向科学，可以作为 SkillFoundry 后续开发主线：

- 先做 Front Desk 需求澄清和确定性冻结；
- 再接入受控 builder；
- 再由 Verifier、QA、Acceptance Coverage、Registry 独立验收；
- ContextForge 与 CodexWorker 的边界基本准确；
- 默认测试仍保持 deterministic/offline。

但初版不能原样交给第三方 agent 盲执行。主要问题是旧 roadmap 状态冲突、风险/隐私/预算硬门不够硬、Acceptance Coverage 没有在 Builder 主线中写成 Registry 前置硬门、manual authority 语义偏弱、生产上线前缺少明确 release gate。

## 2. 审核证据

审核 agent 只读检查了：

- `README.md`
- `docs/DEVELOPMENT_ROADMAP.md`
- `docs/ROADMAP_EXECUTION_PLAN.md`
- `docs/FRONT_DESK_AGENT_ROADMAP.md`
- `docs/FRONT_DESK_ROADMAP_AUDIT.md`
- `docs/LLM_BUILDER_PILOT.md`
- `src/skillfoundry/frontdesk_loop.py`
- `src/skillfoundry/frontdesk.py`
- `src/skillfoundry/frontdesk_schema.py`
- `src/skillfoundry/frontdesk_workspace.py`
- `src/skillfoundry/acceptance.py`
- `src/skillfoundry/llm_builder.py`
- `src/skillfoundry/registry.py`
- `src/skillfoundry/worker.py`
- `src/skillfoundry/api.py`

审核 agent 运行默认测试：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

结果：

```text
259 passed in 18.46s
```

## 3. P0 问题和修正

### P0-1：旧 roadmap 状态冲突

问题：

- 新 roadmap 声明 WP15B、WP16、WP17 已完成；
- 旧 `ROADMAP_EXECUTION_PLAN.md` 和 `FRONT_DESK_AGENT_ROADMAP.md` 仍保留 “next / blocking / blocked” 状态；
- README 初版仍让第三方 agent 同时阅读旧执行路线，容易误导后续执行。

修正：

- README 明确 `docs/DEVELOPMENT_ROADMAP.md` 是当前唯一执行源；
- `docs/ROADMAP_EXECUTION_PLAN.md` 增加历史状态说明；
- `docs/FRONT_DESK_AGENT_ROADMAP.md` 增加历史状态说明；
- `docs/DEVELOPMENT_ROADMAP.md` 明确历史路线图中的 WP15B/WP16/WP17 状态已经过期。

### P0-2：风险、隐私、预算硬门不足

问题：

- 当前 FreezeGate 已经是 deterministic gate，但风险、隐私、预算策略还没有在 roadmap 中写成足够硬的 Phase A 出口；
- `risk_report_ref`、`redaction_status`、`risk_policy_ref`、`data_sensitivity`、权限声明、provider usage/cost 必须成为真实 provider 入口前的硬约束。

修正：

- Phase A 主要任务加入 risk/redaction/policy/data_sensitivity/permission/cost 输入；
- Phase A 退出门加入：
  - `redaction_status != complete` 必须 fail closed 或 human gate；
  - restricted/confidential 数据默认 human gate；
  - 外部 API、文件读取、联网、凭据、脚本执行权限未显式声明不得 freeze；
  - provider 调用次数、token、成本或 timeout 超预算不得继续；
  - usage 缺失且无 reason 不得继续。

## 4. P1 问题和修正

### P1-1：Builder 主线没有把 Acceptance Coverage 写成前置硬门

修正：

- Phase B 退出门改为 `frozen spec -> builder -> verifier -> QA -> acceptance_coverage_result -> registry` 全链路稳定；
- 明确 AcceptanceCoverageEvaluator 是 Registry 前置硬门；
- 缺失、失败、未覆盖或被篡改的 coverage result 都不得注册。

### P1-2：manual authority 只是字符串元数据

修正：

- Phase C 要求将 manual authority 升级为独立人工验收 artifact；
- 建议 artifact 名称为 `manual_acceptance_record.json`；
- artifact 必须包含 reviewer id/role、decision、timestamp、reason、covered criterion ids、source hash；
- coverage result 必须引用 artifact hash；
- Registry 不计算人工验收语义，但必须校验 artifact 存在、hash 匹配、decision 为 approved。

### P1-3：当前 Front Desk Loop 不是产品入口

修正：

- 当前基线明确：WP15B 是可测试的同步 `FrontDeskLoop` / orchestration component，不是产品化多轮 API/UI、persistent job conversation 和 main graph checkpoint；
- Phase A 退出门明确必须交付 `/frontdesk/jobs` 多轮 conversation API/UI 和 job state。

### P1-4：缺少生产发布门

修正：

- 新增 `Phase E2：Pre-Production Release Gate`；
- 明确 authn/authz、tenant isolation、rate limit/CSRF、queue/backpressure、distributed locks、durable DB、deployment manifests、secrets、monitoring/alerting、audit retention、incident response、package signing、SLA/rollback runbook 等必须完成；
- 未完成该 gate 前不得对外宣称 production-ready。

## 5. 专项判断

Front Desk 双 Agent + deterministic FreezeGate：

- 设计合理；
- 已有实现和测试支撑；
- 风险、隐私、预算策略必须继续从文档约束推进到 FreezeGate 硬门实现。

ContextForge 与 CodexWorker 边界：

- 描述准确；
- ContextForge 控制 SkillFoundry 自有 LLM 调用；
- CodexWorker 只作为 external builder boundary，不声称 replay 或控制 Codex 内部 prompt、tool loop、context compaction、cache 或 cost。

默认测试：

- 当前保持良好；
- 默认全量测试通过；
- live provider、live Codex、网络路径必须继续 opt-in。

Phase A-G 顺序：

- 总体科学；
- Acceptance 样例库和 coverage hard gate 应前置到 Builder 主线选择器之前，或与 Phase B 形成联动硬门；
- Rust 只应在 profiling 后引入；
- Phase G 不应早于 Pre-Production Release Gate。

## 6. 最终处理

审核意见已经吸收到：

- `README.md`
- `docs/DEVELOPMENT_ROADMAP.md`
- `docs/ROADMAP_EXECUTION_PLAN.md`
- `docs/FRONT_DESK_AGENT_ROADMAP.md`

后续第三方 agent 执行时，只应以 `docs/DEVELOPMENT_ROADMAP.md` 作为当前路线图，以本文件作为独立审核记录。
