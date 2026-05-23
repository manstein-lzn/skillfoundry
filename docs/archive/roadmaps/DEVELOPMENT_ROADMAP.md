# SkillFoundry 科学开发 Roadmap

> v2 权威声明：本文是 v0 / WP0-WP17 能力基线和产品经验记录，不再是当前 v2 技术执行源。当前 SkillFoundry x ContextForge Goal Harness 重构以 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 为 canonical 蓝图，以 `HANDOFF.md` 记录当前接手状态，以 `docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md` 保留原始重构计划和历史执行证据。本文中“当前执行只看本文”或“ContextForge 主要管自有 LLM 调用”的旧表述，只适用于 v0 历史语境。

版本：v1.1
日期：2026-05-17
适用范围：基于 LangGraph + ContextForge 的 Codex Skill 工厂 MVP，以及后续通用大模型需求交付平台

审核状态：已由独立 `gpt-5.5 xhigh` agent 审核，结论为 `approve_with_changes`。本版本已经吸收审核中的 P0/P1 修改：旧路线图状态降级、风险/隐私/预算硬门、Acceptance Coverage 前置门、人工验收 artifact、产品化 Front Desk 边界和 Pre-Production Release Gate。

## 1. 一句话结论

SkillFoundry 的正确路线不是先做一个“万能 Agent”，而是先把一个高价值闭环做硬：

```text
模糊业务需求
  -> 双 Agent 需求澄清
  -> 确定性规格冻结
  -> 受控 Builder 构建 Codex Skill
  -> QA / Verifier / Acceptance Coverage 独立验收
  -> Registry 注册分发
  -> 使用反馈进入下一轮版本治理
```

当前仓库已经具备 WP0-WP17 的工程基线：workspace、schema、refs-only LangGraph、ContextForge 自有 LLM 调用边界、Front Desk 双 Agent 组件、FreezeGate、Acceptance Coverage、LLM Builder pilot、Verifier、QA Lab、Registry 等核心模块已经存在并有离线测试。

但这还不是“可对外生产”的平台。下一阶段重点是把这些模块组合成真实可用的产品路径：接入真实 LLM provider、提供需求澄清交互入口、建立任务队列和运行观测、跑内部真实样例，并用数据决定是否进入更大规模自动化。

## 2. 产品目标

第一阶段产品目标是 **Codex Skill 工厂**：

> 将业务方的自然语言需求，转化为结构化规格、可测试 Skill 包、验收报告和可复用能力资产。

长期目标是 **通用大模型需求交付平台**：

> 用 LangGraph 组织流程，用 ContextForge 管理自有 LLM 上下文和证据账本，用文件即上下文 workspace 控制长任务状态，用独立验收和 Registry 把模型输出转化为可复用资产。

## 3. 核心架构判断

本项目采用三层责任分离：

```text
控制面：LangGraph
  管流程、状态、路由、重试、人工门、resume。

上下文面：ContextForge
  管 SkillFoundry 自有 LLM 调用的 PromptView、上下文注入、调用记录、replay 证据。

执行面：WorkerAdapter / Builder
  管外部或自有 builder 的输入输出边界，生成 package，但不能自证通过。
```

关键边界：

- Front Desk 是平台大脑，不交给 Codex Agent Thread 黑盒接管。
- Requirements Elicitor 负责主动澄清需求。
- Spec Auditor 负责独立审查需求是否清楚、可行、可测试。
- FrontDeskFreezeGate 是非 LLM 决策门，负责最终冻结或拒绝进入构建。
- Builder 只负责生成候选 Skill，不负责批准 Skill。
- Verifier、QA Lab、Acceptance Coverage、Registry 是质量和资产边界。
- ContextForge 控制 SkillFoundry 自有 LLM 调用，不控制 Codex Worker 内部 prompt、tool loop、context compaction、cache 或成本。

## 4. 当前基线

截至 2026-05-17，仓库已经完成的能力可以按工作包理解：

```text
+-------+------------------------------------+------------------------------+----------------+
| WP    | 名称                               | 核心产物                     | 状态           |
+-------+------------------------------------+------------------------------+----------------+
| WP0   | Design Baseline                    | 白皮书、架构边界、验收原则   | done           |
| WP1   | Workspace + Schema                 | 文件即上下文、hash、manifest | done           |
| WP2   | LangGraph Skeleton                 | refs-only workflow            | done           |
| WP3   | WorkerAdapter + FakeWorker         | builder 边界协议             | done           |
| WP4   | Independent Verifier               | 独立验证门                   | done           |
| WP5   | ContextForge Integration           | 自有 LLM 上下文/证据边界     | done           |
| WP6   | Local Registry MVP                 | verified asset store          | done           |
| WP7   | Offline E2E MVP                    | 离线 build/verify/register    | done           |
| WP8   | CodexWorker Pilot                  | Codex 黑盒 worker 边界试点   | done           |
| WP9   | Minimal API/UI                     | 内部 API 和 HTML 入口         | done           |
| WP10  | QA Lab Expansion                   | 质量报告层                   | done           |
| WP11  | Feedback + Versioning              | 反馈、版本、隔离、回滚       | done           |
| WP12  | Production Hardening Baseline      | ops、安全清单、健康检查      | done           |
| WP13  | Front Desk Schema + Workspace      | 需求澄清 schema/workspace     | done           |
| WP14  | Requirements Elicitor              | 主动澄清 Agent               | done           |
| WP15  | Spec Auditor + FreezeGate          | 审核 Agent + 确定性冻结门    | done           |
| WP15B | Front Desk Loop                    | 多轮澄清/审核/冻结路由       | done           |
| WP16  | Acceptance Coverage Bridge         | 验收标准到 QA/Registry 桥     | done           |
| WP17  | Owned LLM Builder Pilot            | 自有 LLM builder 试点         | done           |
+-------+------------------------------------+------------------------------+----------------+
```

当前基线的含义：

- 默认测试路径仍然是 deterministic/offline，不依赖真实 provider、网络或 live Codex。
- 真实 LLM builder 是 pilot，不等于生产级 builder 集群。
- Front Desk 具备可测试的同步 `FrontDeskLoop` / orchestration component、persistent job conversation、API/UI 入口、核心需求摘要、方案审查门和批准后冻结链路；它仍不是生产级多租户入口或 main graph checkpoint。
- Registry 已经具备本地资产边界，但还不是多租户企业资产平台。
- 历史路线图中的 WP15B/WP16/WP17 “next / blocking / blocked” 状态已经过期；v0 能力基线可看本文，v2 当前执行以 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 和 `HANDOFF.md` 为准。

## 5. 上线判定标准

SkillFoundry 不能用“模型能生成文件”作为上线标准。MVP 可用必须同时满足：

```text
+------+----------------------+----------------------------------------------+
| 编号 | 维度                 | 必须达到                                     |
+------+----------------------+----------------------------------------------+
| G1   | 需求澄清             | 能主动追问并冻结结构化 SkillSpec             |
| G2   | 可行性               | Auditor 和 FreezeGate 能阻止不清楚需求       |
| G3   | 构建                 | Builder 只能读取 frozen inputs 并写 package  |
| G4   | 验收                 | must acceptance criteria 未覆盖时不能注册    |
| G5   | 证据                 | 每次 LLM/worker/verify/register 有 artifact  |
| G6   | 失败闭环             | 失败能分类、repair、human review 或 reject   |
| G7   | 成本                 | 每个 job 有 provider 调用和 token/cost 预算  |
| G8   | 安全                 | 路径、敏感信息、外部权限和脚本执行有硬边界   |
| G9   | 复现                 | 离线测试稳定，真实 provider smoke opt-in     |
| G10  | 使用                 | 内部用户能通过 UI/API 完成至少 3 类真实需求  |
+------+----------------------+----------------------------------------------+
```

## 6. 分阶段路线

### Phase A：真实 Front Desk 产品入口

目标：

- 让用户可以真实提交模糊需求；
- Requirements Elicitor 主动追问；
- Spec Auditor 独立审查；
- FreezeGate 决定是否冻结、继续追问、人工审核或拒绝。

执行细节以 [FRONT_DESK_CORE_NEED_REFACTOR.md](FRONT_DESK_CORE_NEED_REFACTOR.md) 为准。Phase A 的核心产品机制调整为：

```text
Core Need Discovery
  -> Solution Planning
  -> User Review Gate
  -> Deterministic Freeze
```

这意味着需求澄清层优先理解用户痛点、使用场景、期望结果和成功信号；技术路线由 SkillFoundry 方案规划 Agent 自主设计，并通过用户审查后的规划文档进入冻结，而不是让普通澄清对话无限补字段。

主要任务：

- 增强现有 API/UI，支持多轮 conversation，而不是一次性离线 job；`POST /frontdesk/jobs/<id>/plan-review` 已落地为用户方案审查门；
- 接入真实 OpenAI API provider client，保持 fake client 为默认测试路径；
- 给每个 Front Desk job 增加 budget、timeout、model-call limit；budget/risk evidence 已进入 FreezeGate，真实 provider usage 聚合仍需继续产品化；
- 实现 conversation summary、敏感信息标记、长对话摘要策略；
- 将 `risk_report_ref`、`redaction_status`、`risk_policy_ref`、`data_sensitivity`、权限声明和 provider usage/cost 纳入 FreezeGate 输入；当前确定性 gate 已覆盖这些字段；
- 输出用户可读的 `solution_plan.md`、`clarification_summary.md` 和机器可读的 frozen artifacts；
- 增加 opt-in live smoke 测试，不进入默认测试集。

交付物：

- `POST /frontdesk/jobs`
- `POST /frontdesk/jobs/<id>/messages`
- `POST /frontdesk/jobs/<id>/plan-review`
- `GET /frontdesk/jobs/<id>`
- `GET /frontdesk/jobs/<id>/core-need`
- `GET /frontdesk/jobs/<id>/solution-plan`
- UI：对话区、待回答问题、方案审查、当前规格预览、审核结果、冻结状态。

退出门：

- 至少 5 个模拟真实需求能完成澄清或明确进入 human/reject；
- 不清楚需求不会启动 builder；
- raw conversation 不进入 builder prompt；
- 所有真实 provider 调用有 ContextForge 记录、usage 或 usage-unavailable reason；
- `redaction_status != complete` 时必须 fail closed 或进入 human gate；
- `restricted` / `confidential` 数据默认进入 human gate，除非 risk policy 显式允许；
- 外部 API、文件读取、联网、凭据、脚本执行权限未在 frozen spec 中显式声明时不得 freeze；
- provider 调用次数、token、成本或 timeout 超预算时不得继续；
- usage 缺失且没有 `usage-unavailable reason` 时不得继续；
- 当前 WP9 one-shot offline API 不能被误认为 Phase A 完成，Phase A 必须交付真正的 `/frontdesk/jobs` 多轮 conversation API/UI 和 job state。

### Phase B：Factory Floor Builder 主线

目标：

- 从 frozen spec 启动受控 builder；
- 优先打磨 `LLMSkillBuilderWorker`；
- `CodexWorker` 继续作为黑盒高能力 builder 试点，而不是平台大脑。

主要任务：

- 将 `LLMSkillBuilderWorker` 接入正式 build route；
- 增加 builder selector：fake / owned_llm / codex_external；
- 对 builder 输出做 package path confinement、diff、hash、execution report；
- 增加 attempt-level retry 和 repair plan；
- 明确 builder 不可读取 Front Desk raw conversation；
- 为 Codex external worker 记录 transcript、duration、diff、usage unavailable reason。

退出门：

- frozen spec -> builder -> verifier -> QA -> acceptance_coverage_result -> registry 的路径稳定；
- builder 自报成功不能绕过 Verifier/QA/Registry；
- AcceptanceCoverageEvaluator 是 Registry 前置硬门，缺失、失败、未覆盖或被篡改的 coverage result 都不得注册；
- 恶意路径、重复路径、空文件、schema mismatch 全部 fail closed；
- builder 失败能产生可执行 repair task 或 human review。

### Phase C：QA Lab 和 Acceptance Coverage 强化

目标：

- 让验收标准真正支配质量门；
- 避免“文档写得好看但不可验证”的 Skill 注册。

主要任务：

- 从 `acceptance_criteria.yaml` 生成 coverage plan；
- 将 fixture、静态检查、脚本检查、LLM judge、manual authority 明确区分；
- 将 manual authority 从字符串元数据升级为独立人工验收 artifact，例如 `manual_acceptance_record.json`；
- QA report 增加 coverage summary；
- Registry 只消费 coverage result 的 pass/hash/provenance，不自己计算语义；
- 增加 bad skill / good skill 对照样例库；
- 建立最小 benchmark：澄清质量、构建成功率、验收通过率、repair 成功率。

退出门：

- uncovered must criteria 不能注册；
- covered/fail must criteria 不能注册；
- manual-only must criteria 必须有 `manual_acceptance_record.json` 或等价 artifact；
- 人工验收 artifact 必须包含 reviewer id/role、decision、timestamp、reason、covered criterion ids、source hash，并被 coverage result 引用 hash；
- Registry 仍不计算人工验收语义，但必须校验 artifact 存在、hash 匹配、decision 为 approved；
- LLM-only must criteria 默认不能当作确定性通过证据；
- tampered coverage result 被 Registry 拒绝。

### Phase D：Registry、分发和反馈闭环

目标：

- 把通过验收的 Skill 变成可复用资产；
- 支持版本、隔离、回滚、反馈触发新一轮构建。

主要任务：

- Registry 从本地 JSON 逐步迁移到 SQLite/Postgres；
- 增加 skill metadata、owner、version、status、provenance、risk tags；
- 生成可安装 Skill 包；
- 记录用户反馈、失败样例、prompt 修改和使用场景；
- feedback -> repair job -> new version -> re-verify -> promote；
- 增加 quarantine、rollback、deprecate 流程。

退出门：

- 一个 Skill 可以从 v1 反馈修复到 v2；
- v2 注册不破坏 v1 provenance；
- quarantine 后无法下载或分发；
- rollback 有明确记录和可审计原因。

### Phase E：内部 Beta 平台化

目标：

- 让小团队可以真实使用；
- 系统能承受长任务、失败恢复和多人协作。

主要任务：

- 增加任务队列和异步 worker；
- 增加 auth、operator role、manual review role；
- 增加 run dashboard：job 状态、artifact、成本、失败分类、registry 状态；
- 增加 structured logs、metrics、trace id；
- 增加 secrets 管理和 provider key 配置；
- 增加 retention/cleanup policy；
- 增加批量运行和回归集。

退出门：

- 10-20 个内部真实需求可以完整跑完或明确失败；
- 失败都有分类：需求不清、不可行、builder 失败、verifier 失败、coverage 失败、人工门；
- 操作员可以恢复 job、查看证据、重新触发 repair；
- 默认路径不会意外调用 live provider 或 Codex。

### Phase E2：Pre-Production Release Gate

目标：

- 防止内部 beta 被误升级成真实生产上线；
- 在对外或跨团队生产使用前补齐平台级基础设施。

必须完成：

- authn/authz；
- tenant isolation；
- rate limit 和 CSRF 防护；
- queue、backpressure、distributed locks；
- durable DB、migration、backup、restore；
- deployment manifests；
- secrets management；
- monitoring、alerting、trace、audit log retention；
- incident response runbook；
- package signing 和 provenance verification；
- SLA、rollback runbook、data retention policy。

退出门：

- 生产发布 checklist 全部通过；
- staging 环境完成回归和故障演练；
- 安全、运维、人工审核职责明确；
- 未完成本 gate 前不得对外宣称 production-ready。

### Phase F：性能和高可靠内核

目标：

- 在真实长任务压力下识别 Python 的性能瓶颈；
- 决定是否引入 Rust 内核。

判断原则：

- LangGraph 编排、产品 API、策略逻辑继续用 Python 最快；
- 高风险、高频、确定性、可封装模块优先考虑 Rust；
- 不为了“看起来高性能”提前重写系统。

Rust 候选模块：

- path confinement；
- artifact hashing；
- manifest verification；
- diff/package validation；
- policy evaluation；
- log/event compaction；
- sandbox preflight。

退出门：

- 有真实 profiling 数据证明瓶颈；
- Rust 模块接口稳定；
- Python 调用 Rust 后测试覆盖不下降；
- 性能收益能被量化，例如 manifest 校验、package 扫描、批量 hash 明显改善。

### Phase G：通用大模型需求交付平台

目标：

- 从 Codex Skill 工厂扩展到多类需求交付；
- SkillFoundry 成为“生产 Agent 的 Agent 工厂”。

主要任务：

- 支持多 Skill 组合；
- 支持 RAG、脚本、API connector、MCP tool 的能力目录；
- 增加需求路由：复用现有 Skill、微调、重新构建、人工转交；
- 建立组织级知识库和能力图谱；
- 增加跨部门审批、合规、审计和权限。

退出门：

- 不同类型需求能走不同 build route；
- 平台能解释为什么复用、重建或拒绝；
- 使用反馈能影响下一次路由和构建；
- 不牺牲 Front Desk、Verifier、Registry 的质量边界。

## 7. 推荐近期执行顺序

```text
+------+------------------------------------+--------------------------+------------------------------+
| 顺序 | 任务                               | 目标                     | 验收证据                     |
+------+------------------------------------+--------------------------+------------------------------+
| 1    | 修正文档状态                       | 消除旧 roadmap 冲突      | README 指向当前路线图        |
| 2    | Front Desk API/UI 多轮入口         | 真实需求澄清可用         | 手工和测试样例均可跑通       |
| 3    | OpenAI provider opt-in smoke       | 真实 LLM 可控接入        | 非默认 live smoke 通过       |
| 4    | Acceptance 样例库和 coverage 硬门  | 质量门可量化             | good/bad skill 对照测试      |
| 5    | Builder 主线选择器                 | fake/owned_llm/codex 分流| 完整验收链路稳定             |
| 6    | 内部 Beta dashboard                | 可观察、可恢复           | job/artifact/cost 状态可见   |
| 7    | 真实需求试运行                     | 评估产品可用性           | 至少 10 个需求的运行报告     |
+------+------------------------------------+--------------------------+------------------------------+
```

## 8. 指标体系

研发阶段必须开始量化，否则无法判断“上下文管理是否真的有效”。

核心指标：

- `clarification_rounds_avg`：平均澄清轮数；
- `freeze_rate`：进入规格冻结的比例；
- `human_review_rate`：进入人工审核比例；
- `builder_success_rate`：builder 产生候选 package 的比例；
- `verifier_pass_rate`：Verifier 通过比例；
- `acceptance_must_coverage_rate`：must criteria 覆盖率；
- `repair_success_rate`：失败后修复成功比例；
- `registry_approval_rate`：最终注册比例；
- `cost_per_registered_skill`：每个注册 Skill 的平均成本；
- `time_to_registered_skill`：从需求提交到注册的耗时；
- `rework_rate`：用户反馈导致重做的比例。

最低可接受 MVP 指标建议：

```text
真实内部样例数 >= 10
must criteria coverage = 100% or manual authority
manual-only must criteria have hashed manual acceptance artifact = 100%
builder self-approved registry entries = 0
untraceable provider calls = 0
untraceable registry approvals = 0
path escape incidents = 0
```

## 9. 主要风险和处理

```text
+------+--------------------------------+----------------------------------------------+
| 风险 | 描述                           | 处理                                         |
+------+--------------------------------+----------------------------------------------+
| R1   | 需求澄清流于形式               | 双 Agent + FreezeGate + human gate           |
| R2   | Builder 输出看似成功但不可用    | Verifier/QA/Coverage/Registry 独立验收       |
| R3   | 上下文过大导致成本失控          | refs-only state + summary + budget + timeout |
| R4   | Codex Worker 黑盒不可控          | 只作为 external builder，记录边界证据        |
| R5   | LLM judge 被误当确定性证据       | LLM-only must criteria 不默认通过            |
| R6   | Python 长任务性能不足            | 先 profiling，后 Rust 化确定性热点           |
| R7   | 文档与实现状态漂移               | 每阶段结束更新当前状态和验收证据             |
| R8   | 过早生产化                       | 未完成 Pre-Production Gate 前只内部试用      |
+------+--------------------------------+----------------------------------------------+
```

## 10. 不做什么

近期明确不做：

- 不复制 Codex 或 OpenHuman 源码；
- 不承诺控制 Codex Agent Thread 内部上下文；
- 不把 LangGraph state 当大记忆库；
- 不让 Builder 绕过 Verifier 和 Registry；
- 不把 LLM 自评当作上线验收；
- 不先重写成 Rust；
- 不对外宣称生产级多租户平台；
- 不做无边界的通用 Agent OS。

## 11. 给第三方 Agent 的执行原则

后续交给第三方 Agent 实现时，必须按以下规则工作：

- 每个阶段先写 `AGENT_BRIEF_WP*.md`，明确目标、非目标、owned files、验收门；
- 默认测试必须 deterministic/offline；
- live provider、Codex、网络、外部命令能力必须 opt-in；
- 不能删除安全检查来让测试通过；
- 不能让 Registry 变成 evaluator；
- 不能让 Front Desk raw conversation 进入 builder prompt；
- 不能用 worker 自报成功替代独立验收；
- 不能把旧 roadmap 中过期的 “next / blocked” 状态当作当前待办；
- 不能把 manual authority 字符串当作人工验收证据，必须使用带 hash 的人工验收 artifact；
- 每个阶段结束必须给出：改了什么、证据在哪里、怎么复现、还不能做什么。

## 12. 历史最小下一步

以下是本文作为 v0/WP0-WP17 roadmap 时的历史下一步，已经被当前 v2 Goal Harness 蓝图 supersede。当前下一步以 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 和 `HANDOFF.md` 为准。

```text
1. 以本文件作为当时的权威 roadmap。
2. 用第三方 gpt-5.5 xhigh agent 审核本 roadmap。
3. 根据审核意见修正文档。
4. 启动 Phase A：Front Desk 多轮 API/UI + OpenAI provider opt-in smoke。
5. 用 3-5 个真实 Codex Skill 需求跑内部试验。
```

这条路线能保持两个目标同时成立：

- 短期能真实试用 Codex Skill 工厂；
- 长期不会破坏 ContextForge、LangGraph、文件即上下文和独立验收这些核心架构资产。
