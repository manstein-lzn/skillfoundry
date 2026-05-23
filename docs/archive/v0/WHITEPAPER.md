# SkillFoundry 白皮书 v0.2

## 摘要

SkillFoundry，中文名“技能铸造厂”，是一套面向大模型需求交付的工程化平台。它的第一个产品形态是 **Codex Skill 工厂**：把业务方的自然语言需求，转化为结构化规格、可测试 Skill 包、独立验收报告和可注册复用的能力资产。

v0.2 的核心路线是：

```text
LangGraph 编排
+ 文件即上下文 workspace 协议
+ Codex Worker 黑盒高能力构建
+ 独立 Verifier 主质量门
+ Registry approved asset store
+ ContextForge 作为自有 LLM 调用运行时与任务级证据账本
```

这是一条 **conditional-go** 路线：可以作为 MVP 继续推进，但必须先落实 workspace confinement、WorkerAdapter 边界、Verifier 和 Registry gate。真实 Codex Worker 集成不能早于这些基础能力。

SkillFoundry 第一阶段不是自建完整 ActionRuntime，也不假装能控制 Codex Worker 的内部提示词、工具循环、上下文压缩、缓存或成本。它采用的是 **外部 worker 监督型工厂**：

```text
少管黑盒过程，严管输入边界、产物证据和输出验收。
```

## 1. 产品愿景

大模型的单点能力已经足够强，真正阻碍它进入稳定生产的是工程化交付体系。

企业用户需要的不是一次回答，而是一个能持续交付、验收、修复、注册和复用能力资产的平台。SkillFoundry 要解决的问题是：

- 需求能否被主动澄清并结构化；
- 交付物能否被测试和审计；
- 失败后能否形成可执行 repair task；
- 通过验收的能力能否注册、复用和迭代；
- 成本、证据、版本和质量能否被追踪。

SkillFoundry 的第一个 MVP 聚焦一个足够具体的切口：

> 用户提出一个业务需求，系统生成一个经过独立 Verifier 验收并写入 Registry 的 Codex Skill。

## 2. 项目命名

项目英文名：**SkillFoundry**

中文名：**技能铸造厂**

命名含义：

- `Skill`：最终交付物不是一次性回答，而是可复用能力资产。
- `Foundry`：强调工业化生产、质量控制、版本沉淀和持续改进。
- 与 `ContextForge` 呼应：ContextForge 是上下文运行时与证据账本，SkillFoundry 是需求交付和资产生产平台。

## 3. 产品定义

SkillFoundry 接收自然语言需求，输出经过验证的自动化能力资产。第一阶段的能力资产定义为 Codex Skill：

```text
业务需求
  -> SkillSpec
  -> BuildContract
  -> Skill package
  -> VerificationResult
  -> approved RegistryEntry
```

平台维护完整生命周期：

1. 需求澄清；
2. 需求结构化；
3. 可行性和安全评估；
4. 复用、修改、构建或拒绝路由；
5. Skill 构建；
6. 独立验证；
7. 失败修复；
8. 人类审查或自动批准；
9. Registry 注册；
10. 使用反馈回流。

## 4. 核心架构关系

### 4.1 LangGraph：流程和状态编排

LangGraph 负责流程状态，而不是大文本存储或 worker 内部控制。

它回答：

- 当前 job 处于哪个阶段；
- 下一个节点是什么；
- 失败后 repair、reject、human review 还是 register；
- attempt 计数和失败分类如何维护；
- 哪些轻量引用需要 checkpoint 和 resume。

LangGraph state 只保存轻量数据：

```text
job_id
stage
status
attempt_count
route
refs
hashes
next_action
```

它不保存完整 worker transcript、raw logs、完整 Skill package、replay bundle 或长上下文正文。

### 4.2 Workspace：文件即上下文协议

Workspace 是 SkillFoundry 和外部 worker 之间的主要契约。

每个 build job 有独立目录，关键输入在构建前锁定，输出写入受限目录，所有关键 artifact 有 hash：

```text
runs/<job_id>/
  build_contract.yaml
  skill_spec.yaml
  verification_spec.yaml
  worker_input.md
  attempts/
    001/
      input_manifest.json
      execution_report.json
      output_diff.patch
      worker_transcript.log
  package/
    SKILL.md
    references/
    scripts/
    tests/
  verifier/
    verification_result.json
    static_report.json
    sandbox.log
  artifact_manifest.json
  resume_brief.md
```

核心规则：

- `build_contract.yaml`、`skill_spec.yaml`、`verification_spec.yaml` 构建前锁定；
- worker 只允许写 `package/` 和当前 `attempts/<n>/`；
- registry 只能由平台写；
- 所有路径必须 resolve 后确认仍在 job workspace 内；
- 每次 attempt 必须有 execution report、diff 或等价输出摘要；
- 所有关键 artifact 必须可 hash、可引用、可审计。

### 4.3 Codex Worker：黑盒外部构建边界

Codex Worker 是封闭但高能力的外部 builder。它可以是真实 Codex CLI/SDK，也可以是兼容协议的其他 coding worker。

它负责：

- 读取 workspace 中的规格和约束；
- 生成或修复 `SKILL.md`、references、scripts、tests；
- 执行其内部需要的工程操作；
- 输出 execution report、diff、summary、transcript artifact。

SkillFoundry 不控制也不声称能重放以下内部过程：

- Codex Worker 内部提示词；
- worker tool loop；
- worker 上下文压缩和 compaction；
- worker prompt cache 或缓存命中；
- worker 内部成本结构和 token 细节；
- worker 对外部工具的内部调度策略。

SkillFoundry 控制的是外部边界：

- worker 输入文件；
- worker 可写目录；
- timeout 和 attempt limit；
- environment allowlist；
- transcript、diff、report、hash 等边界证据；
- Verifier 是否接受结果；
- Registry 是否允许注册。

Builder 的自报成功不是验收证据。只有独立 Verifier 产生的结果，外加必要的人工审查记录，才能推动 Registry approval。

### 4.4 ContextForge：自有调用运行时与边界证据账本

ContextForge 在 SkillFoundry 中承担两类职责，边界必须清晰。

第一类是 **SkillFoundry 自有 LLM 调用** 的上下文运行时。这些调用可以并且应该由 ContextForge 细粒度控制：

```text
ContextRequest
  -> PromptView
  -> ModelCallEnvelope
  -> ContextKernel.invoke_model()
  -> ModelCallRecord / UsageRecord / ReplayBundle
```

典型 owned LLM call 包括：

- 需求澄清；
- SkillSpec 生成；
- 路由判断；
- failure 分析；
- repair plan；
- 可选 LLM judge；
- report summary。

第二类是 **外部 worker 调用边界** 的证据记录。对 Codex Worker，ContextForge 记录：

- worker invocation；
- worker input manifest；
- workspace hash；
- execution report；
- output diff；
- transcript artifact；
- duration；
- verifier result；
- registry decision；
- usage 是否可得，以及不可得原因。

ContextForge 不负责也不声称提供：

- Codex Worker 内部 prompt 控制或 replay；
- Codex Worker 内部 tool loop 控制；
- sandbox、shell runtime 或 MCP runtime；
- workspace 权限系统；
- 任务队列；
- UI；
- marketplace；
- 真实 Codex 集成。

因此，白皮书中的“可 replay”只指 SkillFoundry 自有 LLM 调用和可重放的边界 artifact，不指 Codex Worker 内部过程的完整 replay。

### 4.5 Verifier：独立主质量门

Verifier 是 MVP 的主质量门，必须独立于 builder。

第一版 Verifier 至少覆盖：

- package 结构检查；
- `SKILL.md` required sections；
- trigger / non-trigger 场景检查；
- required inputs / expected outputs 覆盖检查；
- reference/scripts 路径安全；
- package path confinement；
- 禁止路径穿越；
- artifact hash 校验；
- verification report schema 校验；
- sandbox smoke；
- fixture case。

LLM judge 可以作为辅助判断，但不能是唯一验收门，也不能覆盖掉静态检查、路径检查、hash 检查和 fixture/sandbox 结果。

Verifier 的结果必须机器可读、可追踪、可被 Registry 使用。Builder self-report、聊天总结或“看起来成功”的文本都不是 acceptance evidence。

### 4.6 Registry：approved asset store

Registry 是通过验收的 Skill 资产库。它只接受 Verifier 通过并满足 gate 的 package。

RegistryEntry 至少包含：

```text
skill_id
version
package_path
package_hash
build_job_id
worker_invocation_id
verification_spec_hash
verification_result_hash
artifact_manifest_hash
verifier_version
approval_status
review_status
created_at
provenance
quarantine_status
```

Registry 的职责不是存一份文件列表，而是保存资产、版本、来源、验收证据和后续 quarantine/rollback 决策所需的追溯信息。

## 5. Conditional-Go 路线

v0.2 的判断是：SkillFoundry 可以继续采用外部 Codex Worker 作为高能力 builder，但必须满足条件后再接真实 worker。

### 5.1 可以推进的理由

- Codex Worker 的工程生成能力强，适合第一阶段 Skill 包构建；
- 文件即上下文协议能降低与黑盒 worker 的耦合；
- LangGraph 能承担流程、路由、checkpoint 和 repair loop；
- ContextForge 已适合作为 owned LLM call 的上下文运行时和证据账本；
- 独立 Verifier 和 Registry gate 可以把“模型生成”变成可验收交付。

### 5.2 必须先完成的前置条件

真实 Codex Worker 集成必须等待以下能力存在：

1. workspace confinement；
2. WorkerAdapter 协议；
3. worker timeout、attempt limit 和 env allowlist；
4. attempt 目录、transcript、diff、execution report；
5. 独立 Verifier；
6. Registry gate；
7. usage unavailable reason 和边界 evidence 记录；
8. fail-closed 错误处理。

缺少这些条件时，只能使用 FakeWorker 或离线 fixture，不应把真实 Codex Worker 纳入自动批准链路。

## 6. MVP 范围

第一阶段 MVP 只做 Codex Skill 工厂，不做泛化任务平台。

### 6.1 MVP 必须完成

MVP 必须支持以下闭环：

1. 输入一个自然语言 Skill 需求；
2. 需求澄清节点补齐目标、输入、输出、约束和验收标准；
3. 生成结构化 `SkillSpec`；
4. 路由节点判断复用、修改、构建或拒绝；
5. 准备独立 workspace 和锁定输入；
6. WorkerAdapter 调用 FakeWorker，后续再试点 Codex Worker；
7. Verifier 执行静态验证、路径验证、hash 验证、fixture/sandbox smoke；
8. 失败时生成 repair task；
9. 修复后重新验证；
10. 通过后写入本地 Skill Registry；
11. 输出 verification report 和 artifact manifest。

### 6.2 MVP 暂不做

MVP 不做以下内容：

- 多租户权限系统；
- 完整 Web UI；
- 企业级部署；
- 大规模任务队列；
- 复杂计费系统；
- 任意类型 Agent 自动生成；
- 真实组织知识图谱；
- 多语言 SDK；
- 完整 Skill marketplace；
- 自建完整 ActionRuntime；
- 控制或 replay Codex Worker 内部过程。

## 7. 工作流草案

第一版 LangGraph 主流程：

```text
intake
  -> clarify
  -> spec_generate
  -> route
  -> prepare_workspace
  -> build
  -> verify
  -> repair_or_register
  -> emit_report
```

关键分支：

```text
route.reject -> emit_rejection_report
route.reuse -> register_reuse_decision
verify.failed -> repair
repair.failed_too_many_times -> human_review
register.blocked -> quarantine_or_manual_review
```

自有 LLM 节点走 ContextForge；外部 worker 节点走 WorkerAdapter，并把输入输出边界写入 ContextForge evidence ledger。

## 8. 核心数据对象

### 8.1 SkillSpec

```text
skill_id
title
description
trigger_scenarios
non_trigger_scenarios
required_inputs
expected_outputs
constraints
acceptance_criteria
reference_materials
security_notes
```

### 8.2 BuildContract

```text
job_id
skill_spec_ref
verification_spec_ref
workspace_root
allowed_write_paths
blocked_paths
timeout_seconds
attempt_limit
required_artifacts
locked_input_hashes
```

### 8.3 WorkerInvocation

```text
invocation_id
job_id
worker_type
adapter_version
input_manifest_hash
workspace_hash_before
workspace_hash_after
started_at
finished_at
duration_ms
usage_available
usage_unavailable_reason
transcript_ref
execution_report_ref
diff_ref
exit_status
```

### 8.4 VerificationResult

```text
result_id
job_id
package_hash
verification_spec_hash
passed
checks
failures
evidence_refs
llm_judge_ref_optional
verifier_version
created_at
```

### 8.5 RegistryEntry

```text
skill_id
version
package_path
package_hash
build_job_id
worker_invocation_id
verification_result_hash
approval_status
review_status
quarantine_status
provenance
created_at
```

## 9. 成功标准

MVP 不是以“模型看起来能回答”为成功标准。

MVP 成功标准是：

1. 能从自然语言需求生成结构化 SkillSpec；
2. 能初始化受限 job workspace；
3. 能锁定 BuildContract 和 VerificationSpec；
4. 能通过 WorkerAdapter 构建或修复 Skill package；
5. 能检测一个故意失败的 Skill；
6. 能生成 repair task 并修复；
7. 能重新验证通过；
8. 能阻止 builder self-report 直接进入 Registry；
9. 能写入 approved RegistryEntry；
10. 能输出 verification report；
11. 能 replay SkillFoundry 自有 LLM 调用；
12. 能记录 Codex Worker 边界证据，但不夸大内部 replay；
13. 能证明 raw verifier logs 不直接污染 prompt；
14. 能证明 memory 是显式注入的。

## 10. 风险与边界

### 10.1 最大风险：把生成器误当工厂

如果没有独立 Verifier，SkillFoundry 会退化成一个会生成漂亮文件的聊天机器人。

应对：

- Verifier 是主质量门；
- builder self-report 不算验收证据；
- Registry 只接受 verifier-passed package；
- fail-closed 是默认行为。

### 10.2 第二风险：夸大 ContextForge 边界

ContextForge 能控制 SkillFoundry 自有 LLM 调用，但不能控制 Codex Worker 内部过程。

应对：

- 文档和代码都区分 owned LLM call 与 external worker invocation；
- replay coverage 只统计真实可 replay 对象；
- worker usage 不可得时记录 `usage_unavailable_reason`；
- 不宣称掌握黑盒 worker 内部 prompt、tool loop、cache 或 cost。

### 10.3 第三风险：workspace 越权和供应链污染

外部 worker 可能写错目录、引入不安全脚本或产出无法追溯的文件。

应对：

- 所有路径 resolve 后检查 confinement；
- worker 可写目录最小化；
- artifact hash 和 manifest 必填；
- verifier 执行路径、安全、脚本策略和 hash 检查；
- registry 支持 quarantine。

### 10.4 第四风险：过早平台化

一开始就做 UI、权限、多租户、队列，会拖慢核心验证。

应对：

- 先做离线 MVP；
- 先用 FakeWorker 验证协议和 gate；
- 通过 WP1-WP7 后再进入 CodexWorker pilot；
- API/UI 放到最小可用阶段。

## 11. 分阶段路线摘要

```text
WP0  docs v0.2
WP1  workspace + schema
WP2  LangGraph skeleton
WP3  WorkerAdapter
WP4  Verifier
WP5  ContextForge integration
WP6  Registry MVP
WP7  offline E2E MVP
WP8  CodexWorker pilot
WP9  minimal API/UI
WP10 feedback loop
```

阶段顺序必须保守。特别是 WP8 真实 Codex Worker 试点必须依赖 WP1-WP7 的 confinement、adapter、verifier、registry 和 E2E 证据。

## 12. 第一阶段结论

SkillFoundry v0.2 的结论是：

> 不做通用万能 Agent 平台，先做一个外部 worker 监督型 Codex Skill 工厂。

这条路线成立的前提不是“相信 builder”，而是建立工程化边界：

- LangGraph 管流程；
- Workspace 管输入输出协议；
- WorkerAdapter 管外部调用边界；
- ContextForge 管 owned LLM call 和证据账本；
- Verifier 管质量门；
- Registry 管 approved asset。

只有当这些边界同时存在时，Codex Skill 工厂才不是 prompt demo，而是可审计、可修复、可复用的能力生产系统。
