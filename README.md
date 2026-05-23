# SkillFoundry

SkillFoundry，中文名“技能铸造厂”，是一个基于 **LangGraph + ContextForge + 外部 Worker 边界** 的大模型需求交付平台 MVP。

它的第一个产品形态是 **Codex Skill 工厂**：把业务方的模糊需求，转化为结构化规格、可测试 Skill 包、自动化验收报告和可复用能力资产。

## 项目定位

> v2 基线说明：当前 SkillFoundry 没有线上兼容性负担。旧 WP0-WP17 代码和文档是 v0 原型与知识资产，不是后续技术实现约束。后续实现将以新版 ContextForge Goal Harness 为外骨骼重建技术骨架。v2 当前集成蓝图见 [docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md](docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md)，阶段实现计划和历史执行证据见 [docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md](docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md)，前提说明见 [docs/SKILLFOUNDRY_V2_BASELINE.md](docs/SKILLFOUNDRY_V2_BASELINE.md)。ForgeUnit 完成后的产品化方向见 [docs/SKILLFOUNDRY_ON_FORGEUNIT_PRODUCT_DIRECTION.md](docs/SKILLFOUNDRY_ON_FORGEUNIT_PRODUCT_DIRECTION.md)。

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

这不等于完整生产级多租户平台已经完成，也不等于默认会调用真实 LLM provider 或 live Codex。当前 v2 状态是：ContextForge contract bridge、offline Goal Harness runtime、workers v2、graph v2、verification bridge、registry evidence gate、Front Desk v2 Goal Harness slices、Front Desk approved-plan audit/freeze、API graph v2 build happy path，以及 failed verification -> Goal Harness repair -> verifier / acceptance coverage / ContextForge bridge / registry gate 闭环已经存在；canonical graph v2 route 中首次 registry approval 已收敛到 registry gate，direct verified runtime helper 的自动注册只作为 compatibility 行为保留；human-review 已有 request / decision artifact 和 API decision endpoint，人工决定不会绕过 verifier/registry；`GET /jobs/{job_id}/contextforge` 已能暴露 build path、repair evidence、human-review、verification 和 registry 的 refs-only 摘要；`GET /jobs/{job_id}` 在 `Accept: text/html` 下也会渲染 refs-only job evidence 页面；旧 `POST /jobs` 离线 builder 已默认禁用，只能显式 opt-in 作为 compatibility route 使用；产品主路径仍需继续收敛到这套 v2 骨架，尤其是 legacy 最终退役、更完整的人审运营体验和 live worker pilot 前的边界硬化。

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
docs/SKILLFOUNDRY_ON_FORGEUNIT_PRODUCT_DIRECTION.md # SkillFoundry 作为 ForgeUnit 首个产品场景的后续方向
docs/FORGEUNIT_PRODUCT_ADAPTER_SLICE.md # SkillFoundry 接入 ForgeUnit v1.2 的第一层产品适配切片
docs/FORGEUNIT_SKILLFOUNDRY_COMPOSITION.md # 新版 SkillFoundry-on-ForgeUnit clean composition layer
docs/FORGEUNIT_REAL_CODEX_EXEC_PILOT.md # ForgeUnit 真实 Codex exec 手动 pilot，不进默认 CI
docs/FRONTDESK_FORGEUNIT_COMMAND_PILOT_RUNBOOK.md # FrontDesk API 真实 command boundary 手动试运行协议
docs/FRONTDESK_LIVE_SEMANTIC_EVAL.md # FrontDesk live Codex semantic eval 手动门槛
docs/FRESH_CLONE_GATE.md # 新用户 fresh clone 离线可复现门槛
docs/DEVELOPMENT_WORKFLOW.md # 默认本地开发和验证命令
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
uv run --extra test --extra forgeunit pytest -q
```

`pyproject.toml` 中通过 `tool.uv.sources` 将 `contextforge==0.1.0` 解析到本地 submodule，并把 `uv` 默认包源设为清华 PyPI 镜像。ForgeUnit 不再从本机 sibling 目录 `../ForgeUnit` 解析；`forgeunit` extra 固定到已推送的 Git tag `v1.2.1`。若需要临时换源，可用：

```bash
uv run --default-index https://mirrors.aliyun.com/pypi/simple/ --extra test --extra forgeunit pytest -q
```

如果当前机器还没有安装 `uv`，但 checkout 已经包含可用 `.venv`，可以先用现有虚拟环境验证：

```bash
.venv/bin/python -m pytest -q
```

若不用 `uv`，需要先安装 submodule：

```bash
python -m pip install -e third_party/contextforge
python -m pip install -e ".[test,forgeunit]"
python -m pytest -q
```

新用户可复现门槛见 [docs/FRESH_CLONE_GATE.md](docs/FRESH_CLONE_GATE.md)。本地可以用脚本在临时目录执行同等检查：

```bash
.venv/bin/python scripts/check_fresh_clone_readiness.py \
  --repo-url git@github.com:manstein-lzn/skillfoundry.git \
  --branch main \
  --summary-out .metaloop/phase10_fresh_clone_smoke_summary.json
```

真实 Codex semantic eval 是显式手动门槛，不进入默认测试；操作协议见 [docs/FRONTDESK_LIVE_SEMANTIC_EVAL.md](docs/FRONTDESK_LIVE_SEMANTIC_EVAL.md)。

## 常用开发命令

默认开发入口见 [docs/DEVELOPMENT_WORKFLOW.md](docs/DEVELOPMENT_WORKFLOW.md)：

```bash
make focused
make test
make fresh-clone-smoke
make live-semantic-eval-help
```

这些命令不会默认调用 live Codex。`make fresh-clone-smoke` 会使用 Git/network
创建临时 clone 并跑离线 smoke；live Codex semantic eval 必须按 runbook 手动执行。

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

v2 当前集成蓝图见 [docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md](docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md)。ForgeUnit 完成后的后续产品化方向见 [docs/SKILLFOUNDRY_ON_FORGEUNIT_PRODUCT_DIRECTION.md](docs/SKILLFOUNDRY_ON_FORGEUNIT_PRODUCT_DIRECTION.md)。阶段实现计划和历史执行证据见 [docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md](docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md)。当前 v0/WP0-WP17 能力基线和产品经验见 [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md)。历史分阶段技术路线见 [docs/ROADMAP.md](docs/ROADMAP.md)。

如果要交给第三方 Agent 或工程师执行 v2 重建，先读 [docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md](docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md) 和 [HANDOFF.md](HANDOFF.md)，再参考 [docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md](docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md) 的阶段计划和 [docs/SKILLFOUNDRY_V2_BASELINE.md](docs/SKILLFOUNDRY_V2_BASELINE.md) 的“不背 v0 兼容债”前提。[docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md)、[docs/ROADMAP.md](docs/ROADMAP.md)、[docs/ROADMAP_EXECUTION_PLAN.md](docs/ROADMAP_EXECUTION_PLAN.md)、[docs/FRONT_DESK_AGENT_ROADMAP.md](docs/FRONT_DESK_AGENT_ROADMAP.md) 和 [docs/FRONT_DESK_ROADMAP_AUDIT.md](docs/FRONT_DESK_ROADMAP_AUDIT.md) 只用于理解 v0 能力、历史设计与 WP13-WP17 的形成过程，不再约束 v2 模块边界。

当前推荐路线是：

```text
LangGraph 编排
+ ForgeUnit work-unit harness
+ ContextForge context/cache/checkpoint substrate
+ Codex exec / future Codex SDK thread / external worker 边界执行
+ 独立 Verifier 主质量门
+ Registry approved asset store
```

这意味着 SkillFoundry 不自建完整 ActionRuntime，也不把 Codex exec / Codex SDK thread 当成最终事实源。真实 Codex Worker 集成必须等待 ForgeUnit repair pilot 继续收敛为更完整的 repair policy，并补齐 ContextPacket、PromptCachePlan 和运行诊断后再试点。

当前已经开始落地 ForgeUnit 产品适配层，入口见
[docs/FORGEUNIT_PRODUCT_ADAPTER_SLICE.md](docs/FORGEUNIT_PRODUCT_ADAPTER_SLICE.md)。
第一层代码位于 `src/skillfoundry/forgeunit_adapter.py`，可以把现有
`JobWorkspace` 物化为 ForgeUnit task pack，并通过 ForgeUnit v1.2.1 的
`ForgeUnitNode("codex_exec")` 返回 refs-only v2 graph state。当前有两条
pilot 路径：

- `run_forgeunit_pilot_graph(...)`：dry-run 后生成
  `forgeunit_boundary_verification.json` 和 `human_review/request.json`，明确
  停在 human review，不会把 dry-run 当成 verifier 通过或 registry approval。
- `run_forgeunit_command_bridge_pilot_graph(...)`：使用显式本地 command
  bridge 模拟 Codex exec，产出 `package/SKILL.md`、ForgeUnit evidence 和
  `attempts/001` SkillFoundry evidence，然后进入 `Verifier` 与
  `LocalSkillRegistry`。测试仍然完全离线，不调用 live Codex。
- `run_forgeunit_repair_pilot_graph(...)`：最小 repair pilot。第一次
  ForgeUnit command bridge 可以产出 ForgeUnit-valid 但 SkillFoundry-invalid
  的包，`Verifier` 归档 `attempts/001/verification_result.json` 后写
  `contextforge/forgeunit_repair_packet.json`；第二次 command bridge 写入
  `attempts/002`，只有修复后的 verifier 通过才进入 registry。
- `scripts/run_forgeunit_real_codex_exec_pilot.py`：手动 integration pilot，
  通过 `scripts/forgeunit_codex_exec_worker.py` 包装真实 `codex exec` 或显式
  fake command。该路径只由人工显式运行，不进入默认测试。

新的清爽拼接层位于 `src/forgeunit_skillfoundry/`，文档见
[docs/FORGEUNIT_SKILLFOUNDRY_COMPOSITION.md](docs/FORGEUNIT_SKILLFOUNDRY_COMPOSITION.md)。
它不迁移旧 `src/skillfoundry/` 产品树，而是把旧包里已经稳定的
`JobWorkspace`、Verifier、Registry 和 ForgeUnit adapter 作为能力库复用，提供
`run_codex_skill_factory(...)` 这样的 vNext 产品入口。当前它已拆出
`config.py` / `engine.py` / `graph.py` / `state.py` / `product.py` 内核边界，
通过 `run_skill_factory_graph(...)` 提供薄 LangGraph 产品骨架，覆盖 offline
happy path 和 repair path，并写入
`contextforge/forgeunit_skillfoundry_product_state.json` 与
`contextforge/forgeunit_skillfoundry_graph_state.json` 作为 refs-only 状态，同时写
`contextforge/forgeunit_skillfoundry_summary.json` 作为统一 evidence read model。
本地脚本入口是 `scripts/run_forgeunit_skill_factory.py`，支持显式
`--command/--repair-command`，也支持 `--fake-mode happy|repair` 做离线 smoke；
stdout 直接输出这份 refs-only summary。
Phase 5 还新增了 `forgeunit_skillfoundry.adapters`：既可以把已经存在且锁定
输入的 `JobWorkspace` 直接路由进 vNext，也可以在 `frontdesk/state.json` 已经
`frozen + route_to_build` 且 `freeze_manifest` hash 校验通过时，把 Front Desk
冻结任务路由进同一条 vNext 路径。FrontDesk frozen workspace 若包含
`acceptance_criteria.yaml`，ForgeUnit registry gate 会在注册前生成
`qa/acceptance_coverage_plan.json` 和 `qa/acceptance_coverage_result.json`，保持
registry 的证据门不被绕过。
Phase 6 已把 `POST /frontdesk/jobs/{job_id}/build` 默认接到这条 vNext 路径；
旧 `graph_v2_goal_harness` 构建只作为显式兼容模式保留，可通过请求体
`{"build_mode": "graph_v2"}` 调用。API 响应返回
`contextforge/forgeunit_skillfoundry_summary.json` 这类 refs-only read model，
不返回 worker command、raw prompt、raw conversation、raw transcript 或 package body。
Phase 7 增加了很薄的部署配置面：`SkillFoundryAPI(...,
forgeunit_command="...", forgeunit_repair_command="...")` 或环境变量
`SKILLFOUNDRY_FORGEUNIT_COMMAND` / `SKILLFOUNDRY_FORGEUNIT_REPAIR_COMMAND`
可以为 FrontDesk vNext build 提供真实 ForgeUnit/Codex command boundary；
单个请求仍可用 `{"command": "...", "repair_command": "..."}` 覆盖，也可用
`{"fake_mode": "happy"}` 或 `{"fake_mode": "repair"}` 强制离线 fake。没有任何
command 配置时默认仍是 deterministic fake happy，因此默认测试和本地 smoke 不会调用
live Codex。vNext build 失败时 API 返回 redacted `frontdesk_build_failed`，不会把
底层 exception、command string、stdout/stderr 或 transcript marker 回显给调用方。
Phase 8B 将真实 command 接入前的操作边界固定为
[docs/FRONTDESK_FORGEUNIT_COMMAND_PILOT_RUNBOOK.md](docs/FRONTDESK_FORGEUNIT_COMMAND_PILOT_RUNBOOK.md)；
测试会通过实际本地失败 subprocess 验证 API redaction，但仍不运行 live Codex。
Phase 8C 新增 `scripts/run_frontdesk_forgeunit_command_pilot.py`，可用本地
deterministic 成功 subprocess 通过 FrontDesk API 全流程完成 vNext
build/verify/registry，并只输出 refs-only pilot summary。
Phase 8D 已完成一次显式 manual live `codex exec` pilot：同一脚本通过
`scripts/forgeunit_codex_exec_worker.py` 调用
`codex exec --sandbox workspace-write --skip-git-repo-check -`，实际生成
`package/SKILL.md` 与 `evidence/manifest.json`，随后通过 SkillFoundry Verifier
和 LocalSkillRegistry，最终状态为 `registered`。这仍然不是默认测试路径；
live Codex 只作为手动 smoke，公开 summary/product read model 只保留 refs/status，
不输出 command string、raw prompt、raw transcript、raw worker input、stdout/stderr
或 package body。操作记录和命令形态见
[docs/FRONTDESK_FORGEUNIT_COMMAND_PILOT_RUNBOOK.md](docs/FRONTDESK_FORGEUNIT_COMMAND_PILOT_RUNBOOK.md)。
Phase 9 新增 `scripts/run_frontdesk_live_codex_eval.py`：它把多个 FrontDesk
scenario 逐个跑过同一条 vNext command boundary，并输出
`skillfoundry.frontdesk_live_codex_eval.v1` refs-only 聚合报告。脚本不会默认调用
live Codex；必须显式传 `--command`，或传 `--fake-mode happy` 做离线 smoke。
报告只包含 scenario/job/status、Verifier/Registry 结果、失败分类、耗时和 artifact
refs，不包含 command string、raw FrontDesk message、raw worker input、raw transcript、
stdout/stderr 或 package body。

## 设计原则

- LangGraph 管流程，ContextForge 管每个强 agent node 的上下文视界、缓存计划、边界证据和 checkpoint，SkillFoundry 管需求交付。
- 所有 Skill 生成结果必须可测试、可验证、可追溯；owned LLM 调用可 replay，Codex SDK thread 内部过程只做边界记录。
- 自动化不是直接相信模型，而是给模型建立工程化闭环。
- Verifier 是主质量门，builder self-report 不是验收证据。
- MVP 不追求全自动万能平台，先追求一个可审计的高质量 Skill 构建闭环。
- Codex / OpenHuman 只作为思想参考，不复制其源码。

## 下一步

1. 继续把 `graph_v2.py` 收敛为唯一的 build / verify / repair / registry 产品主骨架；当前默认 Front Desk frozen job 已能通过 `/frontdesk/jobs/{job_id}/build` 进入 graph v2 verified build / registry happy path，registry gate 已是 canonical route 的首次批准点，failed verification route 也能执行 Goal Harness-backed repair 并重新进入 verifier / acceptance coverage / registry gate。
2. 完善 API/UI 对 v2 refs、ContextForge status、registry outcome、repair/human-review decision 的消费，保持不泄漏 raw prompt / raw payload。
3. 隔离或退役旧 `graph.py`、legacy prompt/context/worker 路径，把 v2 contract/graph/runtime 设为默认贡献入口。
4. 保持默认测试 deterministic/offline；真实 provider 和 Codex 只做 opt-in smoke。
5. 用 3-5 个真实 Codex Skill 需求做内部试运行，记录成本、轮数、成功率、repair 成功率、cache/prefix churn 和失败分类。
6. 在完成 auth、tenant、queue、audit、monitoring、deployment、secrets、incident response 之前，不对外宣称生产级平台。
