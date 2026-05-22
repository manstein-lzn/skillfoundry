# SkillFoundry

SkillFoundry，中文名“技能铸造厂”，是一个基于 **LangGraph + ContextForge + 外部 Worker 边界** 的大模型需求交付平台 MVP。

它的第一个产品形态是 **Codex Skill 工厂**：把业务方的模糊需求，转化为结构化规格、可测试 Skill 包、自动化验收报告和可复用能力资产。

## 项目定位

> v2 基线说明：当前 SkillFoundry 没有线上兼容性负担。旧 WP0-WP17 代码和文档是 v0 原型与知识资产，不是后续技术实现约束。后续实现将以新版 ContextForge Goal Harness 为外骨骼重建技术骨架。v2 当前集成蓝图见 [docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md](docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md)，阶段实现计划和历史执行证据见 [docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md](docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md)，前提说明见 [docs/SKILLFOUNDRY_V2_BASELINE.md](docs/SKILLFOUNDRY_V2_BASELINE.md)。

ContextForge 是 agent 工作外骨骼和证据账本。它负责 SkillFoundry 每个强 agent node 的上下文纪律和运行边界：

- GoalContract / AgentNodeContract
- ContextView / PromptView / PromptBlock
- PromptCachePlan
- tool permission / write scope
- 工具输出治理
- checkpoint / WorkerRun / VerificationResult / GoalRunRecord
- ledger / replay / telemetry

对 Codex SDK thread 这类外部强 worker，ContextForge 只记录边界证据，例如输入合同、可见上下文、transcript、diff、artifact refs、changed files、Verifier 结果和 usage 是否可得；Codex 内部 prompt、tool loop、context compaction、cache chain 或 cost 不属于 ContextForge 的控制或 replay 范围。

SkillFoundry 是产品层，负责把这些能力组织成一套需求交付流水线：

- 需求澄清
- 可行性评估
- Skill 构建
- 自动化校验
- 失败修复
- 注册分发
- 使用反馈沉淀

## 当前阶段

当前 WP0-WP17 已完成：项目已经具备离线可验证的 Codex Skill 工厂闭环、可选 CodexWorker pilot adapter、最小内部 API/UI 入口、QA Lab 质量报告层、反馈驱动的版本治理能力、面向小规模内部试用的运维文档，以及 Front Desk 的 schema/workspace、RequirementsElicitor、SpecAuditor、deterministic FrontDeskFreezeGate、FrontDeskLoop、Acceptance Coverage Bridge 和 `LLMSkillBuilderWorker` 自有 LLM builder 试点。

这不等于完整生产级多租户平台已经完成，也不等于默认会调用真实 LLM provider 或 live Codex。当前 v2 状态是：ContextForge contract bridge、offline Goal Harness runtime、workers v2、graph v2、verification bridge、registry evidence gate、Front Desk v2 Goal Harness slices、Front Desk approved-plan audit/freeze、API graph v2 build happy path，以及 failed verification -> Goal Harness repair -> verifier / acceptance coverage / ContextForge bridge / registry gate 闭环已经存在；`GET /jobs/{job_id}/contextforge` 已能暴露 build path、repair evidence、human-review、verification 和 registry 的 refs-only 摘要；产品主路径仍需继续收敛到这套 v2 骨架，尤其是 graph_v2 canonical 化、human-review workbench、legacy 退役和更完整的 UI evidence 体验。

ContextForge 以 Git submodule 形式挂载在 `third_party/contextforge`，并通过 `pyproject.toml` 的 editable path source 接入本工程。

## 第一个 MVP

第一个 MVP 只做一件事：

> 构建一个离线可验证的 Codex Skill 工厂闭环。

最小闭环包括：

1. 用户提交自然语言需求。
2. 需求澄清 Agent 生成结构化 Skill Spec。
3. LangGraph 编排构建流程。
4. ContextForge 管理每个强 agent node 的 GoalContract、ContextView、PromptCachePlan、WorkerRun、checkpoint 和边界证据。
5. WorkerAdapter 调用 FakeWorker 或后续真实 Codex Worker 生成 `SKILL.md`、参考文件和测试。
6. 独立 Verifier 执行静态检查、触发检查、路径/hash 检查、沙箱 smoke 和可选 LLM judge。
7. 失败后自动生成 repair task。
8. 通过验收后写入 Skill Registry。
9. 输出 verification report，证明该 Skill 可以被审查，并能复现自有 LLM 调用与边界证据。

## 当前仓库文件

```text
README.md                  # 项目入口说明
HANDOFF.md                 # 当前实现状态和接手说明
WHITEPAPER.md              # 项目白皮书
docs/ROADMAP.md            # 历史分阶段路线
docs/DEVELOPMENT_ROADMAP.md # v0/WP0-WP17 能力基线和产品经验
docs/ROADMAP_EXECUTION_PLAN.md # 历史执行路线，WP17 后不再作为当前执行源
docs/FRONT_DESK_AGENT_ROADMAP.md # WP13-WP17 设计形成文档，状态已由当前 roadmap 覆盖
docs/FRONT_DESK_ROADMAP_AUDIT.md # 独立 gpt-5.5 xhigh 架构审核结论
docs/FRONT_DESK_CORE_NEED_REFACTOR.md # Phase A 需求澄清层重构执行路线
docs/CONTEXTFORGE_AGENT_EXOSKELETON_PRODUCT_VISION.md # ContextForge Goal Harness 产品愿景
docs/SKILLFOUNDRY_V2_BASELINE.md # v2 重建基线：保留思想，重建实现
docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md # v2 当前集成蓝图和迁移总图
docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md # v2 阶段实现计划和历史执行证据
docs/archive/agent-briefs/ # 旧 WP0-WP17 agent brief 归档
docs/DEVELOPMENT_ROADMAP_AUDIT.md # v0 roadmap 的独立审核记录
docs/ARCHITECTURE.md       # v0.2 架构边界
docs/WORK_PACKAGES.md      # WP0-WP10 工作包
docs/ACCEPTANCE_PLAN.md    # 验收计划
docs/OPERATIONS.md         # WP12 内部 beta 运维说明
docs/SECURITY_CHECKLIST.md # WP12 安全检查清单
docs/PRODUCTION_READINESS.md # WP12 生产就绪边界和迁移评估
.gitignore                 # 本地运行产物忽略规则
```

## 开发环境

本仓库把 ContextForge 作为 Git submodule 嵌入在 `third_party/contextforge`：

```bash
git clone --recurse-submodules <skillfoundry-repo>
cd skillfoundry
git submodule update --init --recursive
uv run --extra test pytest -q
```

`pyproject.toml` 中通过 `tool.uv.sources` 将 `contextforge==0.1.0` 解析到本地 submodule，并把 `uv` 默认包源设为清华 PyPI 镜像。若需要临时换源，可用：

```bash
uv run --default-index https://mirrors.aliyun.com/pypi/simple/ --extra test pytest -q
```

如果当前机器还没有安装 `uv`，但 checkout 已经包含可用 `.venv`，可以先用现有虚拟环境验证：

```bash
.venv/bin/python -m pytest -q
```

若不用 `uv`，需要先安装 submodule：

```bash
python -m pip install -e third_party/contextforge
python -m pip install -e ".[test]"
python -m pytest -q
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

v2 当前集成蓝图见 [docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md](docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md)。阶段实现计划和历史执行证据见 [docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md](docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md)。当前 v0/WP0-WP17 能力基线和产品经验见 [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md)。历史分阶段技术路线见 [docs/ROADMAP.md](docs/ROADMAP.md)。

如果要交给第三方 Agent 或工程师执行 v2 重建，先读 [docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md](docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md) 和 [HANDOFF.md](HANDOFF.md)，再参考 [docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md](docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md) 的阶段计划和 [docs/SKILLFOUNDRY_V2_BASELINE.md](docs/SKILLFOUNDRY_V2_BASELINE.md) 的“不背 v0 兼容债”前提。[docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md)、[docs/ROADMAP.md](docs/ROADMAP.md)、[docs/ROADMAP_EXECUTION_PLAN.md](docs/ROADMAP_EXECUTION_PLAN.md)、[docs/FRONT_DESK_AGENT_ROADMAP.md](docs/FRONT_DESK_AGENT_ROADMAP.md) 和 [docs/FRONT_DESK_ROADMAP_AUDIT.md](docs/FRONT_DESK_ROADMAP_AUDIT.md) 只用于理解 v0 能力、历史设计与 WP13-WP17 的形成过程，不再约束 v2 模块边界。

当前推荐路线是：

```text
LangGraph 编排
+ 文件即上下文 workspace 协议
+ ContextForge Goal Harness agent 工作外骨骼
+ Codex SDK thread / GPT-5.5 / external worker 边界执行
+ 独立 Verifier 主质量门
+ Registry approved asset store
```

这意味着 SkillFoundry 不自建完整 ActionRuntime，也不把 Codex SDK thread 当成纯黑盒最终事实源。真实 Codex Worker 集成必须等待 workspace confinement、Goal Harness worker boundary、Verifier 和 Registry gate 存在后再试点。

## 设计原则

- LangGraph 管流程，ContextForge 管每个强 agent node 的上下文视界、缓存计划、边界证据和 checkpoint，SkillFoundry 管需求交付。
- 所有 Skill 生成结果必须可测试、可验证、可追溯；owned LLM 调用可 replay，Codex SDK thread 内部过程只做边界记录。
- 自动化不是直接相信模型，而是给模型建立工程化闭环。
- Verifier 是主质量门，builder self-report 不是验收证据。
- MVP 不追求全自动万能平台，先追求一个可审计的高质量 Skill 构建闭环。
- Codex / OpenHuman 只作为思想参考，不复制其源码。

## 下一步

1. 继续把 `graph_v2.py` 收敛为唯一的 build / verify / repair / registry 产品主骨架；当前默认 Front Desk frozen job 已能通过 `/frontdesk/jobs/{job_id}/build` 进入 graph v2 verified build / registry happy path，failed verification route 也能执行 Goal Harness-backed repair 并重新进入 verifier / acceptance coverage / registry gate。
2. 完善 API/UI 对 v2 refs、ContextForge status、registry outcome、repair/human-review route 的消费，保持不泄漏 raw prompt / raw payload。
3. 隔离或退役旧 `graph.py`、legacy prompt/context/worker 路径，把 v2 contract/graph/runtime 设为默认贡献入口。
4. 保持默认测试 deterministic/offline；真实 provider 和 Codex 只做 opt-in smoke。
5. 用 3-5 个真实 Codex Skill 需求做内部试运行，记录成本、轮数、成功率、repair 成功率、cache/prefix churn 和失败分类。
6. 在完成 auth、tenant、queue、audit、monitoring、deployment、secrets、incident response 之前，不对外宣称生产级平台。
