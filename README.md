# SkillFoundry

SkillFoundry，中文名“技能铸造厂”，是一个基于 **LangGraph + ContextForge** 的大模型需求管理平台 MVP。

它的第一个产品形态是 **Codex Skill 工厂**：把业务方的模糊需求，转化为结构化规格、可测试 Skill 包、自动化验收报告和可复用能力资产。

## 项目定位

ContextForge 是上下文管理内核，负责模型调用前后的上下文纪律：

- PromptView / PromptBlock
- 工具输出治理
- memory 显式注入
- replay
- telemetry
- verification report

SkillFoundry 是产品层，负责把这些能力组织成一套需求交付流水线：

- 需求澄清
- 可行性评估
- Skill 构建
- 自动化校验
- 失败修复
- 注册分发
- 使用反馈沉淀

## 当前阶段

当前是项目启动阶段，先完成产品白皮书和 MVP 边界定义。

本仓库暂时不直接复制 ContextForge 代码。后续会以依赖或 workspace 方式接入 `/home/mansteinl/contextforge` 中已经完成的 ContextForge v0.1 内核。

## 第一个 MVP

第一个 MVP 只做一件事：

> 构建一个离线可验证的 Codex Skill 工厂闭环。

最小闭环包括：

1. 用户提交自然语言需求。
2. 需求澄清 Agent 生成结构化 Skill Spec。
3. LangGraph 编排构建流程。
4. ContextForge 管理 SkillFoundry 自有 LLM 调用的上下文，并记录 Codex Worker 的边界证据。
5. 构建 Agent 生成 `SKILL.md`、参考文件和测试。
6. 验证 Agent 执行静态检查、触发检查、沙箱检查和 LLM judge。
7. 失败后自动生成 repair task。
8. 通过验收后写入 Skill Registry。
9. 输出 verification report，证明该 Skill 可以被审查和复现。

## 当前仓库文件

```text
README.md       # 项目入口说明
WHITEPAPER.md   # 项目白皮书
.gitignore      # 本地运行产物忽略规则
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

当前推荐路线是：

```text
LangGraph 编排
+ 文件即上下文 workspace 协议
+ Codex Worker 黑盒执行
+ 独立 Verifier 强验收
+ Registry 资产沉淀
+ ContextForge 任务级证据账本
```

这意味着 SkillFoundry 第一阶段不是自建完整 ActionRuntime，而是先把外部 Codex Worker 纳入严格的任务协议、workspace 权限、独立验收和 registry gate 中。

## 设计原则

- LangGraph 管流程，ContextForge 管上下文，SkillFoundry 管需求交付。
- 所有 Skill 生成结果必须可测试、可验证、可 replay。
- 自动化不是直接相信模型，而是给模型建立工程化闭环。
- MVP 不追求全自动万能平台，先追求一个可审计的高质量 Skill 构建闭环。
- Codex / OpenHuman 只作为思想参考，不复制其源码。

## 下一步

1. 根据白皮书拆分 work packages。
2. 设计最小 LangGraph 工作流。
3. 接入 ContextForge v0.1。
4. 实现第一个 Skill 构建任务。
5. 建立自动化 verification gate。
