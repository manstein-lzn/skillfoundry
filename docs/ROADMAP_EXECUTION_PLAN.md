# SkillFoundry 分阶段执行 Roadmap

版本：v1.1
日期：2026-05-17
适用项目：基于 LangGraph + ContextForge 的 Codex Skill 工厂 MVP

> 状态说明：本文是 WP0-WP17 实施过程中的历史执行路线。WP15B、WP16、WP17 已在后续提交中完成，本文中 “next / blocking / blocked” 等状态不再代表当前待办。当前唯一执行源请看 `docs/DEVELOPMENT_ROADMAP.md`。

## 1. 一句话结论

SkillFoundry 的第一阶段路线是：

```text
LangGraph 管流程
+ ContextForge 管自有 LLM 调用上下文和证据账本
+ 文件即上下文 Workspace 协议
+ WorkerAdapter 管外部构建器边界
+ FakeWorker 先跑通离线闭环
+ CodexWorker 后试点
+ 独立 Verifier 做主质量门
+ Registry 保存 verified asset
```

核心判断：

- 可做；
- 不应该一开始自建完整 ActionRuntime；
- 不应该复制 Codex、OpenHuman 或 MetaLoop 源码；
- 可以借鉴它们的思想：文件上下文、长任务恢复、边界证据、独立验收、失败修复；
- ContextForge 只控制 SkillFoundry 自有 LLM 调用；
- Codex Worker 必须被当作外部黑盒 worker；
- Verifier 和 Registry 是信任边界。

## 2. 当前基线

截至 2026-05-17，仓库状态按工作包理解如下：

```text
WP0  Design baseline              已完成
WP1  Workspace + schema           已完成
WP2  LangGraph skeleton           已完成
WP3  WorkerAdapter + FakeWorker   已完成
WP4  Independent Verifier         已完成
WP5  ContextForge integration     已完成
WP6  Local Registry MVP           已完成
WP7  Offline E2E MVP              已完成
WP8  CodexWorker pilot            已完成
WP9  Minimal API/UI               已完成
WP10 QA Lab Expansion             已完成
WP11 Feedback + Versioning        已完成
WP12 Production Hardening         已完成
WP13 Front Desk Schema            已完成
WP14 Requirements Elicitor        已完成
WP15 Auditor + FreezeGate         部件级完成
WP15B Front Desk LangGraph Loop   下一步阻塞项
WP16 Acceptance Coverage Bridge   下一步
WP17 Real Builder Integration     WP15B-WP16 后试点
```

WP13 之后的详细路线已经转移到 `docs/FRONT_DESK_AGENT_ROADMAP.md`。独立审核结论见 `docs/FRONT_DESK_ROADMAP_AUDIT.md`。

后续执行必须保持这个边界：

- Builder 自报成功不是验收证据；
- 真实 Codex Worker 接入不得早于 WP7；
- Registry 只能接受 Verifier 通过的 package；
- LangGraph state 只保存轻量引用，不保存大日志、大 prompt、完整包或完整 transcript；
- 所有长文本和证据落在 workspace 文件中，并通过 hash 和 manifest 串起来。

## 3. ASCII 总表

```text
+------+----------------------------+--------------------------+-------------------------+--------------------------+----------------------------+
| WP   | Phase                      | Primary Output           | Core Gate               | Depends On               | Status                     |
+------+----------------------------+--------------------------+-------------------------+--------------------------+----------------------------+
| WP0  | Design Baseline            | whitepaper + docs        | boundaries explicit     | none                     | done                       |
| WP1  | Workspace + Schema         | job workspace + schema   | path/hash/schema tests  | WP0                      | done                       |
| WP2  | LangGraph Skeleton         | refs-only workflow       | resume/retry routing    | WP1                      | done                       |
| WP3  | WorkerAdapter              | FakeWorker + protocol    | report/diff/transcript  | WP1, WP2 partial         | done                       |
| WP4  | Independent Verifier       | verification gate        | no builder self-pass    | WP1, WP3                 | done                       |
| WP5  | ContextForge Integration   | context/evidence adapter | owned vs external split | WP1-WP4                  | done                       |
| WP6  | Local Registry MVP         | verified asset store     | hash/provenance gate    | WP1, WP4, WP5            | done                       |
| WP7  | Offline E2E MVP            | local full loop + report | build/verify/repair/reg | WP1-WP6                  | done                       |
| WP8  | CodexWorker Pilot          | real worker adapter      | sandbox + verifier gate | WP1-WP7                  | done                       |
| WP9  | Minimal API/UI             | internal product entry   | submit/view/download    | WP7, optional WP8        | done                       |
| WP10 | QA Lab Expansion           | richer evaluators        | fixture + judge quality | WP4, WP7                 | done                       |
| WP11 | Feedback + Versioning      | repair/version loop      | feedback creates jobs   | WP6-WP10                 | done                       |
| WP12 | Production Hardening       | ops/security/perf        | stable multi-job runs   | WP7-WP11                 | done                       |
| WP13 | Front Desk Schema          | schema/workspace         | deterministic tests     | WP1, WP5                 | done                       |
| WP14 | Requirements Elicitor      | elicitation node         | targeted questions      | WP13                     | done                       |
| WP15 | Auditor + FreezeGate       | audit + hard gate        | no premature build      | WP13-WP14                | component done             |
| WP15B| Front Desk Loop            | multi-round graph        | route/freeze/human      | WP15                     | next / blocking            |
| WP16 | Acceptance Coverage Bridge | QA/Verifier coverage     | criteria drive quality  | WP15B                    | next                       |
| WP17 | Real Builder Integration   | LLM/Codex builder pilot  | verified real output    | WP15B-WP16               | blocked                    |
+------+----------------------------+--------------------------+-------------------------+--------------------------+----------------------------+
```

## 4. 总体架构

```text
+----------------------------------------------------------------+
| Product/API Layer                                               |
| requirement intake, job view, report view, registry query       |
+----------------------------------------------------------------+
| LangGraph Orchestration Layer                                   |
| route, retry, checkpoint, repair loop, fail-closed, resume      |
+----------------------------------------------------------------+
| ContextForge Context and Evidence Layer                         |
| owned LLM context, prompt view, model record, boundary evidence |
+----------------------------------------------------------------+
| Workspace Protocol Layer                                        |
| locked specs, manifests, attempts, package, verifier outputs    |
+----------------------------------------------------------------+
| Worker Boundary Layer                                           |
| WorkerAdapter, FakeWorker, future CodexWorker                   |
+----------------------------------------------------------------+
| Quality and Asset Layer                                         |
| independent Verifier, Registry, quarantine, provenance          |
+----------------------------------------------------------------+
```

## 5. 执行总规则

每个阶段都必须遵守以下规则：

- 先写清楚该阶段的输入、输出、非目标和验收门；
- 实现由 worker/agent 完成时，必须给它明确 ownership；
- 架构师只验收，不让 builder 自己证明自己通过；
- 所有实现必须有测试；
- 任何阶段不允许通过删除前置安全检查来让测试通过；
- 每个阶段结束必须能回答：新增了什么能力、不能做什么、证据在哪里、如何复现；
- 涉及真实 Codex Worker、网络、大模型 provider、外部命令执行能力时，必须比 FakeWorker 阶段多一层边界证据和失败兜底；
- 任何生产化能力不能早于离线 E2E 闭环。

## 6. WP0：Design Baseline

目标：

- 冻结产品路线；
- 明确 SkillFoundry、LangGraph、ContextForge、WorkerAdapter、Verifier、Registry 的边界；
- 明确 Codex、OpenHuman、MetaLoop 只是思想参考，不搬源码；
- 明确第一阶段是 Codex Skill 工厂，不是通用万能 Agent 平台。

输入：

- 前期关于 Codex 上下文管理的讨论；
- OpenHuman 长任务运行机制的启发；
- MetaLoop 设计优先和独立验收思想；
- ContextForge v0.1 能力边界；
- Codex Skill 工厂产品目标。

主要任务：

- 写白皮书；
- 写架构文档；
- 写工作包文档；
- 写验收计划；
- 写 roadmap；
- 标明 owned LLM call 和 external worker invocation 的区别。

交付物：

- `README.md`
- `WHITEPAPER.md`
- `docs/ARCHITECTURE.md`
- `docs/WORK_PACKAGES.md`
- `docs/ACCEPTANCE_PLAN.md`
- `docs/ROADMAP.md`

验收门：

- 文档明确 ContextForge 不控制 Codex Worker 内部 prompt、tool loop、context compaction、cache 或 cost；
- 文档明确 Verifier 是主质量门；
- 文档明确真实 Codex Worker 集成前置条件；
- 文档明确 builder self-report 不是 acceptance evidence。

退出条件：

- 后续 WP1-WP12 可以按文档推进；
- 第三方 agent 不需要再猜测系统边界。

状态：已完成。

## 7. WP1：Workspace + Schema

目标：

- 建立文件即上下文的 job workspace；
- 定义核心数据结构；
- 实现 hash、manifest、locked input、attempt 和 resume 的基础能力；
- 实现路径 confinement。

输入：

- WP0 架构边界；
- workspace 标准目录；
- SkillSpec、BuildContract、VerificationSpec 等 schema 清单。

主要任务：

- 定义 schema；
- 初始化 job workspace；
- 生成 locked input；
- 生成 artifact manifest；
- 实现 canonical JSON hash；
- 实现 path resolver；
- 拒绝绝对路径、`..`、符号链接逃逸；
- 建立 resume brief 规则。

交付物：

- `src/skillfoundry/schema.py`
- `src/skillfoundry/security.py`
- `src/skillfoundry/workspace.py`
- `tests/test_schema.py`
- `tests/test_workspace.py`

验收门：

- schema 可 round-trip；
- hash 稳定；
- locked input 被修改后检查失败；
- artifact manifest 覆盖关键输入；
- path traversal 测试失败关闭；
- resume brief 不包含完整 transcript 或大日志。

退出条件：

- WP2、WP3、WP4 可以共享同一 workspace 和 schema。

状态：已完成。

## 8. WP2：LangGraph Skeleton

目标：

- 建立最小 LangGraph workflow；
- 明确 state 只保存轻量 refs；
- 支持 route、retry、repair、fail-closed、human review 和 resume。

输入：

- WP1 schema；
- route enum；
- job refs；
- attempt count 和 failure class。

主要任务：

- 定义 refs-only state；
- 定义 workflow graph；
- 实现 route 节点；
- 实现 build/verify/repair/register 的 stub 节点；
- 加入 checkpoint；
- 加入 attempt limit；
- 加入 resume smoke test。

交付物：

- `src/skillfoundry/graph.py`
- `tests/test_graph.py`

验收门：

- state 不保存 raw transcript、大 prompt、完整 package、大日志；
- route 覆盖 `build_new`、`reuse_existing`、`reject_unsafe`、`ask_clarifying_question`；
- attempt 超限进入 fail-closed 或 human review；
- checkpoint/resume 能跑通；
- graph 可以用 stub 完成流程。

退出条件：

- 后续 worker、verifier、registry 可以被接入 graph。

状态：已完成。

## 9. WP3：WorkerAdapter + FakeWorker

目标：

- 定义外部 worker 调用边界；
- 实现 FakeWorker；
- 为 CodexWorker 保留 adapter 形状；
- 统一 attempt artifact 输出协议。

输入：

- WP1 workspace；
- WP2 graph；
- WorkerInvocation schema。

主要任务：

- 定义 `BuildWorker` 协议；
- 实现 `WorkerAdapter.invoke(...)`；
- 实现 FakeWorker fixture；
- 生成 input manifest；
- 生成 execution report；
- 生成 output diff；
- 生成 worker transcript；
- 模拟失败、修复、缺 report、路径越权、timeout。

交付物：

- `src/skillfoundry/worker.py`
- `tests/test_worker.py`

验收门：

- worker 不能拿到无限制 workspace 写权限；
- 缺 execution report 不能被视为成功；
- path escape 必须失败；
- attempt artifact 路径固定；
- usage 不可得时要记录原因。

退出条件：

- FakeWorker 足以支撑 Verifier 和 offline E2E；
- 上层流程不依赖具体 worker 实现。

状态：已完成。

## 10. WP4：Independent Verifier

目标：

- 建立独立质量门；
- 防止 builder self-report 绕过验收；
- 输出机器可读 verifier 结果。

输入：

- WP1 workspace 和 schema；
- WP3 worker 输出；
- verification spec；
- package 结构要求。

主要任务：

- 检查 artifact manifest；
- 检查 locked input；
- 检查 execution report；
- 检查 package hash；
- 检查 `package/SKILL.md`；
- 检查 required sections；
- 检查 declared references/scripts；
- 检查 package path confinement；
- 加入 sandbox smoke placeholder；
- 支持 optional LLM judge，但不能作为唯一 gate。

交付物：

- `src/skillfoundry/verifier.py`
- `tests/test_verifier.py`

验收门：

- 缺 required section 必 fail；
- malformed frontmatter 必 fail；
- hash mismatch 必 fail；
- path traversal 必 fail；
- builder 自报 pass 但 verifier fail 时整体 fail；
- verifier result 可复现。

退出条件：

- Registry 可以把 Verifier pass 作为唯一注册前提。

状态：已完成。

## 11. WP5：ContextForge Integration

目标：

- 将 ContextForge 接入 SkillFoundry；
- owned LLM call 通过 ContextForge；
- external worker invocation 只作为边界证据记录；
- 治理 verifier log 后再进入 prompt。

输入：

- ContextForge 本地依赖；
- WP1 artifact refs；
- WP2 LLM node skeleton；
- WP3 worker boundary；
- WP4 verifier result。

主要任务：

- 实现 ContextForge adapter；
- 包装 owned LLM call；
- 写入 PromptView、ModelCallEnvelope、ModelCallRecord；
- 记录 worker boundary evidence；
- 区分 replayable owned call 和 non-replayable external worker internals；
- 记录 usage unavailable reason；
- 对 verifier log 做 ToolOutputGovernor 或等价治理。

交付物：

- `src/skillfoundry/context.py`
- `tests/test_context.py`
- `pyproject.toml` 中的 ContextForge 依赖。

验收门：

- owned LLM call 有 replay artifact；
- worker boundary 有 input/output/diff/transcript/hash refs；
- 不声称控制 Codex Worker 内部；
- raw verifier log 不直接进 prompt；
- metrics 区分 owned LLM usage 和 worker usage unavailable。

退出条件：

- 用户能审计一个 job 中哪些东西可 replay，哪些只是外部 worker 边界证据。

状态：已完成。

## 12. WP6：Local Registry MVP

目标：

- 保存 verified Skill asset；
- 保存 provenance 和 hash；
- 支持 approved、rejected、quarantined 状态；
- 支持复用候选查询。

输入：

- WP1 schema；
- WP4 verifier result；
- WP5 evidence refs；
- package hash。

主要任务：

- 实现 local JSON registry；
- 实现 add/get/list；
- 实现 duplicate policy；
- 实现 quarantine/reject；
- 实现 registry verify；
- 强制 verifier-passed package 才能注册；
- 保存 build job、worker invocation、input manifest、execution report、verification spec、verification result、artifact manifest。

交付物：

- `src/skillfoundry/registry.py`
- `tests/test_registry.py`

验收门：

- verifier fail 不能注册；
- hash mismatch 不能注册；
- registry entry 可追溯；
- quarantined entry 不作为默认复用候选；
- verifier evidence 必须包含 execution report ref；
- duplicate policy 明确。

退出条件：

- Offline E2E 可以把 verified package 注册成 approved asset。

状态：已完成。

## 13. WP7：Offline E2E MVP

目标：

- 用 FakeWorker 跑通本地完整闭环；
- 不依赖真实 Codex；
- 不依赖网络；
- 不依赖真实 provider；
- 产出 final report。

输入：

- WP1-WP6 全部实现；
- sample requirement；
- registry 路径；
- deterministic worker fixture。

主要任务：

- 实现 offline build flow；
- 实现 CLI 或等价命令入口；
- 实现 final report；
- 实现 repair loop；
- 实现 reuse route；
- 实现 unsafe reject；
- 实现 ambiguous requirement human-review placeholder；
- 实现 path traversal fixture；
- 实现 attempt limit fixture；
- 实现 resume。

交付物：

- `src/skillfoundry/offline.py`
- `src/skillfoundry/cli.py`
- `tests/test_offline.py`
- `examples/requirements/pytest_repair.md`
- `runs/<job_id>/final_report.json`

建议命令：

```bash
skillfoundry build --requirement examples/requirements/pytest_repair.md --output runs/demo-001
skillfoundry verify --job runs/demo-001
skillfoundry registry add --job runs/demo-001 --registry runs/registry.json
skillfoundry report --job runs/demo-001
```

验收门：

- `build_new` 正常构建；
- 第一轮故意失败后 repair 通过；
- verifier pass 后 registry approved；
- `reuse_existing` 能命中 approved entry；
- `reject_unsafe` 不构建、不注册；
- ambiguous requirement 进入 clarification 或 human review；
- path traversal 不注册；
- attempt limit exceeded 不注册；
- resume 通过 refs/artifacts 恢复；
- final report 包含 build contract、skill spec、worker input、attempts、latest execution report、verifier result、registry entry、artifact manifest、package hash、final status。

退出条件：

- 本地 demo 可以无网络完整运行；
- 任何人可以通过 CLI 复现一个 verified Skill package；
- WP8 可以开始真实 Codex Worker pilot。

状态：已完成。

## 14. WP8：CodexWorker Pilot

目标：

- 接入真实 Codex CLI/SDK 或可用 Codex Worker；
- 不改变 WorkerAdapter 上层协议；
- 验证真实 worker 在受限 workspace 中构建 Skill 的可行性。

输入：

- WP7 offline E2E 通过；
- Codex CLI/SDK 可用性确认；
- workspace 权限策略；
- timeout 策略；
- transcript capture 策略。

主要任务：

- 实现 CodexWorker adapter；
- 拼装 invocation command；
- 传入 worker input；
- 限制 writable paths；
- 捕获 transcript；
- 捕获 diff；
- 捕获 exit status；
- 捕获 duration；
- 记录 usage unavailable reason；
- 将输出交给 Verifier，不允许 worker 自批。

交付物：

- `CodexWorker` adapter；
- pilot fixture；
- integration test 或手工验收脚本；
- pilot report。

验收门：

- 能构建一个简单真实 Skill；
- 失败能进入 repair；
- 超时能 fail-closed；
- path escape 被拦截；
- Verifier 是最终 gate；
- Registry 只接受 verifier-passed package；
- 文档清楚说明 ContextForge 不 replay Codex Worker 内部过程。

退出条件：

- 真实 Codex Worker 可作为可选 builder；
- FakeWorker offline path 仍然稳定。

状态：已完成。

## 15. WP9：Minimal API/UI

目标：

- 提供内部用户可用入口；
- 用户能提交需求、查看 job、查看 report、下载 approved Skill。

输入：

- WP7 offline E2E；
- WP6 registry；
- 可选 WP8 CodexWorker。

主要任务：

- 实现 create job API；
- 实现 get/list job API；
- 实现 artifact download；
- 实现 registry query；
- 实现 minimal UI 或静态 report view；
- 实现 basic auth placeholder 或内部部署说明。

交付物：

- API entry；
- minimal UI 或 report page；
- job status view；
- artifact download path；
- registry list page。

验收门：

- 用户能提交需求；
- 用户能看到澄清、构建、验证、注册状态；
- 用户能查看 final report；
- 用户能下载 approved package；
- API 不暴露 workspace 外文件；
- UI 不把 verifier-failed package 展示为 approved。

退出条件：

- 第一个内部用户可以不接触命令行完成一次 Skill 工厂流程。

状态：已完成。

## 16. WP10：QA Lab Expansion

目标：

- 把 Verifier 从结构检查扩展到更像真实 QA；
- 增加更多 fixture、judge、回归样例和质量分数。

输入：

- WP4 Verifier；
- WP7 final report；
- 真实或模拟 Skill 需求样本。

主要任务：

- 增加 trigger/non-trigger cases；
- 增加输入输出契约测试；
- 增加脚本 smoke；
- 增加 LLM judge adapter；
- 增加 judge prompt governance；
- 增加 regression suite；
- 增加质量评分；
- 增加失败分类。

交付物：

- evaluator fixtures；
- judge adapter；
- quality report；
- regression cases；
- failure taxonomy。

验收门：

- 静态检查仍是硬 gate；
- LLM judge 不能单独放行；
- judge 输入经过 ContextForge 治理；
- bad Skill 能稳定 fail；
- good Skill 能稳定 pass；
- 失败分类能驱动 repair。

退出条件：

- Skill 质量评估不再只是“格式正确”，而开始覆盖“是否真的可用”。

状态：已完成。

## 17. WP11：Feedback + Versioning

目标：

- 把用户反馈变成 repair/version job；
- 让 Skill 资产可以长期维护；
- 支持版本、quarantine、rollback。

输入：

- WP6 Registry；
- WP9 用户入口；
- WP10 QA Lab。

主要任务：

- 定义 feedback record；
- 收集 failed usage case；
- 将反馈转成 repair job；
- 支持 skill version upgrade；
- 支持 registry quarantine；
- 支持 rollback；
- 支持 reviewer approval；
- 输出版本变更报告。

交付物：

- feedback schema；
- versioned registry entry；
- repair-from-feedback flow；
- quarantine/rollback flow；
- feedback report。

验收门：

- 反馈不能直接修改 approved package；
- 新版本仍需 Verifier 通过；
- provenance 保留旧版本和新版本关系；
- quarantine 后默认复用不再命中；
- rollback 有记录。

退出条件：

- SkillFoundry 从“一次性生成器”变成“可持续维护的能力资产系统”。

状态：已完成。

## 18. WP12：Production Hardening

目标：

- 将 MVP 强化到可小规模内部 beta 试用；
- 聚焦安全、性能、并发、观测和运维；
- 明确 Python/Rust 边界和 JSON registry 到数据库的后续迁移触发条件。

输入：

- WP7-WP11 的完整链路；
- 离线 E2E、CodexWorker pilot、API/UI、QA Lab、Feedback/Versioning 的工程事实；
- 内部 beta 前的稳定性、安全和运维要求。

主要任务：

- 多 job 并发；
- registry 并发写防护；
- workspace 清理策略；
- artifact retention 边界；
- 健康检查和 readiness report；
- local observability report；
- 成本和 usage 可得性说明；
- 安全检查清单；
- Python/Rust 边界评估；
- JSON registry 到 SQLite/数据库的方案评估。

交付物：

- `src/skillfoundry/ops.py`
- `tests/test_ops.py`
- `docs/OPERATIONS.md`
- `docs/SECURITY_CHECKLIST.md`
- `docs/PRODUCTION_READINESS.md`
- registry 本地文件锁和原子写入强化；
- CLI ops 命令：`health`、`observability`、`cleanup`。

验收门：

- 多 job 不互相污染 workspace；
- registry 不出现并发写损坏；
- artifact 可清理但 provenance 不断；
- 健康检查输出机器可读结果；
- 失败、耗时、QA、Verifier、Registry、Feedback/Versioning 状态可观测；
- usage/cost 不可得时明确记录不可得原因；
- 高性能内核迁移点明确；
- 默认测试保持确定性、离线、无外部 provider 依赖。

退出条件：

- 可以进入受控内部 beta；
- 可以基于真实试用数据决定继续 Python 主体、引入 Rust 内核，或局部迁移到 SQLite/数据库；
- 不宣称完整生产级平台已经完成。

状态：已完成。

## 19. 阶段依赖图

```text
WP0
  -> WP1
      -> WP2
      -> WP3
          -> WP4
              -> WP6
      -> WP5
          -> WP6
  -> WP7
      -> WP8
      -> WP9
          -> WP11
      -> WP10
          -> WP11
              -> WP12
```

更准确地说：

- WP7 必须等待 WP1-WP6；
- WP8 必须等待 WP7；
- WP9 可以不等待 WP8，但真实 worker 能力依赖 WP8；
- WP10 可与 WP9 部分并行；
- WP11 需要 Registry、API/UI 和 QA Lab；
- WP12 只能在完整闭环跑过之后做，否则容易过早工程化。

## 20. 第一阶段成功标准

第一阶段不是“写出一个 Agent demo”，而是满足以下标准：

- 一个自然语言需求能变成结构化 SkillSpec；
- 构建过程被 workspace、manifest、hash 和 refs 约束；
- worker 可以失败，可以修复，但不能自证成功；
- verifier 独立验收；
- registry 只保存 verified package；
- final report 能解释这个 Skill 为什么被接受或拒绝；
- offline E2E 不依赖外部网络也能跑通；
- 真实 Codex Worker 接入后仍不破坏上述边界。

## 21. 不做清单

第一阶段明确不做：

- 不做通用 Agent 操作系统；
- 不做完整 ActionRuntime；
- 不做全自动无监督生产发布；
- 不复制 Codex 源码；
- 不复制 OpenHuman 源码；
- 不复制 MetaLoop 框架；
- 不让 ContextForge 冒充 Codex Worker 内部上下文控制器；
- 不让 LLM judge 成为唯一质量门；
- 不把未验证的 package 放入 approved registry；
- 不提前做复杂 marketplace。

## 22. 推荐下一步

WP0-WP12 已经形成第一阶段闭环。下一步不是继续堆功能，而是进入受控内部 beta，用真实需求验证这套 Codex Skill 工厂是否能稳定交付。

```text
Internal Beta:
select real skill needs
-> run health + tests
-> batch build
-> inspect observability
-> collect feedback
-> repair/version/quarantine
-> decide Python/Rust/SQLite next move
```

内部 beta 的目标不是证明“完整生产级平台完成”，而是收集足够运行证据，判断下一阶段应该优先补哪一类工程能力：真实 worker 调度、权限和审计、SQLite/数据库注册表、Rust 安全/性能内核、部署监控，或更强的 QA/评估体系。

## 23. 内部 Beta 执行表

```text
+------+--------------------------+--------------------------------------+------------------------------+------------------------------+
| Step | Action                   | Evidence                             | Pass Gate                    | Owner                        |
+------+--------------------------+--------------------------------------+------------------------------+------------------------------+
| B1   | Select 3-5 real needs    | requirement docs                     | scope clear and reviewable   | product/architect            |
| B2   | Preflight                | pytest + ops health JSON             | all tests pass, ready=true   | operator                     |
| B3   | Batch build              | runs/<job>/final_report.json         | registered/reused or explained| builder workflow             |
| B4   | Quality review           | verifier + QA reports                | no self-report acceptance    | verifier/reviewer            |
| B5   | Observability review     | ops observability JSON               | failures/durations visible   | operator/architect           |
| B6   | User feedback            | feedback records                     | actionable repair/version job| user/product                 |
| B7   | Asset governance         | registry provenance/quarantine/rollback| approved assets traceable  | reviewer/operator            |
| B8   | Architecture decision    | beta summary                         | next investment explicit     | architect                    |
+------+--------------------------+--------------------------------------+------------------------------+------------------------------+
```
