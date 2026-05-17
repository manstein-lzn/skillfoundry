# SkillFoundry 分阶段 Roadmap

## 0. 路线总判定

SkillFoundry 的 MVP 采用以下路线：

```text
LangGraph 编排
+ 文件即上下文的 workspace 协议
+ Codex Worker 黑盒执行
+ 独立 Verifier 强验收
+ Registry 资产沉淀
+ ContextForge 任务级证据账本
+ MetaLoop 风格任务治理思想
```

这是一条 **conditional-go** 路线：

- 可以作为 MVP 采用；
- 不先自建完整 ActionRuntime；
- 不假装 ContextForge 能控制 Codex Worker 内部上下文；
- 必须先定义 workspace 协议、worker 边界、verifier、registry 信任模型和安全底线。

核心原则：

```text
少管黑盒过程，严管输入边界和输出验收。
```

## 1. 最终产物定义

SkillFoundry 最终要成为一套大模型需求交付平台。

第一个 MVP 只交付 **Codex Skill 工厂**：

```text
自然语言需求
  -> 需求澄清
  -> SkillSpec
  -> BuildContract
  -> Codex Worker 构建 Skill package
  -> 独立 Verifier 验收
  -> Repair loop
  -> Registry approved entry
  -> Verification report
```

MVP 的真实目标不是“能生成文件”，而是：

> 能把一个需求转化为经过独立验证、可追溯、可注册、可复用的 Codex Skill。

## 2. 架构边界

### 2.1 LangGraph

LangGraph 负责流程和状态：

- 当前 job 处于哪个阶段；
- 下一个节点是什么；
- repair / reject / human review / register 如何路由；
- checkpoint 和 resume；
- attempt 计数和失败分类。

LangGraph state 只能保存轻量引用：

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

禁止把大文本、worker transcript、raw logs、完整 Skill 包、replay bundle 放入 LangGraph state。

### 2.2 Workspace Protocol

Workspace 是“文件即上下文”的载体。

每个 build job 有独立目录：

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

- `build_contract.yaml`、`skill_spec.yaml`、`verification_spec.yaml` 构建前锁定；
- worker 只允许写 `package/` 和当前 `attempts/<n>/`；
- registry 只能由平台写；
- 所有路径必须 resolve 后确认在 job workspace 内；
- 所有关键 artifact 必须有 hash；
- 每次 attempt 必须有 execution report。

### 2.3 Codex Worker

Codex Worker 是封闭但高能力的外部 agent runtime。

它负责：

- 读取 workspace 文件；
- 生成或修复 Skill package；
- 写 `SKILL.md`、reference、scripts、tests；
- 运行它内部需要的工程操作；
- 输出 execution report、diff、summary、transcript。

SkillFoundry 不控制 Codex Worker 内部 prompt、tool loop、上下文压缩和 cache。

SkillFoundry 只控制：

- worker 输入文件；
- worker 可写范围；
- worker timeout；
- worker 输出协议；
- worker transcript / diff / report 的记录；
- verifier 是否接受结果。

### 2.4 ContextForge

ContextForge 在 SkillFoundry 中承担两类职责。

第一类：对 SkillFoundry 自有 LLM 节点做细粒度上下文治理：

- 需求澄清；
- SkillSpec 生成；
- 路由判断；
- failure 分析；
- repair plan；
- LLM judge；
- report summary。

这些 owned LLM call 必须走：

```text
ContextRequest -> PromptView -> ModelCallEnvelope -> ContextKernel.invoke_model()
```

第二类：对 Codex Worker 做边界证据记录：

- worker invocation；
- worker input manifest；
- workspace hash；
- execution report；
- output diff；
- transcript artifact；
- verifier result；
- registry decision；
- usage unavailable reason。

ContextForge 不承担：

- shell runtime；
- MCP runtime；
- Codex Worker 内部 prompt 控制；
- 权限系统；
- 沙箱系统；
- 任务队列；
- marketplace。

### 2.5 Verifier

Verifier 是 MVP 的质量生命线。

它独立于 builder，不接受 builder 自报成功。

第一版必须包含：

- package 结构检查；
- `SKILL.md` required sections；
- trigger / non-trigger 检查；
- required inputs / expected outputs 检查；
- reference/scripts 路径安全；
- package path confinement；
- 禁止路径穿越；
- artifact hash 校验；
- verification report schema 校验；
- sandbox smoke；
- fixture case；
- 可选 LLM judge，但不能作为唯一主验收门。

### 2.6 Registry

Registry 只接受 verifier 通过的 Skill。

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

## 3. 分阶段 Roadmap

### Phase 0：路线修正与设计冻结

目标：

- 将白皮书升级到 v0.2；
- 明确新路线是“外部 worker 监督型工厂”；
- 修正 ContextForge 和 Codex Worker 的边界；
- 固化 MVP 不自建完整 ActionRuntime 的决策。

交付物：

- `WHITEPAPER.md` v0.2；
- `docs/ROADMAP.md`；
- `docs/ARCHITECTURE.md`；
- `docs/WORK_PACKAGES.md`；
- `docs/ACCEPTANCE_PLAN.md`。

验收：

- 文档明确 owned LLM call 和 external worker invocation 的区别；
- 文档明确 ContextForge 不控制 Codex Worker 内部上下文；
- 文档明确 verifier 是主质量门；
- 文档明确接真实 Codex Worker 前必须有 workspace confinement。

### Phase 1：Workspace 协议与数据模型

目标：

- 定义所有核心 schema；
- 定义 job workspace 目录；
- 定义文件权限和 hash 规则；
- 定义 attempt 模型和 resume 模型。

交付物：

- `BuildJob`
- `BuildContract`
- `SkillSpec`
- `VerificationSpec`
- `WorkerInvocation`
- `ExecutionReport`
- `VerificationResult`
- `RepairAttempt`
- `ArtifactManifest`
- `RegistryEntry`
- `ApprovalRecord`

验收：

- schema 可 JSON/YAML round-trip；
- workspace 可初始化；
- hash 可稳定生成；
- 路径逃逸被拒绝；
- locked input 被修改时 verifier 能发现。

### Phase 2：LangGraph 骨架

目标：

- 实现最小 LangGraph workflow；
- state 只保存 refs、hashes、status、attempt counters；
- 支持 build / verify / repair / register 主流程。

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
- checkpoint；
- route enum；
- failure classification；
- repair loop；
- human review gate placeholder。

验收：

- 不把大文本放入 LangGraph state；
- workflow 可用 FakeWorker 跑通；
- attempt 超限后 fail-closed；
- 中断后可 resume。

### Phase 3：WorkerAdapter

目标：

- 先实现 FakeWorker；
- 定义 CodexWorker adapter 接口；
- 统一 worker 输入输出协议；
- 实现 attempt 目录、diff、transcript 和 execution report。

交付物：

- `BuildWorker` interface；
- `FakeWorker`；
- `CodexWorker` placeholder 或 adapter skeleton；
- worker timeout；
- env allowlist；
- writable path allowlist；
- worker transcript artifact；
- output diff。

验收：

- FakeWorker 可生成一个故意失败 Skill；
- FakeWorker 可根据 repair input 修复 Skill；
- Worker 试图写 workspace 外路径时失败；
- Worker 没有 execution report 时不能进入 verifier pass。

### Phase 4：独立 Verifier

目标：

- 构建强验证门；
- builder self-report 不算证据；
- verifier 输出机器可读 `verification_result.json`。

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

验收：

- 缺 required section 必 fail；
- 路径穿越必 fail；
- hash 不匹配必 fail；
- 缺 artifact manifest 必 fail；
- builder 自报 pass 但 verifier fail 时 registry 不接受；
- verifier result 可复现。

### Phase 5：ContextForge 集成

目标：

- 把 ContextForge 接入 SkillFoundry；
- owned LLM 节点走 ContextForge；
- worker 黑盒只记录边界；
- verifier logs 走 ToolOutputGovernor；
- metrics 和 evidence refs 落盘。

交付物：

- ContextForge ledger adapter；
- owned LLM call wrapper；
- worker boundary record；
- verifier log governance；
- artifact refs；
- job-level metrics；
- usage unavailable reason。

验收：

- owned LLM call 有 PromptView / ModelCallEnvelope；
- worker invocation 有 input/output boundary record；
- raw verifier log 不直接进入 prompt；
- metrics 包含 attempt count、verification status、worker duration、usage availability；
- replay coverage 不夸大 Codex Worker 内部过程。

### Phase 6：Registry MVP

目标：

- 注册通过 verifier 的 Skill；
- 保存 provenance 和 hash；
- 支持 approved / rejected / quarantined 状态。

交付物：

- local JSON 或 SQLite registry；
- registry writer；
- registry verifier gate；
- package hash；
- verification result hash；
- artifact manifest hash；
- rollback/quarantine metadata。

验收：

- verifier fail 不能注册；
- hash 改变后 registry 校验失败；
- approved entry 可追溯到 build job 和 worker invocation；
- registry 不接受 builder 自报成功。

### Phase 7：端到端离线 MVP

目标：

- 本地 CLI 跑通完整 Codex Skill 工厂闭环；
- 暂时使用 FakeWorker；
- 输出最终 verification report 和 registry entry。

最小命令：

```bash
skillfoundry build --requirement examples/requirements/pytest_repair.md --output runs/demo-001
skillfoundry verify --job runs/demo-001
skillfoundry registry list
```

验收场景：

- `build_new` 正常构建；
- `reuse_existing` 可路由；
- `reject_unsafe` 可拒绝；
- 模糊需求触发澄清；
- 初版 Skill 故意失败，repair 后通过；
- 路径穿越被拒绝；
- attempt 超限进入 human_review；
- 中断后 resume；
- registry 只接受 hash 匹配 package。

### Phase 8：真实 Codex Worker 试点

目标：

- 接入 Codex CLI/SDK；
- 不改变 WorkerAdapter 上层协议；
- 验证真实 worker 在受限 workspace 中构建 Skill 的可行性。

前置条件：

- Phase 1-7 全部通过；
- workspace confinement 已实现；
- verifier 已实现；
- registry gate 已实现；
- worker timeout 和 attempt limit 已实现；
- transcript / diff / execution report 已落盘。

验收：

- CodexWorker 能完成一个简单 Skill；
- CodexWorker 失败能进入 repair；
- CodexWorker 越权写路径被拒绝；
- 成本/usage 不可得时记录 `usage_unavailable_reason`；
- verifier 是最终 gate。

### Phase 9：最小 API / UI

目标：

- 给内部用户一个最小可用入口；
- 不做企业级多租户；
- 能提交需求、查看 job、查看报告、下载 Skill。

交付物：

- FastAPI 或等价 API；
- job create / get / list；
- artifact download；
- registry query；
- minimal read-only UI 或静态报告页。

验收：

- 用户能提交需求；
- 用户能看到澄清、构建、验证、注册状态；
- 用户能查看 verification report；
- 用户能下载 approved Skill package。

### Phase 10：反馈闭环与产品化

目标：

- 收集真实使用反馈；
- 形成 Skill 版本迭代；
- 支持组织内部分发。

交付物：

- feedback record；
- failed usage case；
- Skill version upgrade；
- registry search；
- usage metrics；
- reviewer workflow；
- batch build queue。

验收：

- 反馈能生成 repair job；
- Skill 可以版本升级；
- 旧版本可 quarantine 或 rollback；
- dashboard 可看到成功率、失败分类、成本和 worker 质量。

## 4. Work Packages 总表

| WP | 名称 | 主要目标 | 关键验收 |
| --- | --- | --- | --- |
| WP0 | 文档 v0.2 | 修正路线和边界 | 白皮书承认 Codex Worker 黑盒边界 |
| WP1 | Workspace + Schema | 定义文件协议和核心对象 | schema round-trip、路径安全、hash 稳定 |
| WP2 | LangGraph 骨架 | refs-only state 和主流程 | FakeWorker 跑通 build/verify/repair |
| WP3 | WorkerAdapter | FakeWorker 与 CodexWorker 接口 | attempt、diff、transcript、timeout |
| WP4 | Verifier | 独立强验收 | 路径穿越、缺 section、hash mismatch 必 fail |
| WP5 | ContextForge 集成 | 证据账本和 owned LLM 管理 | 不夸大 Codex 内部 replay |
| WP6 | Registry MVP | approved Skill 资产沉淀 | 只接受 verifier-passed + hash 固定 package |
| WP7 | E2E 离线 MVP | 本地 CLI 完整闭环 | 覆盖 build/reuse/reject/repair/resume |
| WP8 | CodexWorker 试点 | 接真实 Codex Worker | 受限 workspace 内成功构建简单 Skill |
| WP9 | 最小 API/UI | 内部可用入口 | 提交需求、查看报告、下载 Skill |
| WP10 | 反馈闭环 | 版本迭代和产品化 | feedback -> repair job -> version upgrade |

## 5. ASCII 总览表

```text
+-------+-----------------------+-----------------------------+------------------------------+---------------------------+
| Phase | Name                  | Main Deliverable            | Must Pass                    | Exit Condition            |
+-------+-----------------------+-----------------------------+------------------------------+---------------------------+
| 0     | Design v0.2           | Whitepaper/Roadmap update   | Boundaries are explicit      | conditional-go resolved   |
| 1     | Workspace + Schema    | Job files and data models   | path/hash/schema checks      | workspace can initialize  |
| 2     | LangGraph Skeleton    | refs-only workflow          | FakeWorker loop runs         | build->verify->repair     |
| 3     | WorkerAdapter         | FakeWorker/Codex interface  | attempts/diff/transcript     | worker boundary stable    |
| 4     | Verifier              | independent quality gate    | deterministic fail/pass      | registry can trust result |
| 5     | ContextForge Link     | evidence ledger integration | owned LLM and worker records | no black-box overclaim    |
| 6     | Registry MVP          | approved skill registry     | hash/provenance enforced     | approved entry traceable  |
| 7     | Offline E2E MVP       | local CLI complete loop     | key fixtures pass            | demo job fully verified   |
| 8     | CodexWorker Pilot     | real worker integration     | sandbox/timeout/gate works   | simple real skill built   |
| 9     | Minimal API/UI        | internal product entry      | submit/view/download works   | usable by first users     |
| 10    | Feedback Loop         | version and learning cycle  | feedback creates repair job  | repeatable improvement    |
+-------+-----------------------+-----------------------------+------------------------------+---------------------------+
```

## 6. 当前最优下一步

下一步不是直接写平台代码，而是执行 WP0：

1. 将 `WHITEPAPER.md` 升级为 v0.2；
2. 新增 `docs/ARCHITECTURE.md`；
3. 新增 `docs/WORK_PACKAGES.md`；
4. 新增 `docs/ACCEPTANCE_PLAN.md`；
5. 明确 `BuildContract`、`VerificationSpec`、`WorkerAdapter`、`RegistryEntry` 的第一版字段。

完成 WP0 后，再进入 schema 和 workspace 协议实现。

