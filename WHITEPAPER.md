# SkillFoundry 白皮书

## 摘要

SkillFoundry 是一个基于 **LangGraph + ContextForge** 的大模型需求管理平台。它的第一个 MVP 是 **Codex Skill 工厂**。

这个项目的核心判断是：

> 大模型的单点能力已经足够强，真正阻碍它进入稳定生产的是工程化交付体系，而不是再写一个聊天机器人。

SkillFoundry 要解决的问题不是“让模型回答问题”，而是“让模型把业务需求持续、稳定、可验收地转化为可复用的自动化能力”。

第一阶段我们不做泛化大平台，只做一个足够锋利的切口：

> 用户提出一个业务需求，系统自动澄清、评估、构建、测试、修复并注册一个 Codex Skill。

这个 MVP 既是产品原型，也是底层能力验证场。它会验证 LangGraph 的流程编排能力、ContextForge 的上下文管理能力，以及 Codex 类 coding worker 在真实需求交付中的价值。

## 1. 项目命名

项目英文名：**SkillFoundry**

中文名：**技能铸造厂**

命名含义：

- `Skill`：最终交付物不是一次回答，而是可复用的能力资产。
- `Foundry`：强调工业化生产、质量控制、版本沉淀和持续改进。
- 与 `ContextForge` 呼应：ContextForge 是上下文内核，SkillFoundry 是能力生产平台。

## 2. 背景问题

今天很多大模型应用停留在“对话增强”阶段，但企业真正需要的是“需求交付”。

业务方不会关心 prompt 是否优雅，也不会关心 agent 架构是否复杂。他们只关心：

- 我的需求有没有被理解清楚？
- 系统能不能主动问出缺失信息？
- 交付物能不能稳定复用？
- 结果有没有测试和验收？
- 失败后能不能自动修复？
- 下次类似需求能不能更快交付？

如果没有工程化平台，大模型能力会被浪费在一次性对话里：

- 需求不结构化，后续无法复用。
- 每次构建都从零开始。
- prompt、脚本、参考文件散落在个人机器上。
- 缺少自动化测试，无法放心分发。
- 缺少 replay，失败后无法复盘。
- 缺少 telemetry，成本和质量不可量化。
- 缺少 registry，组织能力无法沉淀。

SkillFoundry 的目标是把这些一次性智能转化为组织级能力资产。

## 3. 核心产品定义

SkillFoundry 是一套大模型需求管理与能力交付平台。

它接收自然语言需求，输出经过验证的自动化能力资产。

第一阶段能力资产定义为 Codex Skill：

```text
业务需求
  -> Skill Spec
  -> SKILL.md / references / scripts / tests
  -> validation report
  -> approved registry entry
```

平台不是简单生成文件，而是维护完整生命周期：

1. 需求澄清
2. 需求结构化
3. 可行性评估
4. 构建或复用决策
5. Skill 生成
6. 自动化测试
7. 失败修复
8. 人类验收或自动批准
9. 注册分发
10. 使用反馈回流

## 4. 和 LangGraph、ContextForge、Codex 的关系

### 4.1 LangGraph

LangGraph 负责工作流编排。

它回答：

- 当前流程走到哪一步？
- 下一个节点是谁？
- 失败后重试还是转人工？
- 是否需要分支、回滚、暂停、恢复？
- 哪些状态需要 checkpoint？

SkillFoundry 会把需求交付过程拆成 LangGraph 节点。

### 4.2 ContextForge

ContextForge 负责上下文运行时。

它回答：

- 当前模型调用应该看到什么？
- 哪些历史和工具输出不该进 prompt？
- 工具日志如何治理？
- memory 如何显式注入？
- PromptView 如何归因？
- 使用量和成本如何记录？
- 模型调用如何 replay？

在 SkillFoundry 中，所有重要 LLM 调用都必须通过 ContextForge 的模型调用边界。

### 4.3 Codex / Coding Worker

Codex 或类似 coding worker 负责具体工程产出：

- 编写 `SKILL.md`
- 整理参考文件
- 生成脚本
- 生成测试
- 根据验证失败进行修复

在架构上，Codex 不是内核，而是外部 worker 边界。

这点很重要：SkillFoundry 不直接复制 Codex 的上下文管理实现，而是学习其思想，并用 ContextForge 建立自己的上下文纪律。

## 5. MVP 范围

第一阶段 MVP 只做 Codex Skill 工厂，不做泛化任务平台。

### 5.1 MVP 必须完成

MVP 必须支持以下闭环：

1. 输入一个自然语言 Skill 需求。
2. 需求澄清 Agent 主动补齐目标、输入、输出、约束和验收标准。
3. 生成结构化 `SkillSpec`。
4. 路由 Agent 判断复用、修改、构建或拒绝。
5. 构建 Agent 生成 Skill 包。
6. 验证 Agent 执行静态验证和最小沙箱验证。
7. 失败时生成 repair task。
8. 修复后重新验证。
9. 通过后写入本地 Skill Registry。
10. 输出 verification report。

### 5.2 MVP 暂不做

MVP 不做以下内容：

- 多租户权限系统
- 完整 Web UI
- 企业级部署
- 大规模任务队列
- 复杂计费系统
- 任意类型 Agent 自动生成
- 真实组织知识图谱
- 多语言 SDK
- 完整 Skill marketplace

这些可以进入后续阶段。

MVP 的核心不是“大而全”，而是证明：

> 一个需求可以被自动转化为经过验证的 Codex Skill。

## 6. 核心架构

SkillFoundry 分为六层。

### 6.1 需求交互层

职责：

- 接收用户自然语言需求。
- 主动澄清缺失信息。
- 生成结构化 `SkillSpec`。

关键输出：

- 目标场景
- 输入格式
- 输出格式
- 约束条件
- 安全边界
- 验收标准

### 6.2 评估与路由层

职责：

- 判断需求是否清晰。
- 判断是否安全。
- 判断是否已有可复用 Skill。
- 判断应复用、修改、构建还是拒绝。

典型路由：

- `reuse_existing`
- `modify_existing`
- `build_new`
- `reject_unsafe`
- `ask_clarifying_question`
- `human_review_required`

### 6.3 构建层

职责：

- 生成 `SKILL.md`
- 生成 reference files
- 生成 scripts
- 生成测试样例
- 打包 Skill package

第一阶段可以使用 fake worker 或 Codex CLI/SDK worker。

### 6.4 验证层

职责：

- 静态结构检查
- 触发场景检查
- 非触发场景检查
- 文件路径安全检查
- 沙箱运行
- LLM-as-a-Judge
- 验收标准覆盖检查

验证层是 SkillFoundry 的生命线。

没有验证层，Skill 工厂只是 prompt 生成器。

### 6.5 注册与分发层

职责：

- 记录 approved Skill
- 保存版本、路径、验证报告、构建来源
- 支持后续检索、复用和分发

第一阶段可以是本地 JSON registry。

后续可以升级到数据库和私有 Skill marketplace。

### 6.6 反馈学习层

职责：

- 收集使用反馈
- 收集失败样例
- 更新测试集
- 更新 memory
- 推动 Skill 版本迭代

第一阶段只设计接口，不强行实现完整闭环。

## 7. LangGraph 工作流草案

第一版 LangGraph 可以是线性主流程加少量分支：

```text
intake
  -> clarify
  -> spec_review
  -> route
  -> build_or_reuse
  -> validate
  -> repair_if_failed
  -> validate_again
  -> register_if_passed
  -> emit_report
```

关键分支：

```text
route.reject -> emit_rejection_report
route.reuse -> register_reuse_decision
validate.failed -> repair
repair.failed_too_many_times -> human_review
```

每个 LLM 节点都必须通过 ContextForge：

```text
LangGraph Node
  -> ContextRequest
  -> ContextForge.prepare()
  -> PromptView
  -> ModelCallEnvelope
  -> ContextKernel.invoke_model()
  -> ModelCallRecord / UsageRecord / ReplayBundle
  -> LangGraph State Update
```

## 8. ContextForge 集成原则

SkillFoundry 不能绕过 ContextForge。

必须遵守以下规则：

1. 所有模型调用必须生成 `ModelCallEnvelope`。
2. 所有 prompt 必须有 `PromptView`。
3. 工具输出必须经过 `ToolOutputGovernor`。
4. memory 必须显式请求，不能默认注入。
5. 每个构建任务必须生成 replay artifact。
6. 每个通过的 Skill 必须有 verification report。
7. metrics 必须记录 prompt 数量、工具输出压缩、usage 和 replay 覆盖率。

这些规则的目的不是形式主义，而是让系统长期运行后仍然可审计、可恢复、可控成本。

## 9. 数据对象草案

### 9.1 SkillSpec

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

### 9.2 BuildJob

```text
job_id
skill_spec_id
status
assigned_worker
attempt_count
created_at
updated_at
ledger_ref
artifact_root
```

### 9.3 ValidationReport

```text
report_id
skill_id
version
static_passed
trigger_passed
sandbox_passed
judge_passed
failures
repair_prompt
evidence_refs
```

### 9.4 RegistryEntry

```text
skill_id
version
package_path
validation_report_id
approval_status
created_at
metadata
```

## 10. 成功标准

MVP 不是以“模型看起来能回答”为成功标准。

MVP 成功标准是：

1. 能从自然语言需求生成结构化 SkillSpec。
2. 能构建一个本地 Skill package。
3. 能检测一个故意失败的 Skill。
4. 能生成 repair task 并修复。
5. 能重新验证通过。
6. 能写入 registry。
7. 能输出 verification report。
8. 能 replay 至少一次关键模型调用。
9. 能证明 raw tool output 没有直接污染 prompt。
10. 能证明 memory 是显式注入的。

## 11. 风险与边界

### 11.1 最大风险：形式化 Agent 工厂

如果没有严格验收，SkillFoundry 很容易变成一个会生成漂亮文件的聊天机器人。

应对：

- verification report 是硬门。
- 没有测试通过不能 approved。
- 每次模型调用必须可 replay。

### 11.2 第二风险：上下文失控

复杂任务中，工具输出、历史记录、memory 很容易污染 prompt。

应对：

- 用 ContextForge 统一上下文入口。
- raw tool output 不允许直接进入 prompt。
- memory search 和 memory injection 分离。

### 11.3 第三风险：过早平台化

一开始就做 UI、权限、多租户、队列，会拖慢核心验证。

应对：

- 第一阶段只做本地或最小 API。
- 先证明一个 Skill 构建闭环。
- 验证闭环跑通后再产品化。

## 12. 路线图

### Phase 0：项目定义

- 项目命名
- git 仓库
- 白皮书
- MVP 边界

### Phase 1：工作包拆分

- 拆分 LangGraph 节点
- 定义数据模型
- 定义 ContextForge 集成接口
- 定义验收命令

### Phase 2：离线 MVP

- 本地 CLI 输入需求
- LangGraph 或 graph-like 流程
- ContextForge 接入
- fake / local worker
- 本地 registry
- verification report

### Phase 3：真实 Codex Worker

- 接 Codex CLI 或 SDK
- 真实生成 Skill 包
- 沙箱执行测试
- 自动修复循环

### Phase 4：产品化

- API 服务
- 最小 UI
- 任务队列
- 用户反馈
- Skill 版本管理
- 团队内部分发

## 13. 第一阶段结论

SkillFoundry 的第一阶段目标非常明确：

> 不做通用万能 Agent 平台，先做一个能稳定生产、验证、修复和注册 Codex Skill 的工厂。

这条路线有三个好处：

1. 目标足够具体，容易验收。
2. 能直接复用 ContextForge 已有能力。
3. 交付物是组织可沉淀的 Skill 资产，而不是一次性回答。

如果这个 MVP 成功，SkillFoundry 后续可以自然扩展成更通用的大模型需求交付平台。

