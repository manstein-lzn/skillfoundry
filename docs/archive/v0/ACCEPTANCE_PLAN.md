# SkillFoundry 验收计划 v0.2

## 1. 验收原则

SkillFoundry 的验收标准不是“模型生成了文件”，而是：

- 输入、输出和边界可追踪；
- 关键 artifact 可 hash；
- builder self-report 不能直接通过；
- Verifier 是主质量门；
- Registry 只接收 verifier-passed package；
- ContextForge 对 owned LLM call 可 replay，对外部 worker 只记录边界证据；
- 所有安全不确定性默认 fail-closed。

LLM judge 可以存在，但只能作为辅助信号，不能是唯一 gate。

## 2. WP0 文档验收

目标：

- 确认设计文档足以指导后续实现；
- 确认 v0.2 的关键纠偏已经落入文档。

必须通过：

- `WHITEPAPER.md` 存在；
- `docs/ARCHITECTURE.md` 存在；
- `docs/WORK_PACKAGES.md` 存在；
- `docs/ACCEPTANCE_PLAN.md` 存在；
- 文档明确 Codex Worker 是黑盒外部 worker；
- 文档明确 ContextForge 不控制 Codex Worker 内部 prompt、tool loop、context compaction、cache 或 cost；
- 文档明确 owned LLM call 走 `ContextRequest -> PromptView -> ModelCallEnvelope -> ContextKernel`；
- 文档明确 Verifier 是主质量门；
- 文档明确 builder self-report 不是验收证据；
- 文档明确真实 Codex Worker 集成必须等待 workspace confinement、WorkerAdapter、Verifier 和 Registry gate。

轻量命令：

```bash
test -f WHITEPAPER.md
test -f docs/ARCHITECTURE.md
test -f docs/WORK_PACKAGES.md
test -f docs/ACCEPTANCE_PLAN.md
grep -q "Codex Worker" WHITEPAPER.md
grep -q "ContextForge" docs/ARCHITECTURE.md
grep -q "WorkerAdapter" docs/WORK_PACKAGES.md
grep -q "Verifier" docs/ACCEPTANCE_PLAN.md
```

## 3. Schema / Workspace 验收

目标：

- 验证文件即上下文协议和核心 schema 可以支撑后续 worker、verifier 和 registry。

必须通过：

- `SkillSpec`、`BuildContract`、`VerificationSpec`、`WorkerInvocation`、`ExecutionReport`、`VerificationResult`、`ArtifactManifest`、`RegistryEntry` 可序列化；
- JSON/YAML round-trip 后语义不丢失；
- workspace initializer 创建标准目录；
- locked input hash 稳定；
- 修改 locked input 后检查失败；
- workspace 外路径被拒绝；
- `..`、绝对路径、符号链接逃逸被拒绝或显式禁止；
- artifact manifest 覆盖所有关键输入和输出；
- resume brief 只保存摘要和引用，不复制完整 transcript。

示例命令形态：

```bash
skillfoundry workspace init --job-id demo-001 --output runs/demo-001
skillfoundry workspace check --job runs/demo-001
skillfoundry schema roundtrip --fixtures tests/fixtures/schema
skillfoundry security path-check --job runs/demo-001
```

通过标准：

- 所有 schema fixture pass；
- 所有路径逃逸 fixture fail；
- locked input tamper fixture fail；
- manifest 缺失 fixture fail。

## 4. LangGraph State 验收

目标：

- 确认工作流只在 state 中保存 refs-only 轻量信息；
- 确认失败和重试按 gate 路由。

必须通过：

- state 包含 `job_id`、`stage`、`status`、`route`、`attempt_count`、`refs`、`hashes`；
- state 不包含完整 Skill package、raw logs、完整 worker transcript、完整 replay bundle；
- route 覆盖 build_new、reuse_existing、reject_unsafe、ask_clarifying_question、human_review_required；
- attempt 超限进入 fail-closed 或 human review；
- 中断后可根据 refs resume；
- checkpoint 不依赖 worker 内部状态。

示例命令形态：

```bash
skillfoundry graph smoke --fixture build_new
skillfoundry graph inspect-state --job runs/demo-001
skillfoundry graph resume --job runs/demo-001
```

通过标准：

- inspect-state 没有大文本字段；
- resume 后下一步与 checkpoint 一致；
- unsafe requirement 不进入 build。

## 5. WorkerAdapter 验收

目标：

- 确认外部 worker 只能通过受控边界被调用；
- 确认 worker 产物不能绕过 Verifier。

必须通过：

- FakeWorker 能生成最小 Skill package；
- FakeWorker 能生成故意失败 package；
- FakeWorker 能根据 repair input 修复；
- worker 只能写允许路径；
- workspace 外写入被拒绝；
- timeout 生效；
- attempt limit 生效；
- 每次 invocation 有 input manifest、execution report、diff 或等价摘要、transcript artifact、duration、exit status；
- usage 不可得时记录 `usage_unavailable_reason`；
- 缺 execution report 时不能进入 verifier pass。

示例命令形态：

```bash
skillfoundry worker run --worker fake --job runs/demo-001
skillfoundry worker run --worker fake --fixture path_escape --job runs/escape-001
skillfoundry worker inspect --job runs/demo-001 --attempt 001
```

通过标准：

- path_escape fixture fail；
- missing_report fixture fail；
- fixed_package fixture 仍需等待 Verifier pass 才能注册。

## 6. Verifier 验收

目标：

- 确认独立 Verifier 是主质量门；
- 确认 builder self-report 无法通过验收。

必须通过：

- package 结构检查；
- `SKILL.md` required sections 检查；
- trigger / non-trigger fixture 检查；
- required inputs / expected outputs 覆盖检查；
- reference/scripts 路径安全检查；
- package path confinement 检查；
- artifact manifest 完整性检查；
- hash 一致性检查；
- sandbox smoke；
- verification result schema 校验；
- 可选 LLM judge 只作为辅助。

必须失败的 fixture：

- 缺 required section；
- 路径穿越；
- hash mismatch；
- 缺 artifact manifest；
- builder 自报 pass 但实际结构错误；
- LLM judge pass 但静态检查 fail；
- sandbox smoke fail。

示例命令形态：

```bash
skillfoundry verify --job runs/demo-001
skillfoundry verify --fixture missing_required_section
skillfoundry verify --fixture builder_self_report_only
skillfoundry verify --fixture path_traversal
```

通过标准：

- `verification_result.json` 机器可读；
- pass/fail 原因可定位到 evidence refs；
- builder self-report 不出现在 pass evidence 中；
- Verifier fail 时 Registry 写入被拒绝。

## 7. ContextForge 集成验收

目标：

- 确认 ContextForge 用于正确边界；
- 确认 replay 和 usage 不被夸大。

必须通过：

- owned LLM call 有 `ContextRequest`；
- owned LLM call 有 `PromptView`；
- owned LLM call 有 `ModelCallEnvelope`；
- owned LLM call 产生 ModelCallRecord、UsageRecord 或明确 error record；
- owned LLM call replay artifact 可定位；
- memory 显式请求和注入；
- raw verifier log 不直接进入 prompt；
- worker invocation 被记录为 boundary evidence；
- worker transcript、diff、execution report、verifier result、registry decision 有 refs；
- Codex Worker usage 不可得时记录 unavailable reason；
- replay coverage 不统计 Codex Worker 内部 prompt/tool loop。

必须拒绝的声明或实现：

- “真实 Codex Worker 内部 prompt 属于 ContextForge replay 对象”；
- “Codex Worker tool loop 属于 ContextForge 控制范围”；
- “sandbox/shell/MCP runtime/queue/UI 已由 ContextForge 提供”；
- “外部 worker 内部调用也计入 owned LLM replay 覆盖率”。

示例命令形态：

```bash
skillfoundry context audit --job runs/demo-001
skillfoundry context replay --job runs/demo-001 --node clarify
skillfoundry context evidence --job runs/demo-001 --worker-boundary
```

通过标准：

- owned call replay 可打开；
- worker boundary evidence 可打开；
- audit 报告清楚区分 owned call 和 external worker invocation；
- usage unavailable reason 不为空且不伪造成本。

## 8. Registry 验收

目标：

- 确认 Registry 只保存经过 Verifier gate 的 approved asset。

必须通过：

- verifier fail 不能注册；
- 缺 package hash 不能注册；
- hash 改变后 registry 校验失败；
- approved entry 可追溯到 build job、worker invocation、verification spec、verification result、artifact manifest；
- quarantine 状态阻止默认复用；
- duplicate version 有明确拒绝或幂等策略；
- registry 不接受 builder self-report。

示例命令形态：

```bash
skillfoundry registry add --job runs/demo-001
skillfoundry registry verify --skill-id demo-skill --version 0.1.0
skillfoundry registry quarantine --skill-id demo-skill --version 0.1.0
skillfoundry registry list --status approved
```

通过标准：

- verifier-passed package 可注册；
- verifier-failed package 被拒绝；
- tampered package 被拒绝；
- quarantined package 不出现在默认 approved 复用候选中。

## 9. E2E Smoke 验收

目标：

- 验证离线 Codex Skill 工厂闭环；
- WP7 之前使用 FakeWorker；
- WP8 后可增加真实 CodexWorker pilot smoke。

离线 smoke 必须覆盖：

- `build_new`；
- `reuse_existing`；
- `reject_unsafe`；
- ambiguous requirement -> clarification；
- first attempt fail -> repair -> verifier pass；
- path traversal fail；
- attempt limit fail-closed；
- resume；
- registry approved entry；
- final verification report。

示例命令形态：

```bash
skillfoundry build --requirement examples/requirements/pytest_repair.md --output runs/demo-001
skillfoundry verify --job runs/demo-001
skillfoundry registry add --job runs/demo-001
skillfoundry report --job runs/demo-001
```

通过标准：

- demo job 完整产出 Skill package；
- 初始失败和 repair 证据可查；
- final verifier pass；
- registry entry hash 与 package hash 一致；
- report 链接核心 evidence refs；
- 不依赖真实网络或真实 Codex Worker。

CodexWorker pilot smoke 的额外条件：

- 只能在 WP1-WP7 通过后运行；
- 真实 worker 仍受 WorkerAdapter 和 workspace confinement 限制；
- 成功结果仍必须由 Verifier 决定；
- cost/usage 不可得时记录 unavailable reason。

## 10. Security / Fail-Closed 验收

安全 baseline 必须覆盖所有 WP。

必须 fail-closed 的情况：

- workspace 外路径；
- 未声明写路径；
- missing manifest；
- hash mismatch；
- missing execution report；
- missing verification result；
- verifier fail；
- unsafe requirement；
- attempt limit exceeded；
- timeout；
- registry provenance 缺失；
- package quarantine；
- raw logs 直接注入 prompt；
- worker transcript 被当作可信 pass evidence。

最小安全测试集：

```text
path_escape
symlink_escape
absolute_path_write
missing_manifest
hash_mismatch
missing_execution_report
self_report_pass_only
llm_judge_only_pass
unsafe_requirement
attempt_limit_exceeded
timeout
quarantined_reuse
raw_log_prompt_injection
```

通过标准：

- 所有安全 fixture 得到 deterministic fail；
- fail 结果包含原因和 evidence refs；
- 失败不会写入 approved Registry；
- 失败不会被 report summary 改写成成功；
- 人工审查只可改变 review status，不能绕过缺失 evidence 的事实。

## 11. 发布前验收矩阵

```text
+-----------+--------------------------+------------------------------+
| Area      | Primary Evidence         | Blocking Gate                |
+-----------+--------------------------+------------------------------+
| Docs      | Markdown docs            | terminology and boundaries   |
| Workspace | schema + manifest tests  | path/hash confinement        |
| Graph     | state inspection         | refs-only checkpoint         |
| Worker    | invocation artifacts     | adapter boundary             |
| Verifier  | verification_result.json | independent pass/fail        |
| Context   | PromptView + evidence    | no worker-internal overclaim |
| Registry  | RegistryEntry hashes     | verifier-passed only         |
| E2E       | final report             | full offline smoke           |
| Security  | negative fixtures        | fail-closed                  |
+-----------+--------------------------+------------------------------+
```

任何 blocking gate 未通过时，不得宣称该 WP 完成。
