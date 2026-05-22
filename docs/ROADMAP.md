# SkillFoundry 分阶段 Roadmap v1.1

> 历史状态说明：本文是早期分阶段技术路线快照，不再作为当前执行源。WP15B、WP16、WP17 已在后续实现中完成。当前 v2 技术执行源是 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`，当前接手状态见 `HANDOFF.md`；`docs/DEVELOPMENT_ROADMAP.md` 仅作为 v0 / WP0-WP17 能力基线和产品经验记录。本文保留用于理解架构形成过程和历史设计取舍。

## 0. 总体结论

SkillFoundry 第一阶段采用以下路线：

```text
LangGraph 流程编排
+ ContextForge 自有 LLM 上下文治理和证据账本
+ 文件即上下文 workspace 协议
+ WorkerAdapter 外部 worker 边界
+ Codex Worker 黑盒高能力构建
+ 独立 Verifier 主质量门
+ Registry approved asset store
```

路线判断是 **conditional-go**：

- 可做，且适合作为 Codex Skill 工厂 MVP；
- 不先自建完整 ActionRuntime；
- 不复制 Codex、OpenHuman 或 MetaLoop 源码；
- 借鉴其核心思想：文件上下文、边界证据、长任务恢复、独立验收、失败修复；
- ContextForge 只控制 SkillFoundry 自有 LLM 调用，不控制 Codex Worker 内部 prompt、tool loop、上下文压缩、缓存或成本；
- Codex Worker 必须被看作外部黑盒 builder；
- Verifier 和 Registry 是信任边界。

核心工程原则：

```text
少管黑盒过程，严管输入边界、输出协议、独立验收和资产注册。
```

## 1. 产品目标

SkillFoundry 的长期目标是成为一套基于 LangGraph + ContextForge 的大模型需求交付平台。

第一个 MVP 只做 **Codex Skill 工厂**：

```text
自然语言需求
  -> 需求澄清
  -> SkillSpec
  -> BuildContract
  -> Workspace 初始化
  -> Worker 构建 Skill package
  -> 独立 Verifier 验收
  -> Repair loop
  -> Registry approved entry
  -> Verification report
```

MVP 的验收不是“模型生成了文件”，而是：

> 能把一个模糊需求转化为经过独立验证、可追溯、可注册、可复用的 Codex Skill。

## 2. 历史状态快照

以下内容反映 2026-05-17 附近的历史基线，不代表当前待办状态。当前 v2 重构蓝图见 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`，当前接手状态见 `HANDOFF.md`；WP0-WP17 状态只应从 `docs/DEVELOPMENT_ROADMAP.md` 读取为历史能力基线。

当时 WP0-WP15 的部件级实现已完成，项目已经具备：

- workspace + schema 基础；
- LangGraph refs-only workflow；
- WorkerAdapter + FakeWorker；
- 独立 Verifier；
- ContextForge 自有 LLM 调用和 worker 边界证据接入；
- Local Registry；
- offline E2E build/verify/repair/register/report 闭环；
- 可选 CodexWorker pilot adapter；
- minimal internal API/UI；
- QA Lab；
- feedback/versioning/quarantine/rollback；
- WP12 operations、health/readiness、observability、cleanup、安全清单和生产就绪边界文档；
- Front Desk schema/workspace；
- RequirementsElicitor；
- SpecAuditor；
- deterministic FrontDeskFreezeGate。

后续已完成 Front Desk Loop、Acceptance Coverage Bridge 和 Owned LLM Builder Pilot。继续执行时不要使用本文中的旧 “当前状态” 判断。

## 3. 分层架构

```text
+--------------------------------------------------------------+
| Product/API Layer                                             |
| requirement intake, job view, report view, registry query     |
+--------------------------------------------------------------+
| Orchestration Layer                                           |
| LangGraph nodes, route, retry, checkpoint, fail-closed        |
+--------------------------------------------------------------+
| Context and Evidence Layer                                    |
| ContextForge for owned LLM calls and worker boundary records  |
+--------------------------------------------------------------+
| Workspace Protocol Layer                                      |
| locked specs, manifests, attempts, package, verifier outputs  |
+--------------------------------------------------------------+
| Worker Boundary Layer                                         |
| WorkerAdapter, FakeWorker, CodexWorker adapter                |
+--------------------------------------------------------------+
| Quality and Asset Layer                                       |
| independent Verifier, Registry gate, quarantine, provenance   |
+--------------------------------------------------------------+
```

### 3.1 LangGraph 边界

LangGraph 负责流程和轻量状态：

- 当前 job 处于哪个阶段；
- 下一个节点是什么；
- retry、repair、reject、human review、register 如何路由；
- checkpoint 和 resume；
- attempt 计数和失败分类。

LangGraph state 只能保存轻量引用：

```text
job_id
stage
status
route
attempt_count
failure_class
refs
hashes
next_action
human_review_required
```

禁止把以下内容放入 LangGraph state：

```text
完整 Skill package
完整 worker transcript
raw tool logs
完整 replay bundle
大型 prompt 正文
完整 verification logs
```

### 3.2 ContextForge 边界

ContextForge 在 SkillFoundry 中有两个职责。

第一，管理 SkillFoundry 自有 LLM 调用：

```text
ContextRequest
  -> PromptView
  -> ModelCallEnvelope
  -> ContextKernel.invoke_model()
  -> ModelCallRecord / UsageRecord / ErrorRecord
```

适用节点包括：

- 需求澄清；
- SkillSpec 生成；
- route 判断；
- failure 分析；
- repair plan；
- LLM judge；
- report summary。

第二，记录外部 worker 边界证据：

- worker invocation；
- worker input manifest；
- workspace hash before/after；
- transcript artifact；
- output diff；
- execution report；
- verifier result；
- registry decision；
- usage unavailable reason。

ContextForge 不承担：

- shell runtime；
- MCP runtime；
- Codex Worker 内部 prompt 控制；
- Codex Worker 内部 tool loop replay；
- 权限系统；
- 沙箱系统；
- 队列系统；
- UI。

### 3.3 Workspace 协议

Workspace 是“文件即上下文”的事实边界。

标准目录：

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

关键规则：

- 构建前锁定 `build_contract.yaml`、`skill_spec.yaml`、`verification_spec.yaml`、`worker_input.md`；
- worker 只允许写 `package/` 和当前 `attempts/<n>/`；
- verifier 只允许写 `verifier/`；
- registry 只能由平台写；
- 所有路径必须 resolve 后确认在 job workspace 内；
- 绝对路径、`..`、符号链接逃逸、隐藏跳转默认拒绝；
- 所有关键 artifact 必须有 hash；
- 每次 attempt 必须有 execution report。

### 3.4 WorkerAdapter 边界

WorkerAdapter 是 SkillFoundry 与外部 builder 的唯一调用接口。

建议接口语义：

```text
prepare(invocation)
run(invocation)
collect(invocation)
classify_failure(invocation)
```

输入：

- job workspace 路径；
- build contract；
- worker input manifest；
- timeout；
- env allowlist；
- writable path allowlist；
- attempt id。

输出：

- execution report；
- output diff；
- transcript artifact；
- workspace hash before/after；
- exit status；
- duration；
- usage availability；
- failure class。

第一阶段先实现 FakeWorker。真实 CodexWorker 只能在 workspace、verifier、registry、offline E2E 都稳定后试点。

### 3.5 Verifier 边界

Verifier 是 MVP 的质量生命线。它独立于 builder，不接受 builder 自报成功。

第一版必须检查：

- package 结构；
- `SKILL.md` required sections；
- trigger / non-trigger；
- required inputs / expected outputs；
- reference/scripts 路径安全；
- package path confinement；
- artifact hash；
- verification report schema；
- sandbox smoke；
- fixture case；
- 可选 LLM judge，但不能作为唯一主验收门。

### 3.6 Registry 边界

Registry 只接受 verifier-passed package。

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

Registry 不接受 builder self-report，不接受 hash 不完整的 package，不把 quarantined entry 作为默认复用候选。

## 4. ASCII 总览表

```text
+-------+-----------------------+---------------------------+----------------------------+----------------------------+--------------------------+
| Phase | Name                  | Main Deliverable          | Must Pass                  | Depends On                 | Exit Condition           |
+-------+-----------------------+---------------------------+----------------------------+----------------------------+--------------------------+
| 0     | Design Baseline       | Whitepaper/docs v0.2      | boundaries explicit        | none                       | route frozen             |
| 1     | Workspace + Schema    | schemas, job workspace    | path/hash/schema tests     | Phase 0                    | workspace trusted        |
| 2     | LangGraph Skeleton    | refs-only workflow        | resume/retry/fail-closed   | Phase 1                    | graph can run stubs      |
| 3     | WorkerAdapter         | FakeWorker, worker API    | timeout/diff/report tests  | Phase 1, partial Phase 2   | worker boundary stable   |
| 4     | Verifier              | independent quality gate  | deterministic pass/fail    | Phase 1, Phase 3           | builder cannot self-pass |
| 5     | ContextForge Link     | context/evidence adapter  | owned call replay boundary | Phase 1-4                  | no black-box overclaim   |
| 6     | Registry MVP          | approved asset registry   | hash/provenance gate       | Phase 1, Phase 4           | approved skill traceable |
| 7     | Offline E2E MVP       | local CLI full loop       | fixtures cover main routes | Phase 1-6                  | demo job fully verified  |
| 8     | CodexWorker Pilot     | real worker adapter       | sandbox/timeout/gate works | Phase 1-7                  | simple real skill built  |
| 9     | Minimal API/UI        | internal product entry    | submit/view/download works | Phase 7, optional Phase 8  | first users can use it   |
| 10    | Feedback Loop         | version and feedback flow | feedback creates repair    | Phase 6-9                  | repeatable improvement   |
+-------+-----------------------+---------------------------+----------------------------+----------------------------+--------------------------+
```

## 5. 阶段执行计划

### Phase 0：Design Baseline

目标：

- 将产品路线冻结为外部 worker 监督型工厂；
- 明确 LangGraph、ContextForge、Workspace、WorkerAdapter、Verifier、Registry 的边界；
- 明确 ContextForge 不控制 Codex Worker 内部；
- 明确不自建完整 ActionRuntime；
- 明确 Codex、OpenHuman、MetaLoop 只作为思想参考，不搬源码。

输入：

- 前期关于 Codex 上下文管理、OpenHuman 长任务机制、MetaLoop 任务治理的讨论；
- ContextForge v0.1 能力边界；
- SkillFoundry 产品目标。

交付物：

- `README.md`
- `WHITEPAPER.md`
- `docs/ARCHITECTURE.md`
- `docs/WORK_PACKAGES.md`
- `docs/ACCEPTANCE_PLAN.md`
- `docs/ROADMAP.md`

验收门：

- 文档明确 Codex Worker 是黑盒 external worker；
- 文档明确 owned LLM call 和 external worker invocation 的区别；
- 文档明确 Verifier 是主质量门；
- 文档明确真实 Codex Worker 试点的前置条件；
- 文档不存在“ContextForge 控制 Codex 内部 tool loop/cache/cost”的过度声明。

退出条件：

- 设计文档可以指导 WP1-WP10 实现；
- 后续任何 worker 或工程师可以从文档判断什么该做、什么不该做。

历史状态：

- 已完成并提交。

### Phase 1：Workspace + Schema

目标：

- 定义 job workspace 文件协议；
- 定义核心 schema；
- 实现 hash、锁定输入、artifact manifest、attempt 和 resume 基础；
- 实现路径 confinement 基础能力。

输入：

- Phase 0 架构文档；
- workspace 标准目录；
- schema 清单；
- 安全边界要求。

交付物：

- `pyproject.toml`
- `src/skillfoundry/__init__.py`
- `src/skillfoundry/schema.py`
- `src/skillfoundry/security.py`
- `src/skillfoundry/workspace.py`
- `tests/test_schema.py`
- `tests/test_workspace.py`

核心对象：

- `SkillSpec`
- `BuildContract`
- `VerificationSpec`
- `WorkerInvocation`
- `ExecutionReport`
- `VerificationResult`
- `RepairAttempt`
- `ArtifactManifest`
- `RegistryEntry`
- `ApprovalRecord`

验收门：

- schema 可 JSON/YAML round-trip；
- canonical JSON hash 稳定；
- workspace 可初始化；
- locked input 被修改后检查失败；
- 绝对路径被拒绝；
- `..` 路径被拒绝；
- 符号链接逃逸被拒绝或显式禁止；
- artifact manifest 覆盖锁定输入；
- resume brief 只保存摘要和引用，不复制完整 transcript。

建议命令：

```bash
.venv/bin/python -m pytest -q
```

退出条件：

- workspace 和 schema 可以被 WP2、WP3、WP4 同时依赖；
- 路径安全测试通过；
- 架构师验收通过后提交。

历史状态：

- 当时已有实现草案，正在架构验收阶段；当前 v2 实现状态以 `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md` 与 `HANDOFF.md` 为准，`docs/DEVELOPMENT_ROADMAP.md` 仅作为 v0 历史基线。

### Phase 2：LangGraph Skeleton

目标：

- 建立最小 LangGraph workflow；
- state 只保存 refs、hashes、status、attempt counters；
- 支持 build、verify、repair、register 主流程；
- 支持 fail-closed 和 resume。

输入：

- Phase 1 schema；
- workspace refs；
- route enum；
- failure classification 草案。

建议节点：

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

交付物：

- refs-only state；
- workflow graph；
- route enum；
- checkpoint；
- failure classification；
- repair loop；
- human review placeholder；
- graph smoke tests。

验收门：

- state 不包含大文本、raw logs、完整 package 或 replay bundle；
- workflow 可用 stub node 跑通；
- attempt 超限后进入 fail-closed 或 human review；
- 中断后可根据 refs resume；
- route 至少覆盖 `build_new`、`reuse_existing`、`reject_unsafe`、`ask_clarifying_question`。

退出条件：

- 不接真实 worker 的情况下，graph 可以完成一次 stub build/verify/repair/register 流程；
- inspect-state 能证明 state 是 refs-only。

### Phase 3：WorkerAdapter

目标：

- 定义 worker 调用边界；
- 实现 FakeWorker；
- 为 CodexWorker 保留 adapter 接口；
- 统一 attempt、diff、transcript、execution report 输出协议。

输入：

- Phase 1 workspace；
- Phase 2 workflow skeleton；
- worker invocation schema。

交付物：

- `BuildWorker` interface；
- `FakeWorker`；
- `CodexWorker` placeholder 或 adapter skeleton；
- timeout；
- env allowlist；
- writable path allowlist；
- worker transcript artifact；
- output diff；
- execution report；
- usage availability 字段。

验收门：

- FakeWorker 可生成一个最小 Skill；
- FakeWorker 可生成一个故意失败 Skill；
- FakeWorker 可根据 repair input 修复 Skill；
- worker 试图写 workspace 外路径时失败；
- worker 缺 execution report 时不能进入 verifier pass；
- invocation 记录 duration、exit status、input/output refs 和 usage availability。

退出条件：

- 上层 workflow 不依赖具体 worker 实现；
- FakeWorker 可以支撑后续 Verifier 和 offline E2E。

### Phase 4：Verifier

目标：

- 构建独立强验收门；
- 使 builder self-report 无法绕过验收；
- 输出机器可读 `verification_result.json`。

输入：

- Phase 1 schema 和 path checker；
- Phase 3 worker 输出；
- verification spec；
- fixture cases。

交付物：

- static checker；
- package checker；
- path confinement checker；
- artifact hash checker；
- trigger / non-trigger fixture checker；
- script policy checker；
- sandbox smoke；
- optional LLM judge adapter；
- verification summary。

验收门：

- 缺 required section 必 fail；
- 路径穿越必 fail；
- hash mismatch 必 fail；
- 缺 artifact manifest 必 fail；
- builder 自报 pass 但 verifier fail 时整体失败；
- LLM judge pass 但静态检查 fail 时整体失败；
- verification result schema 可校验；
- verifier result 可复现。

退出条件：

- Registry 可以信任 Verifier 的 pass/fail；
- builder self-report 不能成为 pass evidence。

### Phase 5：ContextForge Integration

目标：

- 将 ContextForge 接入 SkillFoundry；
- owned LLM 节点通过 ContextForge；
- external worker invocation 只记录边界证据；
- verifier logs 经过 ToolOutputGovernor 或等价治理后才可进入 prompt；
- 落盘 metrics 和 evidence refs。

输入：

- ContextForge v0.1；
- Phase 1 artifact refs；
- Phase 2 LLM node skeleton；
- Phase 3 worker boundary；
- Phase 4 verifier result。

交付物：

- ContextForge ledger adapter；
- owned LLM call wrapper；
- worker boundary record；
- verifier log governance；
- artifact refs；
- job-level metrics；
- usage unavailable reason；
- replay coverage 计算规则。

验收门：

- owned LLM call 有 PromptView 和 ModelCallEnvelope；
- owned LLM replay artifact 可定位；
- worker invocation 有 input/output boundary record；
- raw verifier log 不直接进入 prompt；
- metrics 包含 attempt count、verification status、worker duration、usage availability；
- replay coverage 不夸大 Codex Worker 内部过程；
- usage 不可得时记录明确原因。

退出条件：

- 用户可以审计一个 job 中哪些 LLM 调用是可 replay 的，哪些只是外部 worker boundary evidence；
- 系统不伪造外部 worker 成本和内部上下文控制能力。

### Phase 6：Registry MVP

目标：

- 注册通过 Verifier 的 Skill；
- 保存 provenance 和 hash；
- 支持 approved、rejected、quarantined 状态。

输入：

- Phase 1 schema；
- Phase 4 verification result；
- Phase 5 evidence refs。

交付物：

- local JSON 或 SQLite registry；
- registry writer；
- registry verifier gate；
- package hash；
- verification result hash；
- artifact manifest hash；
- rollback/quarantine metadata；
- registry query。

验收门：

- verifier fail 不能注册；
- hash 改变后 registry 校验失败；
- approved entry 可追溯到 build job、worker invocation、verification spec 和 verification result；
- quarantined entry 不能作为默认复用候选；
- registry 不接受 builder self-report；
- duplicate version 有明确拒绝或幂等策略。

退出条件：

- approved Skill 可以被查询、追溯、验证和隔离；
- Registry 成为后续复用决策的可信来源。

### Phase 7：Offline E2E MVP

目标：

- 本地 CLI 或等价入口跑通完整 Codex Skill 工厂闭环；
- 使用 FakeWorker；
- 输出最终 verification report 和 registry entry。

输入：

- Phase 1-WP6 全部能力；
- sample requirements；
- fixture cases。

最小命令形态：

```bash
skillfoundry build --requirement examples/requirements/pytest_repair.md --output runs/demo-001
skillfoundry verify --job runs/demo-001
skillfoundry registry list
```

交付物：

- offline build command；
- offline verify command；
- sample requirements；
- fixture cases；
- repair loop；
- final report generation；
- smoke test。

验收门：

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

退出条件：

- 在不接真实 Codex Worker、不接 UI 的情况下，可以完成一条可验证的本地闭环；
- 这是第一个可以演示给内部用户和技术评审看的版本。

### Phase 8：CodexWorker Pilot

目标：

- 接入真实 Codex CLI/SDK 或可用 Codex Worker；
- 不改变 WorkerAdapter 上层协议；
- 验证真实 worker 在受限 workspace 中构建 Skill 的可行性。

前置条件：

- Phase 1-7 全部通过；
- workspace confinement 已实现；
- verifier 已实现；
- registry gate 已实现；
- worker timeout 和 attempt limit 已实现；
- transcript、diff、execution report 已落盘。

交付物：

- CodexWorker adapter；
- invocation command assembly；
- transcript capture；
- timeout handling；
- failure classification；
- usage availability handling；
- pilot fixtures。

验收门：

- CodexWorker 能完成一个简单 Skill；
- CodexWorker 失败能进入 repair；
- CodexWorker 越权写路径被拒绝；
- 成本或 usage 不可得时记录 `usage_unavailable_reason`；
- Verifier 是最终 gate；
- Registry 只接受 verifier-passed package。

退出条件：

- 真实 Codex Worker 可以作为可替换 worker 被监督调用；
- 系统仍然不声称控制 Codex Worker 内部上下文。

### Phase 9：Minimal API/UI

目标：

- 给内部用户一个最小可用入口；
- 能提交需求、查看 job、查看报告、下载 approved Skill。

输入：

- Phase 7 offline E2E；
- Phase 6 registry；
- 可选 Phase 8 CodexWorker pilot。

交付物：

- API job create/get/list；
- artifact download；
- registry query；
- minimal read-only UI 或静态报告页；
- basic auth placeholder 或内部访问说明。

验收门：

- 用户能提交需求；
- 用户能看到澄清、构建、验证、注册状态；
- 用户能查看 verification report；
- 用户能下载 approved Skill package；
- API 不暴露 workspace 外文件；
- UI 不展示未通过 verifier 的 package 为 approved。

退出条件：

- 第一个内部用户可以不用命令行完成一次需求提交和结果查看；
- 产品仍然遵守 Verifier 和 Registry 信任边界。

### Phase 10：Feedback Loop

目标：

- 收集真实使用反馈；
- 形成 Skill 版本迭代；
- 支持组织内部分发和质量改进。

输入：

- Phase 6 registry；
- Phase 7 reports；
- Phase 9 用户入口；
- 真实使用反馈。

交付物：

- feedback record；
- failed usage case；
- Skill version upgrade；
- registry search；
- usage metrics；
- reviewer workflow；
- batch build queue 设计或最小实现。

验收门：

- 反馈能生成 repair job；
- Skill 可以版本升级；
- 旧版本可 quarantine 或 rollback；
- 新版本仍需通过 Verifier 和 Registry gate；
- dashboard 或报告可看到成功率、失败分类、成本和 worker 质量；
- 反馈链路保留来源和审查记录。

退出条件：

- SkillFoundry 从一次性生成工具升级为持续改进的 Skill 资产工厂；
- 具备扩大到更多需求类型的基础。

## 6. 执行纪律

后续每个 WP 都按同一个节奏推进：

```text
Design
  -> independent review when needed
  -> worker implementation
  -> architect inspection
  -> automated validation
  -> repair if needed
  -> approval
  -> commit
```

必须遵守：

- 每个 WP 开始前写清楚 owns、non-goals、acceptance；
- builder self-report 永远不是验收证据；
- 涉及质量门、路线判断、真实 worker 接入时必须有独立审核；
- 每次实现后必须跑对应测试；
- 文档、schema、workflow、verifier、registry 的边界不允许互相偷换；
- `.metaloop/`、`.venv/`、缓存和运行产物不进 git。

## 7. 停止与重设计条件

出现以下情况时，不继续堆代码，必须回到设计：

- ContextForge 被错误扩展为 shell/MCP/runtime/sandbox 总线；
- LangGraph state 开始承载大文本或完整 transcript；
- WorkerAdapter 无法限制 workspace 写入边界；
- Verifier 只能靠 LLM judge 判断；
- Registry 接受未通过 Verifier 的 package；
- CodexWorker pilot 需要绕过 Phase 1-7 的 gate；
- 成本、usage、replay coverage 被伪造或过度声明；
- repair loop 只能靠人工解释，无法形成机器可读失败分类。

## 8. 最短可演示路径

如果目标是最快做出可演示 MVP，执行顺序为：

```text
Phase 1  Workspace + Schema
Phase 2  LangGraph Skeleton
Phase 3  FakeWorker
Phase 4  Verifier
Phase 6  Registry MVP
Phase 7  Offline E2E MVP
Phase 5  ContextForge Integration
Phase 8  CodexWorker Pilot
Phase 9  Minimal API/UI
Phase 10 Feedback Loop
```

说明：

- Phase 5 可以在 Phase 7 前后穿插，但不能改变 Phase 1-4 的边界；
- Phase 8 不能提前；
- Phase 9 可以先基于 FakeWorker 演示，但真实生产价值依赖 Phase 8；
- Phase 10 是从“工厂能跑”走向“资产能沉淀”的阶段。

## 9. 版本里程碑

```text
v0.1  文档和路线冻结
v0.2  workspace + schema foundation
v0.3  refs-only LangGraph + FakeWorker
v0.4  independent Verifier + Registry MVP
v0.5  offline E2E Codex Skill factory
v0.6  ContextForge integration
v0.7  CodexWorker pilot
v0.8  internal API/UI
v0.9  feedback loop
v1.0  internal production pilot
```

v1.0 的定义：

- 至少 3 类真实 Skill 需求可通过平台构建；
- 每个 approved Skill 都有 verification report、provenance、hash 和 registry entry；
- 失败能进入 repair 或 human review；
- 用户可以提交需求、查看状态、下载结果；
- 系统能区分 owned LLM replay 和 external worker boundary evidence；
- 成本、usage、replay coverage 不做虚假承诺。
