# SkillFoundry

SkillFoundry，中文名“技能铸造厂”，是一个基于 **LangGraph + ContextForge + 外部 Worker 边界** 的大模型需求交付平台 MVP。

它的第一个产品形态是 **Codex Skill 工厂**：把业务方的模糊需求，转化为结构化规格、可测试 Skill 包、自动化验收报告和可复用能力资产。

## 项目定位

ContextForge 是上下文运行时与证据账本。它负责 **SkillFoundry 自有 LLM 调用** 前后的上下文纪律：

- PromptView / PromptBlock
- 工具输出治理
- memory 显式注入
- owned LLM call replay
- telemetry

对 Codex Worker 这类外部 worker，ContextForge 只记录边界证据，例如 worker 输入输出、transcript、diff、hash、duration、Verifier 结果和 usage 是否可得；Codex Worker 内部 prompt、tool loop、context compaction、cache 或 cost 不属于 ContextForge 的控制或 replay 范围。

SkillFoundry 是产品层，负责把这些能力组织成一套需求交付流水线：

- 需求澄清
- 可行性评估
- Skill 构建
- 自动化校验
- 失败修复
- 注册分发
- 使用反馈沉淀

## 当前阶段

当前 WP0-WP10 已完成：项目已经具备离线可验证的 Codex Skill 工厂闭环、可选 CodexWorker pilot adapter、最小内部 API/UI 入口，以及 QA Lab 质量报告层。下一阶段是 WP11 Feedback + Versioning，也就是把一次性 Skill 生成扩展为可持续维护的能力资产系统。

本仓库暂时不直接复制 ContextForge 代码。后续会以依赖或 workspace 方式接入 `/home/mansteinl/contextforge` 中已经完成的 ContextForge v0.1 内核。

## 第一个 MVP

第一个 MVP 只做一件事：

> 构建一个离线可验证的 Codex Skill 工厂闭环。

最小闭环包括：

1. 用户提交自然语言需求。
2. 需求澄清 Agent 生成结构化 Skill Spec。
3. LangGraph 编排构建流程。
4. ContextForge 管理 SkillFoundry 自有 LLM 调用的上下文，并记录 Codex Worker 的边界证据。
5. WorkerAdapter 调用 FakeWorker 或后续真实 Codex Worker 生成 `SKILL.md`、参考文件和测试。
6. 独立 Verifier 执行静态检查、触发检查、路径/hash 检查、沙箱 smoke 和可选 LLM judge。
7. 失败后自动生成 repair task。
8. 通过验收后写入 Skill Registry。
9. 输出 verification report，证明该 Skill 可以被审查，并能复现自有 LLM 调用与边界证据。

## 当前仓库文件

```text
README.md                  # 项目入口说明
WHITEPAPER.md              # 项目白皮书
docs/ROADMAP.md            # 分阶段路线
docs/ROADMAP_EXECUTION_PLAN.md # 可直接执行的分阶段 Roadmap
docs/ARCHITECTURE.md       # v0.2 架构边界
docs/WORK_PACKAGES.md      # WP0-WP10 工作包
docs/ACCEPTANCE_PLAN.md    # 验收计划
.gitignore                 # 本地运行产物忽略规则
```

## 白皮书

请从 [WHITEPAPER.md](WHITEPAPER.md) 开始阅读。

它回答以下问题：

- 为什么要做 SkillFoundry
- 它和 LangGraph、ContextForge、Codex 的关系是什么
- Codex Skill 工厂的 MVP 边界是什么
- 核心架构如何分层
- 哪些能力必须第一阶段实现
- 哪些能力明确不是 MVP
- 如何验收这个项目不是“玩具 Agent”

## Roadmap

分阶段技术路线见 [docs/ROADMAP.md](docs/ROADMAP.md)。

如果要交给第三方 Agent 或工程师逐阶段执行，优先阅读 [docs/ROADMAP_EXECUTION_PLAN.md](docs/ROADMAP_EXECUTION_PLAN.md)。这份文档按 WP0-WP12 写清楚了每个阶段的目标、输入、主要任务、交付物、验收门和退出条件。

当前推荐路线是：

```text
LangGraph 编排
+ 文件即上下文 workspace 协议
+ Codex Worker 黑盒外部构建
+ 独立 Verifier 主质量门
+ Registry approved asset store
+ ContextForge 自有 LLM 运行时与任务级证据账本
```

这意味着 SkillFoundry 第一阶段不是自建完整 ActionRuntime，而是先把外部 Codex Worker 纳入严格的任务协议、workspace 权限、独立验收和 registry gate 中。真实 Codex Worker 集成必须等待 workspace confinement、WorkerAdapter、Verifier 和 Registry gate 存在后再试点。

## 设计原则

- LangGraph 管流程，ContextForge 管自有 LLM 上下文和边界证据，SkillFoundry 管需求交付。
- 所有 Skill 生成结果必须可测试、可验证、可追溯；自有 LLM 调用可 replay，Codex Worker 内部过程只做边界记录。
- 自动化不是直接相信模型，而是给模型建立工程化闭环。
- Verifier 是主质量门，builder self-report 不是验收证据。
- MVP 不追求全自动万能平台，先追求一个可审计的高质量 Skill 构建闭环。
- Codex / OpenHuman 只作为思想参考，不复制其源码。

## 下一步

1. 启动 WP11 Feedback + Versioning。
2. 定义 feedback record，并能从失败使用案例生成 repair job。
3. 支持 Skill 版本升级、quarantine 和 rollback。
4. 新版本必须继续通过 Verifier、QA Lab 和 Registry gate。
5. WP11 稳定后，再推进 WP12 Production Hardening。
