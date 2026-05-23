# SkillFoundry Handoff

更新日期：2026-05-23

## 当前状态

当前主线已经从 v0 Front Desk / worker / graph 原型，推进到 ContextForge Goal Harness v2 骨架的混合迁移阶段。

重要更新：SkillFoundry 目前没有线上用户、外部兼容性承诺或生产数据迁移负担。后续可以基于新版 ContextForge Goal Harness 重新设计技术实现；旧 WP0-WP17 代码和文档是 v0 原型与知识资产，不是 v2 技术约束。v2 当前集成蓝图是 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`，阶段实现计划和历史执行证据见 `docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md`，前提说明见 `docs/SKILLFOUNDRY_V2_BASELINE.md`。

ForgeUnit 方向已经进入第一层代码接入：`src/skillfoundry/forgeunit_adapter.py`
可以把 `JobWorkspace` 物化为 ForgeUnit task pack，并通过 ForgeUnit v1.2.1
的 public `ForgeUnitNode("codex_exec")` 生成 refs-only v2 state。当前有
两条 dedicated pilot graph：dry-run 路径会停在 human review；离线
command-bridge 路径会用显式本地命令模拟 Codex exec，写入 ForgeUnit
evidence，再桥接成 SkillFoundry `attempts/001` 证据，最终通过
`Verifier` 和 `LocalSkillRegistry`。如果 workspace 包含 root
`acceptance_criteria.yaml`，ForgeUnit registry gate 会先写
`qa/acceptance_coverage_plan.json` 和 `qa/acceptance_coverage_result.json`，再进入
registry approval。`POST /frontdesk/jobs/{job_id}/build` 当前默认进入
`forgeunit_skillfoundry_vnext`；旧 `graph_v2_goal_harness` 只能通过请求体
`{"build_mode": "graph_v2"}` 显式调用。设计说明见
`docs/FORGEUNIT_PRODUCT_ADAPTER_SLICE.md`。真实 Codex exec 的手动 pilot
入口是 `scripts/run_forgeunit_real_codex_exec_pilot.py`，说明见
`docs/FORGEUNIT_REAL_CODEX_EXEC_PILOT.md`；该路径不进入默认 CI。
FrontDesk vNext build 现在也有部署配置面：constructor 参数
`forgeunit_command` / `forgeunit_repair_command` 或环境变量
`SKILLFOUNDRY_FORGEUNIT_COMMAND` / `SKILLFOUNDRY_FORGEUNIT_REPAIR_COMMAND`
可以提供真实 ForgeUnit/Codex command boundary；请求体里的 `command` 仍可覆盖。
没有配置时默认走 deterministic fake happy，因此默认测试仍完全离线。vNext worker
失败时 API 返回 redacted `frontdesk_build_failed`，不回显底层 exception、command
string、stdout/stderr 或 transcript marker。FrontDesk API 手动接入真实 command
boundary 的操作协议见 `docs/FRONTDESK_FORGEUNIT_COMMAND_PILOT_RUNBOOK.md`；
其中的 preflight 包括实际本地失败 subprocess redaction smoke，但不调用 live Codex。
本地成功 preflight 入口是 `scripts/run_frontdesk_forgeunit_command_pilot.py`，它通过
FrontDesk API create/approve/build/contextforge 全流程运行 deterministic subprocess
并输出 refs-only summary。
Phase 8D 已完成一次显式 manual live `codex exec` pilot：同一 FrontDesk API 入口
通过 `scripts/forgeunit_codex_exec_worker.py` 调用
`codex exec --sandbox workspace-write --skip-git-repo-check -`，产出
`package/SKILL.md`、`evidence/transcript.md`、`evidence/manifest.json`，随后通过
Verifier 和 LocalSkillRegistry，最终 refs-only summary 为 `status=registered`。
Phase 9E 已完成两场景 live semantic eval：`pytest-failure-analyzer` 和
`repository-handoff` 均通过 live Codex command boundary、Verifier 和 Registry，
并且 package/source semantic markers 全部命中。ForgeUnit 现在以 Git tag
`v1.2.1` 接入 SkillFoundry，不再依赖本机 sibling `../ForgeUnit`。Phase 10 的
fresh clone gate 文档和脚本位于 `docs/FRESH_CLONE_GATE.md` 与
`scripts/check_fresh_clone_readiness.py`；live semantic eval 手动门槛位于
`docs/FRONTDESK_LIVE_SEMANTIC_EVAL.md`。Phase 11 新增默认开发入口：
`Makefile` 和 `scripts/dev_check.sh`，常用命令为 `make focused`、`make test`、
`make fresh-clone-smoke` 和 `make live-semantic-eval-help`；说明见
`docs/DEVELOPMENT_WORKFLOW.md`。

核心行为现在是：

```text
Core Need Discovery
  -> Solution Planning
  -> User Review Gate
  -> Deterministic Freeze
  -> Build / Verify / QA / Registry
```

用户不再被无限追问技术细节。Front Desk 会先理解痛点、使用场景、目标用户、期望结果和成功信号；随后由 Agent 生成方案文档，用户确认或要求修改。只有用户批准过的方案才能进入 deterministic freeze。

当前不能说“v2 重构已经完成”。更准确的状态是：

```text
ContextForge contract bridge 已存在。
Offline Goal Harness build path 已存在。
workers_v2 / graph_v2 / verification bridge / registry evidence gate 已存在。
Front Desk v2 Goal Harness slices 已存在。
graph v2 failed verification -> Goal Harness repair -> verifier / acceptance coverage / ContextForge bridge / registry gate 闭环已存在。
canonical graph v2 route 中首次 registry approval 已收敛到 registry gate；direct verified runtime helper 的自动注册只作为 compatibility 行为保留。
产品主路径还需要继续收敛到这套 v2 骨架，human-review 已有 request / decision artifact 和 API decision endpoint，`GET /jobs/{job_id}` 已有 refs-only HTML evidence 页面；后续重点是 legacy 最终退役、worker/cache 边界硬化，以及 internal pilot 前的人审运营体验打磨。
```

## 最近完成的关键改动

- ContextForge 已作为 Git submodule 接入：`third_party/contextforge`。
- `pyproject.toml` 通过 editable path source 使用 `contextforge==0.1.0`，默认 `uv` index 设置为清华源。
- `pyproject.toml` 的 `forgeunit` extra 已固定到
  `git+ssh://git@github.com/manstein-lzn/forgeunit.git@v1.2.1`，用于 fresh clone
  安装；本地 sibling path source 已移除。
- `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 已创建；初版曾由独立 `gpt-5.5 xhigh` reviewer 审查为 `approved_with_residual_risks`、无 blocking findings。当前入口文档 reviewer 记录以该文档末尾和最新 MetaLoop review 为准。
- `src/skillfoundry/forgeunit_adapter.py` 已创建第一层 ForgeUnit 产品适配：
  `JobWorkspace -> task.yaml -> ForgeUnitNode("codex_exec") -> refs-only v2 state`。
  dry-run 会停在 human review；离线 command-bridge 可以继续进入
  SkillFoundry verifier 和 registry gate；registry 前会在需要时补齐
  acceptance coverage evidence。
- `src/forgeunit_skillfoundry/adapters/` 已新增 vNext 路由层：
  `run_existing_workspace_skill_factory(...)` 复用已有 locked `JobWorkspace`，
  `run_frozen_frontdesk_skill_factory(...)` 校验 FrontDesk `frozen +
  route_to_build` 和 freeze manifest/hash 后进入同一条 vNext graph。
- `src/skillfoundry/api.py` 已把 FrontDesk frozen build 默认切到
  ForgeUnit SkillFoundry vNext。响应返回
  `forgeunit_skillfoundry_summary/product_state/graph_state` refs 和 summary；
  legacy graph v2 只保留显式 `build_mode=graph_v2`。
  FrontDesk vNext build 的 worker command 选择顺序为：payload `fake_mode` /
  payload `command` / constructor 配置 / environment 配置 / deterministic fake happy。
  command string 不返回到 API JSON，也不进入 vNext summary/product/graph read model；
  build failure API error 也保持 redacted。
- v2 核心桥接模块已经存在：
  - `src/skillfoundry/contracts.py`
  - `src/skillfoundry/goal_runtime.py`
  - `src/skillfoundry/workers_v2.py`
  - `src/skillfoundry/graph_v2.py`
  - `src/skillfoundry/frontdesk_v2.py`
  - `src/skillfoundry/frontdesk_goal_runtime.py`
  - `src/skillfoundry/verification_bridge.py`
- Front Desk schema 增加：
  - `CoreNeedBrief`
  - `CoreNeedDiscoveryReport`
  - `CoreNeedQuestion`
  - `SolutionPlan`
  - `PlanReviewRecord`
  - `FrontDeskState.frontdesk_phase`
  - `FrontDeskState.core_need_brief_ref`
  - `FrontDeskState.solution_plan_ref`
  - `FrontDeskState.latest_plan_review_ref`
  - `FrontDeskState.core_need_round`
  - `FrontDeskState.plan_revision_count`
- `FrontDeskLoop` 在 `ready_for_audit` 后先生成：
  - `frontdesk/core_need_brief.json`
  - `frontdesk/core_need_report_*.json`
  - `frontdesk/decision_ledger.json`
  - `frontdesk/solution_plan.json`
  - `frontdesk/solution_plan.md`
  - `frontdesk/draft_skill_spec.yaml`
  - `frontdesk/acceptance_criteria.yaml`
- `POST /frontdesk/jobs/<id>/plan-review` 支持：
  - `approve`
  - `request_revision`
  - `reject`
  - `human_review`
- `request_revision` 会写入新的 user turn，并触发下一轮方案修订；超过 `max_plan_revision_rounds` 会持久化为 `human_review_required`。
- `FrontDeskFreezeGate` 现在要求 approved plan review 和 source hash 匹配，否则不能 freeze。
- Freeze manifest hash 现在覆盖 risk/budget/plan review 证据：
  - `frontdesk/budget.json`
  - `frontdesk/risk_report.json`
  - `frontdesk/core_need_brief.json`
  - `frontdesk/solution_plan.json`
  - `frontdesk/solution_plan.md`
  - `frontdesk/plan_review_*.json`
- Manual-only acceptance 不再只靠 `manual_authority`，必须有 `qa/manual_acceptance_record.json`；Registry 会复验该 artifact 的 hash、decision 和 covered criterion ids。
- Server-rendered HTML 的 Front Desk submit script 现在序列化完整 `FormData`，plan-review UI 在启用 JS 时也能提交 `decision` / `reason`。

## 关键代码入口

- `src/skillfoundry/frontdesk_schema.py`
  - Front Desk schema、状态字段、阶段/动作枚举。
- `src/skillfoundry/frontdesk_loop.py`
  - 需求澄清主循环。
  - 核心需求和方案文档物化。
  - 用户批准后 audit/freeze。
- `src/skillfoundry/frontdesk.py`
  - `RequirementsElicitor`
  - `SpecAuditor`
  - `FrontDeskFreezeGate`
  - no-freeze-without-approved-plan、risk/privacy/budget gate。
- `src/skillfoundry/api.py`
  - `/frontdesk/jobs`
  - `/frontdesk/jobs/<id>/messages`
  - `/frontdesk/jobs/<id>/plan-review`
  - `/frontdesk/jobs/<id>/core-need`
  - `/frontdesk/jobs/<id>/solution-plan`
  - server-rendered HTML UI。
- `src/skillfoundry/acceptance.py`
  - acceptance coverage 和 manual-only artifact gate。
- `src/skillfoundry/registry.py`
  - Registry provenance gate 和 manual acceptance record revalidation。
- `src/skillfoundry/contracts.py`
  - SkillFoundry frozen artifacts 到 ContextForge contracts 的 bridge。
- `src/skillfoundry/goal_runtime.py`
  - Offline Goal Harness build runtime。
  - Goal Harness repair evidence runtime。
- `src/skillfoundry/workers_v2.py`
  - Fake / owned LLM / Codex thread boundary / external agent worker。
- `src/skillfoundry/graph_v2.py`
  - refs-only LangGraph v2 spine。
  - verified build/registry happy path 和 failed verification repair re-verification/registry loop。
- `src/skillfoundry/frontdesk_goal_runtime.py`
  - Core Need、Solution Planner、Spec Auditor 的 Goal Harness runtime slices。
- `src/skillfoundry/verification_bridge.py`
  - SkillFoundry verifier / acceptance coverage 到 ContextForge VerificationResult 的桥接。
- `src/skillfoundry/forgeunit_adapter.py`
  - SkillFoundry `JobWorkspace` 到 ForgeUnit task pack 的薄转换层。
  - ForgeUnit codex exec dry-run v2 node，默认不调用 live Codex。
  - Dedicated pilot graph runner，dry-run 时停在 human review，不注册、不写 final report。
  - Offline command-bridge pilot runner，使用本地假命令写
    `package/SKILL.md`、ForgeUnit evidence 和 `attempts/001` evidence，再由
    `Verifier` 与 `LocalSkillRegistry` 决定通过和注册。
- `scripts/forgeunit_codex_exec_worker.py`
  - ForgeUnit `codex_exec` 的手动真实 Codex wrapper，负责调用显式
    Codex-compatible command、验证 package/evidence、补齐最小
    `worker_result.json`，并输出不含 raw prompt/stdout/stderr 的诊断。
  - Phase 8D 已通过一次 FrontDesk API live Codex exec pilot；公共 summary/product
    read model 扫描未发现 wrapper script 名、live command flags、ForgeUnit worker
    env 名或 raw FrontDesk message。
- `scripts/run_forgeunit_real_codex_exec_pilot.py`
  - 手动 integration runner；默认不进 pytest / CI，可通过 `--codex-command`
    或 `FORGEUNIT_CODEX_COMMAND` 指向真实 `codex exec`。

## 关键文档

- `README.md`
  - 项目入口、开发环境、submodule 初始化方式。
- `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`
  - v2 当前集成蓝图：解释 ContextForge / LangGraph / worker / verifier / registry 边界，列出 Phase 0-9 迁移计划和验收门。
- `docs/SKILLFOUNDRY_V2_BASELINE.md`
  - v2 重建基线：保留 SkillFoundry agent 协作思想，围绕新版 ContextForge Goal Harness 重建技术骨架。
- `docs/CONTEXTFORGE_GOAL_HARNESS_REBUILD_PLAN.md`
  - v2 阶段实现计划和历史执行证据，已合入第三方 `gpt-5.5 xhigh` reviewer 审查意见。
- `docs/CONTEXTFORGE_AGENT_EXOSKELETON_PRODUCT_VISION.md`
  - SkillFoundry 作为 ContextForge Agent Exoskeleton Runtime 第一个产品化应用的长期愿景。
- `docs/FORGEUNIT_PRODUCT_ADAPTER_SLICE.md`
  - SkillFoundry 接入 ForgeUnit v1.2 public API / LangGraph adapter 的第一层代码切片。
  - 当前包含三条 pilot：dry-run 停 human review、offline command bridge
    verifier/registry success path、以及最小 repair pilot（`001` verifier fail
    -> refs-only repair packet -> `002` verifier pass -> registry）。
- `docs/FORGEUNIT_SKILLFOUNDRY_COMPOSITION.md`
  - 新版 SkillFoundry-on-ForgeUnit clean composition layer。代码入口位于
    `src/forgeunit_skillfoundry/`，它复用旧 `skillfoundry` 包里的 workspace /
    verifier / registry / ForgeUnit adapter，不在 legacy product tree 里继续拼接。
  - Phase 1 已拆出 `config.py`、`engine.py`、`state.py`、`product.py` 边界；
    Phase 2 已新增 `graph.py`，提供
    `prepare_workspace -> run_forgeunit_engine -> verify_product_state ->
    emit_product_report` 的薄 LangGraph 产品骨架。
  - Phase 3 已新增 `scripts/run_forgeunit_skill_factory.py`，可以从命令行运行
    happy path、repair path 或显式 command bridge，并输出 refs-only JSON 摘要。
  - Phase 4 已新增 `report.py`，统一写
    `contextforge/forgeunit_skillfoundry_summary.json`；CLI stdout 直接打印这份
    summary，后续 API/UI/reviewer 也应优先消费它。
  - Phase 5 已新增 `adapters/workspace.py` 与 `adapters/frontdesk.py`，允许
    已有 `JobWorkspace` 和 FrontDesk frozen job 进入 vNext，同时保持
    summary/product/graph state refs-only。
  - Phase 6 已完成 API 接线：`POST /frontdesk/jobs/{job_id}/build` 默认运行
    ForgeUnit SkillFoundry vNext；FrontDesk raw conversation 的排除证据由
    ForgeUnit adapter 在 verifier 前写入 ContextForge ledger/state。
- `docs/FRONTDESK_FORGEUNIT_COMMAND_PILOT_RUNBOOK.md`
  - Phase 8B 的 FrontDesk API command boundary 手动试运行协议：部署配置、
    worker 输出协议、redaction 检查、成功/停止条件，以及真实 Codex 之前必须通过的
    本地失败 subprocess smoke。
- `scripts/run_frontdesk_forgeunit_command_pilot.py`
  - Phase 8C 的本地成功 command-boundary preflight：使用 deterministic local
    subprocess 通过 FrontDesk API 入口完成 vNext build / verify / registry，并只打印
    refs-only pilot summary。
  - Phase 8D 用显式 `--command` 复用该脚本跑通 live `codex exec`：结果为
    `status=registered`、`verification_passed=true`、`registry_approved=true`、
    `command_string_included=false`。证据见
    `.metaloop/phase8d_live_codex_pilot_summary.json` 和
    `.local/frontdesk_live_codex_pilot_runs/frontdesk-live-codex-pilot-001/`。
- `scripts/run_frontdesk_live_codex_eval.py`
  - Phase 9 的手动 scenario eval harness：可用内置 5 个场景或 JSON scenario
    file，逐个通过 FrontDesk API -> ForgeUnit SkillFoundry vNext command boundary
    -> Verifier -> Registry，并输出 refs-only `eval_summary.json`。
  - 默认不会调用 live Codex；必须显式 `--command`，或用 `--fake-mode happy` 跑离线
    smoke。summary 不包含 command string、raw FrontDesk message、raw worker input、
    raw transcript、stdout/stderr、package body 或 worker script path。
  - Phase 9E 已加入 semantic fidelity 统计，要求不同场景在 frozen inputs 和 live
    package 中命中各自 markers，并通过 `unique_registry_skill_ids` 防止 package
    identity 扁平化。
- `scripts/check_fresh_clone_readiness.py`
  - Phase 10 的新用户可复现 gate：临时 clone、初始化 submodule、创建新 venv、
    安装 `.[test,forgeunit]`，运行 focused harness test 和 fake-mode semantic smoke，
    并把 refs-only summary 复制到指定 evidence path。
- `scripts/dev_check.sh` 和 `Makefile`
  - Phase 11 的默认开发命令入口。`make focused` 跑 FrontDesk/ForgeUnit 关键离线
    测试，`make test` 跑全量 pytest，`make fresh-clone-smoke` 跑 fresh clone 离线
    smoke，`make live-semantic-eval-help` 只打印手动 runbook 提示，不调用 Codex。
- `docs/DEVELOPMENT_WORKFLOW.md`
  - 新用户和后续 agent 的本地验证命令说明。
- `docs/DEVELOPMENT_ROADMAP.md`
  - v0/WP0-WP17 能力基线和产品经验输入；不再约束 v2 模块边界。
- `docs/FRONT_DESK_CORE_NEED_REFACTOR.md`
  - Front Desk 需求澄清层重构路线和当前落地状态。
- `docs/FRONT_DESK_ROADMAP_AUDIT.md`
  - 历史独立审核，说明 WP15/WP16/风险门背景。

## 验证结果

代码实现切片需要继续使用全量验证：

```bash
make test
```

若本机未安装 `uv`，但 checkout 已经包含可用 `.venv`，可用等价本地验证：

```bash
scripts/dev_check.sh full
```

当前 MetaLoop 状态请以本地命令为准：

```bash
python3 /home/mansteinl/.codex/skills/metaloop/scripts/metaloop_kernel.py --workspace . status
```

`docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 的初版独立 reviewer 结论是 `approved_with_residual_risks`、无 blocker；后续入口文档复审记录以该文档末尾和最新 MetaLoop review 为准。代码切片仍需按对应 focused tests 和全量测试重新验证。

## 接手后建议先做

1. 确认本地依赖和 submodule：

```bash
git submodule update --init --recursive
make focused
make test
```

没有 `uv` 时可先用：

```bash
.venv/bin/python -m pytest -q
```

2. 若要继续 v2 重建，先读 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`。当前默认 Front Desk frozen job 已能通过 API build endpoint 进入 ForgeUnit SkillFoundry vNext build / verify / acceptance coverage / registry happy path：

- `POST /frontdesk/jobs/{job_id}/build` 只接受 approved/frozen Front Desk jobs。
- endpoint 默认调用 `forgeunit_skillfoundry` clean composition layer，经 ForgeUnit command boundary、SkillFoundry verifier、acceptance coverage、ContextForge bridge 和 registry gate 产出 `final_report.json`、registry decision 和 entry snapshot。
- endpoint 可通过 constructor 配置 `forgeunit_command` / `forgeunit_repair_command`，或环境变量 `SKILLFOUNDRY_FORGEUNIT_COMMAND` / `SKILLFOUNDRY_FORGEUNIT_REPAIR_COMMAND` 接入部署侧真实 ForgeUnit/Codex command boundary；payload `command` / `repair_command` 可以单次覆盖，payload `fake_mode` 可以强制离线 fake。
- 没有配置 command 时默认 deterministic fake happy；默认 pytest 不调用 live Codex，API 和 persisted vNext read models 不输出 command string。
- 旧 `graph_v2_goal_harness` 仍可通过 `{"build_mode": "graph_v2"}` 显式调用；它是 compatibility path，不再是 FrontDesk frozen build 默认路径。
- graph v2 compatibility route 仍可调用 verified Goal Harness build、SkillFoundry verifier、acceptance coverage、ContextForge verification bridge 和 registry gate；其中 verified runtime 只产出 candidate + evidence，registry gate 执行首次 `LocalSkillRegistry.add_verified()`、`final_report.json`、registry decision 和 entry snapshot。
- failed verification route 可以进入 Goal Harness-backed repair node，记录 governed verifier-failure context、WorkerRun、ContextView、PromptCachePlan、checkpoint、repair instructions、repair runtime result 和 `RepairAttempt`；repair 后会重新进入 SkillFoundry verifier、acceptance coverage、ContextForge verification bridge 和 registry gate。repair worker self-report 仍不是验收或注册依据。
- ForgeUnit adapter repair pilot 现在也具备一条 deterministic/offline 薄切片：
  `run_forgeunit_repair_pilot_graph(...)` 通过两个显式 command bridge 命令复现
  `attempts/001` verifier 失败、`contextforge/forgeunit_repair_packet.json`、
  `attempts/002` verifier 通过和 registry 注册。它不是 scheduler/daemon/长期
  repair policy，默认不调用 live Codex。
- 新增 `src/forgeunit_skillfoundry/` clean composition layer：
  `prepare_skill_factory_workspace(...)` 准备或复用 locked `JobWorkspace`，
  `run_skill_factory_graph(...)` 运行薄 LangGraph 产品骨架，
  `run_codex_skill_factory(...)` 作为产品 convenience entry 走 graph path。
  它通过 explicit command bridge 运行 happy path 或 repair path，并写
  `contextforge/forgeunit_skillfoundry_product_state.json` 和
  `contextforge/forgeunit_skillfoundry_graph_state.json`。focused tests 覆盖 config
  validation、refs-only product/graph state selection、offline happy-path
  registration 和 repair-path registration。
- 新增 `scripts/run_forgeunit_skill_factory.py`：
  支持 `--fake-mode happy|repair` 离线 smoke，也支持显式
  `--command/--repair-command`。stdout 直接输出
  `contextforge/forgeunit_skillfoundry_summary.json`，其中只有
  job/status/verification/registry/attempt/refs 摘要，不输出 command string、raw
  prompt、raw transcript、package body 或 worker_input 内容。
- Phase 8D 已实际跑通一次显式 live Codex exec pilot，命令经
  `scripts/forgeunit_codex_exec_worker.py` 调用
  `codex exec --sandbox workspace-write --skip-git-repo-check -`。结果同样为
  `status=registered`、`verification_passed=true`、`registry_approved=true`、
  `command_string_included=false`；live Codex 仍只作为 opt-in smoke，不进入默认
  tests/CI。
- graph v2 final state 持久化到 `contextforge/graph_v2_state.json`，仍是 refs/IDs/status-only。
- `GET /jobs/{job_id}/contextforge` 会暴露 build path、verified runtime、graph v2 state、repair evidence、human-review、verification 和 registry summary，不暴露 raw prompt / raw payload / raw conversation / transcript / package content。
- `GET /jobs/{job_id}` 在 `Accept: text/html` 下会渲染 refs-only job evidence 页面，展示 build path、graph v2、verification、registry、repair、human-review、cache、worker、usage 和 artifact refs 摘要，不内联 raw evidence。
- 旧 `POST /jobs` 离线 builder 现在默认返回 `legacy_offline_jobs_disabled`，只在显式 constructor flag、`SKILLFOUNDRY_ALLOW_LEGACY_OFFLINE_JOBS=1` 或 `skillfoundry serve --allow-legacy-offline-jobs` 下作为 compatibility route 可用；默认首页不再展示 legacy `/jobs` form。
- 相关 focused gates：`tests/test_frontdesk_api.py tests/test_api.py tests/test_graph_v2_runtime.py tests/test_graph_v2.py tests/test_goal_harness_verified_runtime.py tests/test_verification_bridge.py tests/test_registry.py tests/test_acceptance_coverage.py` 和全量 pytest。

3. 后续继续 vNext 收敛：

- 让 `graph_v2.py` 成为唯一产品 build / verify / repair / registry 主骨架，旧 `graph.py` 退役或隔离为 compatibility wrapper；registry timing 已在 canonical route 中收敛，后续重点是清掉旁路和旧入口歧义。
- 继续完善 API/UI 的 registry outcome、repair/human-review decision 和 evidence 摘要。
- 隔离或退役 legacy prompt/context/worker 路径，把 v2 contract/graph/runtime 设为默认贡献入口。
- 真实 provider / Codex SDK thread 只做 opt-in pilot，不进入默认测试。

4. 不要回退以下约束：

- `FrontDeskState` 必须 refs-only，不保存 raw conversation、raw prompt、raw model output。
- Builder 不得读取 raw Front Desk conversation。
- 没有 approved plan review 不得 freeze。
- risk/privacy/budget/manual acceptance 证据必须进入 deterministic gate 或 Registry gate。
- 默认测试路径必须保持 fake/scripted/offline，不依赖 live provider。
- Worker self-report is never acceptance。
- ContextForge 不控制 Codex SDK thread 内部 prompt/cache/tool loop，只记录边界证据。

## Git 注意事项

当前变更包含 submodule：

```text
.gitmodules
third_party/contextforge
```

克隆或切换机器时请使用：

```bash
git clone --recurse-submodules <repo>
```

或者在已有 checkout 中运行：

```bash
git submodule update --init --recursive
```
