# SkillFoundry Work Packages v0.2

## 总体顺序

第一阶段采用保守实现序列：

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

核心依赖：

- WP8 真实 CodexWorker pilot 必须等待 WP1-WP7；
- WP6 Registry 只能信任 WP4 Verifier；
- WP5 ContextForge integration 不能声称控制 Codex Worker 内部；
- 所有 implementation WP 都必须遵守 WP0 文档边界。

## WP0：Docs v0.2

目标：

- 将产品路线冻结为外部 worker 监督型工厂；
- 明确 owned LLM call 与 external worker invocation 的区别；
- 明确 ContextForge 只控制自有 LLM 调用，并记录 worker 边界证据；
- 明确 Verifier 是主质量门；
- 明确真实 Codex Worker 集成前置条件。

Owns：

- `WHITEPAPER.md`；
- `docs/ARCHITECTURE.md`；
- `docs/WORK_PACKAGES.md`；
- `docs/ACCEPTANCE_PLAN.md`；
- 必要时更新 `README.md` 和 `docs/ROADMAP.md` 术语。

Non-goals：

- 不实现产品代码；
- 不接真实 Codex Worker；
- 不复制 MetaLoop 实现细节或 `.metaloop/` 布局；
- 不声称 ContextForge 控制 Codex Worker 内部 prompt、tool loop、compaction、cache 或 cost。

Acceptance criteria：

- 白皮书包含 conditional-go 路线；
- 架构文档包含 WorkerAdapter、workspace protocol、Verifier gate、Registry trust model；
- 工作包文档包含 WP0-WP10；
- 验收计划包含 schema、LangGraph、WorkerAdapter、Verifier、ContextForge、Registry、E2E 和 security gate；
- 文档明确 builder self-report 不是验收证据；
- 轻量 grep 检查通过。

Dependencies：

- 无。WP0 是后续所有 WP 的设计基线。

## WP1：Workspace + Schema

目标：

- 定义 job workspace 文件协议；
- 定义核心 schema；
- 定义 hash、锁定输入、attempt 和 resume 规则；
- 实现路径 confinement 基础能力。

Owns：

- `SkillSpec`；
- `BuildContract`；
- `VerificationSpec`；
- `WorkerInvocation`；
- `ExecutionReport`；
- `VerificationResult`；
- `RepairAttempt`；
- `ArtifactManifest`；
- `RegistryEntry`；
- workspace initializer；
- path resolver 和 confinement checker。

Non-goals：

- 不实现真实 worker；
- 不实现完整 Verifier；
- 不实现 Registry approval；
- 不接 ContextForge；
- 不做 UI。

Acceptance criteria：

- schema 可 JSON/YAML round-trip；
- workspace 可初始化；
- locked input hash 稳定；
- 路径逃逸被拒绝；
- 符号链接逃逸被拒绝或被明确禁止；
- 修改 locked input 后检查失败；
- artifact manifest 能覆盖关键输入和输出。

Dependencies：

- 依赖 WP0。

## WP2：LangGraph Skeleton

目标：

- 建立最小 LangGraph workflow；
- state 只保存 refs、hashes、status、attempt counters；
- 支持 build、verify、repair、register 主流程；
- 支持 fail-closed 和 resume。

Owns：

- workflow graph；
- route enum；
- refs-only state；
- checkpoint；
- failure classification；
- repair loop；
- human review placeholder。

Non-goals：

- 不调用真实 Codex Worker；
- 不实现完整 UI；
- 不把 artifact 正文塞入 state；
- 不把 worker transcript 当作可控状态。

Acceptance criteria：

- workflow 可用 stub node 跑通；
- state 中不包含大文本、raw logs、完整 package 或 replay bundle；
- attempt 超限后进入 fail-closed 或 human review；
- 中断后可通过 refs 恢复；
- route 至少覆盖 build_new、reuse_existing、reject_unsafe、ask_clarifying_question。

Dependencies：

- 依赖 WP1 schema 和 workspace refs。

## WP3：WorkerAdapter

目标：

- 定义 worker 调用边界；
- 实现 FakeWorker；
- 为 CodexWorker 保留 adapter 接口；
- 统一 attempt、diff、transcript、execution report 输出协议。

Owns：

- `BuildWorker` interface；
- `FakeWorker`；
- `CodexWorker` placeholder 或 adapter skeleton；
- worker timeout；
- env allowlist；
- writable path allowlist；
- worker transcript artifact；
- output diff；
- execution report；
- usage availability 字段。

Non-goals：

- 不接真实 Codex Worker 自动批准链路；
- 不绕过 workspace confinement；
- 不把 builder self-report 作为 pass；
- 不实现 Verifier 业务规则。

Acceptance criteria：

- FakeWorker 可生成一个最小 Skill；
- FakeWorker 可生成一个故意失败 Skill；
- FakeWorker 可根据 repair input 修复 Skill；
- worker 试图写 workspace 外路径时失败；
- worker 没有 execution report 时不能进入 verifier pass；
- invocation 记录 duration、exit status、input/output refs 和 usage availability。

Dependencies：

- 依赖 WP1；
- 可与 WP2 并行部分开发，但集成依赖 WP2 workflow。

## WP4：Verifier

目标：

- 构建独立强验收门；
- 使 builder self-report 无法绕过验收；
- 输出机器可读 `verification_result.json`。

Owns：

- static checker；
- package checker；
- path confinement checker；
- artifact hash checker；
- trigger / non-trigger fixture checker；
- script policy checker；
- sandbox smoke；
- optional LLM judge adapter；
- verification summary。

Non-goals：

- 不信任 worker 自报；
- 不把 LLM judge 当唯一 gate；
- 不写 Registry；
- 不做完整安全沙箱产品化。

Acceptance criteria：

- 缺 required section 必 fail；
- 路径穿越必 fail；
- hash mismatch 必 fail；
- 缺 artifact manifest 必 fail；
- builder 自报 pass 但 verifier fail 时整体失败；
- verifier result schema 可校验；
- verifier result 可复现；
- fixture pass/fail 都有测试覆盖。

Dependencies：

- 依赖 WP1；
- 与 WP3 集成后用于验证 worker 输出。

## WP5：ContextForge Integration

目标：

- 将 ContextForge 接入 SkillFoundry；
- owned LLM 节点通过 ContextForge；
- external worker invocation 只记录边界证据；
- verifier logs 经过 ToolOutputGovernor 或等价治理后才可进入 prompt；
- 落盘 metrics 和 evidence refs。

Owns：

- ContextForge ledger adapter；
- owned LLM call wrapper；
- worker boundary record；
- verifier log governance；
- artifact refs；
- job-level metrics；
- usage unavailable reason；
- replay coverage 计算规则。

Non-goals：

- 不把 Codex Worker 内部 prompt 写成 ContextForge 可控对象；
- 不把 Codex Worker 内部 tool loop 写成 ContextForge replay 对象；
- 不把 ContextForge 描述为 sandbox、shell runtime、MCP runtime、队列、权限系统或 UI；
- 不接真实 provider 时不伪造 usage。

Acceptance criteria：

- owned LLM call 有 PromptView 和 ModelCallEnvelope；
- owned LLM replay artifact 可定位；
- worker invocation 有 input/output boundary record；
- raw verifier log 不直接进入 prompt；
- metrics 包含 attempt count、verification status、worker duration、usage availability；
- replay coverage 不夸大 Codex Worker 内部过程；
- usage 不可得时记录明确原因。

Dependencies：

- 依赖 WP1；
- 与 WP2、WP3、WP4 集成。

## WP6：Registry MVP

目标：

- 注册通过 Verifier 的 Skill；
- 保存 provenance 和 hash；
- 支持 approved、rejected、quarantined 状态。

Owns：

- local JSON 或 SQLite registry；
- registry writer；
- registry verifier gate；
- package hash；
- verification result hash；
- artifact manifest hash；
- rollback/quarantine metadata；
- registry query。

Non-goals：

- 不做 marketplace；
- 不做多租户权限；
- 不接受 builder self-report；
- 不自动注册 verifier-failed package。

Acceptance criteria：

- verifier fail 不能注册；
- hash 改变后 registry 校验失败；
- approved entry 可追溯到 build job、worker invocation、verification spec 和 verification result；
- quarantined entry 不能作为默认复用候选；
- registry 写入是幂等或能明确拒绝重复版本。

Dependencies：

- 依赖 WP1 和 WP4；
- 推荐在 WP5 边界证据接入后补齐 provenance refs。

## WP7：Offline E2E MVP

目标：

- 本地 CLI 或等价入口跑通完整 Codex Skill 工厂闭环；
- 使用 FakeWorker；
- 输出最终 verification report 和 registry entry。

Owns：

- offline build command；
- offline verify command；
- sample requirements；
- fixture cases；
- repair loop；
- final report generation；
- smoke test。

Non-goals：

- 不接真实 Codex Worker；
- 不做完整 API/UI；
- 不做生产队列；
- 不依赖外部网络。

Acceptance criteria：

- `build_new` 正常构建；
- `reuse_existing` 可路由；
- `reject_unsafe` 可拒绝；
- 模糊需求触发澄清；
- 初版 Skill 故意失败，repair 后通过；
- 路径穿越被拒绝；
- attempt 超限进入 human review 或 fail-closed；
- 中断后可 resume；
- registry 只接受 hash 匹配 package；
- final verification report 能链接核心 evidence refs。

Dependencies：

- 依赖 WP1-WP6。

## WP8：CodexWorker Pilot

目标：

- 接入真实 Codex CLI/SDK 或可用 Codex Worker；
- 不改变 WorkerAdapter 上层协议；
- 验证真实 worker 在受限 workspace 中构建 Skill 的可行性。

Owns：

- CodexWorker adapter；
- invocation command assembly；
- transcript capture；
- timeout handling；
- failure classification；
- usage availability handling；
- pilot fixtures。

Non-goals：

- 不绕过 WP1-WP7 gate；
- 不把 Codex Worker 内部过程描述为 ContextForge 可控；
- 不把 worker 自报作为 acceptance；
- 不直接接生产用户。

Acceptance criteria：

- CodexWorker 能完成一个简单 Skill；
- CodexWorker 失败能进入 repair；
- CodexWorker 越权写路径被拒绝；
- 成本或 usage 不可得时记录 `usage_unavailable_reason`；
- Verifier 是最终 gate；
- Registry 只接受 verifier-passed package。

Dependencies：

- 必须依赖 WP1-WP7 全部通过。

## WP9：Minimal API/UI

目标：

- 给内部用户一个最小可用入口；
- 能提交需求、查看 job、查看报告、下载 approved Skill。

Owns：

- API job create/get/list；
- artifact download；
- registry query；
- minimal read-only UI 或静态报告页；
- basic auth placeholder 或内部访问说明。

Non-goals：

- 不做企业级多租户；
- 不做完整权限平台；
- 不做 marketplace；
- 不改变 worker/verifier/registry 信任模型。

Acceptance criteria：

- 用户能提交需求；
- 用户能看到澄清、构建、验证、注册状态；
- 用户能查看 verification report；
- 用户能下载 approved Skill package；
- API 不暴露 workspace 外文件；
- UI 不展示未通过 verifier 的 package 为 approved。

Dependencies：

- 依赖 WP7；
- CodexWorker pilot 不是 API/UI 的强依赖，但真实 worker 功能需要 WP8。

## WP10：Feedback Loop

目标：

- 收集真实使用反馈；
- 形成 Skill 版本迭代；
- 支持组织内部分发和质量改进。

Owns：

- feedback record；
- failed usage case；
- Skill version upgrade；
- registry search；
- usage metrics；
- reviewer workflow；
- batch build queue 设计或最小实现。

Non-goals：

- 不提前扩展成通用任务平台；
- 不降低 verifier gate；
- 不让反馈直接修改 approved package；
- 不省略 provenance。

Acceptance criteria：

- 反馈能生成 repair job；
- Skill 可以版本升级；
- 旧版本可 quarantine 或 rollback；
- dashboard 或报告可看到成功率、失败分类、成本和 worker 质量；
- 新版本仍需通过 Verifier 和 Registry gate；
- 反馈链路保留来源和审查记录。

Dependencies：

- 依赖 WP6-WP9 的资产、报告和用户入口。
