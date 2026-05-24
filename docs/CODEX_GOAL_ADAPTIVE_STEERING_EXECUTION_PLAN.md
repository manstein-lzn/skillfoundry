# Codex Goal: Adaptive Steering Execution Plan

最后更新：2026-05-24

## 文档用途

本文是一份给 Codex `/goal` 使用的长任务执行计划。

它不是新的产品愿景，也不是替代 `ADAPTIVE_STEERING_IMPLEMENTATION_PLAN.md` 的路线图。它的作用是把当前已确认的 vision 和 implementation plan 改写成 `/goal` 可以长期执行、阶段验收、断点续跑的工作契约。

核心目标：

```text
在 SkillFoundry 层完成第一版可运行、可验证、可回滚的 adaptive steering loop，
把 SkillFoundry 从 plan-and-execute 的 Skill 工厂推进到卡尔曼式 Capability Bundle 工厂 MVP。
```

## 当前起点

截至 2026-05-24，当前起点是：

- Phase 0 文档基线已完成；
- Phase 1 Adaptive Schema MVP 已完成；
- Phase 2 Adaptive Workspace Artifacts 已完成；
- Phase 3 及之后未完成；
- 本阶段仍不修改 ContextForge / ForgeUnit / LangGraph 的核心公共 API；
- 复杂真实产品验证仍放在后续 pilot，不在默认测试中调用 live Codex。

已完成代码入口：

```text
src/skillfoundry/adaptive.py
tests/test_adaptive_schema.py
src/skillfoundry/adaptive_workspace.py
tests/test_adaptive_workspace.py
```

已完成 schema：

```text
CapabilityStateEstimate
NextStepContract
ObservationReport
StateCorrection
DecisionRecord
DecisionLedger
```

已知通过验证：

```bash
.venv/bin/python -m pytest tests/test_adaptive_schema.py -q
.venv/bin/python -m pytest tests/test_adaptive_schema.py tests/test_adaptive_workspace.py -q
.venv/bin/python -m pytest -q
git diff --check
```

## /goal 总目标

请 Codex 在当前 repo 中完成 adaptive steering MVP 的剩余阶段：

1. Adaptive Workspace Artifacts；
2. Refs-only Product State Integration；
3. Adaptive Graph Loop MVP；
4. Bundle Manifest MVP；
5. Bundle Verifier MVP；
6. Code Runtime Pilot；
7. Mini Knowledge Runtime Pilot；
8. Substrate Extraction Assessment。

完成后，SkillFoundry 应具备以下能力：

```text
Frozen Spec / Acceptance / Verification Spec
  -> Capability State Estimate
  -> Next-Step Contract
  -> bounded ForgeUnit / command work unit
  -> Observation Report
  -> State Correction
  -> route continue / repair / redesign / review_required / final_verify / closure
  -> Bundle Manifest
  -> Bundle Verifier
  -> refs-only Final Report
  -> Registry gate only after verified
```

## 不变原则

这些原则优先级高于具体实现细节。

### 1. SkillFoundry 先验证，不提前下沉

短期只在 SkillFoundry 层实现 adaptive steering。

除非某个改动无法避免，否则不要修改：

```text
third_party/contextforge/
ForgeUnit public API
LangGraph library behavior
```

如果发现必须修改底座，先写入 extraction / redesign note，不要在本 goal 内大改。

### 2. LangGraph 保持薄编排

LangGraph 只负责 route。

它不拥有：

- capability state semantics；
- evidence reliability；
- verifier policy；
- bundle quality logic；
- long-term memory；
- product domain meaning。

### 3. Refs-only 是硬边界

公开 state、product state、final report、registry entry 中只能出现 refs 和摘要，不允许写入 raw prompt / transcript / full model output。

禁止字段至少包括：

```text
conversation
conversation_turns
messages
prompt
prompts
raw_prompt
model_output
model_outputs
raw_model_output
raw_model_outputs
transcript
raw_transcript
```

### 4. Worker self-report 不是验收

worker claim 可以进入 `ObservationReport.worker_claims`，但不能直接推动 closure。

closure 必须依赖：

- artifacts；
- tests；
- verifier result；
- reviewer result；
- command evidence；
- manifest / hash / path checks。

### 5. 默认离线、确定性、可测试

默认测试不能调用 live Codex、外部网络、真实 MCP 服务或大型 EdaSkill/Codexarium 复刻。

可以保留 live / manual / opt-in runbook，但默认 CI 级验证必须离线。

### 6. 不泄漏本地私有产品代码

后续 Code Runtime Pilot 可以是 Codexarium-like，但不能读取、复制、引用本地已有 Codexarium 私有实现。

需要使用 clean-room fixture 或 synthetic mini runtime。

### 7. 小步闭环

每个 phase 都要：

- 有明确新增/修改文件；
- 有目标测试；
- 通过 `git diff --check`；
- 更新本文或 implementation plan 的当前状态；
- 能独立 commit。

## 建议 /goal 启动提示

可以直接复制下面这段作为 Codex `/goal` 输入：

```text
/goal
在 /home/mansteinl/skillfoundry 中继续实现 SkillFoundry adaptive steering MVP。

请严格遵循 docs/CODEX_GOAL_ADAPTIVE_STEERING_EXECUTION_PLAN.md、docs/ADAPTIVE_STEERING_IMPLEMENTATION_PLAN.md、docs/AGENT_WORK_SUBSTRATE_VISION.md 和 docs/SKILLFOUNDRY_CAPABILITY_BUNDLE_VISION.md。

当前 Phase 0 docs baseline 和 Phase 1 Adaptive Schema MVP 已完成。请从 Phase 2 开始，按阶段推进：

1. Adaptive Workspace Artifacts
2. Refs-only Product State Integration
3. Adaptive Graph Loop MVP
4. Bundle Manifest MVP
5. Bundle Verifier MVP
6. Code Runtime Pilot
7. Mini Knowledge Runtime Pilot
8. Substrate Extraction Assessment

每个阶段必须：
- 先检查当前 git 状态和相关代码；
- 保持 ContextForge / ForgeUnit / LangGraph 核心 API 不变，除非写出明确 redesign note；
- 保持公开状态 refs-only，不写 raw prompt / transcript / full model output；
- 默认离线、确定性、可测试，不默认调用 live Codex；
- 写 focused tests；
- 运行该阶段目标测试、git diff --check，并在关键阶段运行 full pytest；
- 更新 docs/CODEX_GOAL_ADAPTIVE_STEERING_EXECUTION_PLAN.md 的进度；
- 每个阶段完成后提交一个清晰 commit。

如果某阶段出现连续失败，不要蛮干。请记录 observation、diagnosis、options、decision、fallback，然后缩小范围或重设下一步 contract。

最终完成标准：
- adaptive artifacts 可以写入和读取；
- product state / final report 只暴露 refs 和摘要；
- adaptive graph 能跑 happy path、repair path、repeated failure -> review_required；
- bundle manifest 有 schema 和测试；
- bundle verifier 能检查 manifest、entrypoint、runtime refs 和 profile basics；
- 至少完成一个 deterministic code-runtime pilot；
- 至少完成一个 mini knowledge-runtime pilot；
- 写出 substrate extraction assessment；
- full pytest 通过；
- git diff --check 通过；
- 所有阶段变更已提交。
```

## Commit 策略

推荐每个阶段一个 commit。

建议 commit 顺序：

```text
1. Document Codex goal execution plan
2. Add adaptive workspace artifacts
3. Expose adaptive refs in product state
4. Add adaptive graph loop MVP
5. Add capability bundle manifest schema
6. Add bundle verifier checks
7. Add deterministic code runtime pilot
8. Add mini knowledge runtime pilot
9. Document substrate extraction assessment
```

如果某阶段过大，可以拆成：

```text
<phase>: implementation
<phase>: tests
<phase>: docs
```

但不要把多个大阶段压进一个 commit。

## Phase 2: Adaptive Workspace Artifacts

### 目标

把 Phase 1 schema 变成稳定 workspace artifacts。

### 建议新增

```text
src/skillfoundry/adaptive_workspace.py
tests/test_adaptive_workspace.py
```

### 标准 artifact refs

```text
adaptive/capability_state.json
adaptive/next_step_contract_{iteration:03d}.json
adaptive/observation_report_{iteration:03d}.json
adaptive/state_correction_{iteration:03d}.json
adaptive/decision_ledger.json
```

### Helper API

```text
write_capability_state_estimate
read_capability_state_estimate
write_next_step_contract
read_next_step_contract
write_observation_report
read_observation_report
write_state_correction
read_state_correction
append_decision_record
read_decision_ledger
adaptive_contract_ref
adaptive_observation_ref
adaptive_correction_ref
```

### 实现要求

- 复用 `JobWorkspace` 或现有 workspace path/security pattern；
- 所有写入路径必须在 workspace 内；
- artifact refs 必须稳定；
- iteration 编号格式固定为三位；
- `DecisionLedger` append 必须保留历史 decision；
- public artifact 不包含 raw prompt / raw transcript / raw model output；
- 不接入 graph，不改变 worker 执行行为。

### 测试要求

覆盖：

- 初始化 adaptive 目录；
- 写读 state / contract / observation / correction；
- append decision；
- unsafe path 被拒绝；
- duplicate decision id 被拒绝；
- forbidden raw field 被拒绝；
- iteration ref 格式稳定。

### 验收命令

```bash
.venv/bin/python -m pytest tests/test_adaptive_schema.py tests/test_adaptive_workspace.py -q
git diff --check
```

### 完成标准

- Phase 2 目标测试通过；
- no full runtime behavior change；
- 文档进度更新；
- commit 完成。

## Phase 3: Refs-only Product State Integration

### 目标

把 adaptive artifacts 纳入 SkillFoundry product state / evidence summary，但只暴露 refs 和少量状态摘要。

### 可能修改

```text
src/forgeunit_skillfoundry/state.py
src/forgeunit_skillfoundry/report.py
src/forgeunit_skillfoundry/product.py
tests/test_forgeunit_skillfoundry_composition.py
```

具体文件以实际代码结构为准，先读现有 composition 层再改。

### 输出应包含

```text
refs:
  adaptive_state
  latest_next_step_contract
  latest_observation_report
  latest_state_correction
  decision_ledger

adaptive_summary:
  latest_iteration
  latest_route
  latest_decision
  latest_verification_status
```

### 实现要求

- 只暴露 refs 和状态摘要；
- 不把 adaptive artifact body 复制进 product state；
- 不把 raw worker output、prompt、transcript 放入 final report；
- 保持现有 composition API 向后兼容；
- 如果必须新增字段，测试需要覆盖旧路径不破坏。

### 验收命令

```bash
.venv/bin/python -m pytest tests/test_forgeunit_skillfoundry_composition.py -q
.venv/bin/python -m pytest tests/test_adaptive_schema.py tests/test_adaptive_workspace.py -q
git diff --check
```

### 完成标准

- product state refs-only；
- old composition tests 通过；
- 新增 refs 被测试覆盖；
- commit 完成。

## Phase 4: Adaptive Graph Loop MVP

### 目标

在 SkillFoundry composition 层实现最小 adaptive loop。

第一版使用 deterministic policy，不默认 live Codex。

### 建议图形

```text
initialize_adaptive_state
  -> propose_next_step
  -> execute_work_unit
  -> collect_observation
  -> correct_state
  -> route_after_correction
```

### Route

```text
continue
repair
redesign
review_required
final_verify
closure
failed
spec_revision_required
```

### MVP Policy

最小 deterministic policy 可以按以下规则：

- package 缺 `SKILL.md` -> contract 要求生成 skill entry；
- package 缺 `skillfoundry.bundle.json` -> contract 要求生成 manifest；
- verifier failed -> 生成 repair contract；
- repeated failure -> `review_required`；
- verifier passed -> `final_verify` 或 `closure`；
- spec / acceptance contradiction -> `spec_revision_required`。

### 建议新增

```text
src/forgeunit_skillfoundry/adaptive_graph.py
tests/test_adaptive_graph.py
```

实际位置应贴合现有 composition 层命名。

### 测试要求

覆盖：

- happy path；
- verifier fail -> repair；
- repeated failure -> review_required；
- missing manifest -> next-step contract；
- state correction refs 写入；
- graph state refs-only；
- no live Codex default。

### 验收命令

```bash
.venv/bin/python -m pytest tests/test_adaptive_graph.py tests/test_forgeunit_skillfoundry_composition.py -q
.venv/bin/python -m pytest tests/test_adaptive_schema.py tests/test_adaptive_workspace.py -q
git diff --check
```

### 完成标准

- adaptive loop 能完成至少 2 轮 deterministic flow；
- observation -> correction -> route 被 artifact 记录；
- repeated failure 不会无限循环；
- commit 完成。

## Phase 5: Bundle Manifest MVP

### 目标

让 Capability Bundle 有机器可读 manifest。

### 建议新增

```text
src/skillfoundry/bundle.py
tests/test_bundle_manifest.py
```

### 标准 ref

```text
package/skillfoundry.bundle.json
```

### Schema MVP

```json
{
  "schema_version": "skillfoundry.bundle.v1",
  "bundle_id": "example",
  "bundle_type": "prompt_only",
  "entrypoint": "SKILL.md",
  "capability_surface": {},
  "runtime_assets": [],
  "data_assets": [],
  "references": [],
  "environment": {},
  "permissions": {},
  "verification": {},
  "distribution": {}
}
```

### Allowed bundle types

```text
prompt_only
script_tool
code_runtime
knowledge_runtime
mcp_runtime
service_runtime
full_runtime_bundle
```

### 实现要求

- manifest 继承现有 `SchemaModel` pattern；
- unknown fields fail；
- entrypoint 和 asset refs 必须 path-safe；
- structured fields JSON-safe；
- 不要求第一版实现完整服务部署语义；
- 不要求真实 MCP runtime。

### 验收命令

```bash
.venv/bin/python -m pytest tests/test_bundle_manifest.py -q
git diff --check
```

### 完成标准

- manifest JSON round-trip；
- invalid bundle_type fail；
- unsafe path fail；
- public API 需要时再导出；
- commit 完成。

## Phase 6: Bundle Verifier MVP

### 目标

Verifier 开始理解 bundle manifest 和 profile 最小检查。

### 建议新增或扩展

```text
src/skillfoundry/bundle_verifier.py
tests/test_bundle_verifier.py
```

也可以扩展现有 verifier，但要避免把 `verifier.py` 变成无边界大文件。

### MVP checks

- `package/skillfoundry.bundle.json` 存在时必须 schema 合法；
- entrypoint 存在；
- declared runtime assets 存在；
- declared data assets 存在；
- declared references 存在；
- refs 不允许绝对路径或 parent traversal；
- `prompt_only` profile 检查 `package/SKILL.md`；
- `code_runtime` profile 支持声明 verification commands，但第一版默认只记录为 manual / required evidence，不直接开放任意 shell；
- package hash 仍覆盖整个 package tree；
- worker self-report 不作为 verifier pass 条件。

### Manifest 缺失兼容策略

第一版建议：

- manifest 缺失时保持旧 skill package 路径可运行；
- manifest 存在但非法时 verifier fail；
- 新 adaptive graph 可以优先要求生成 manifest。

### 验收命令

```bash
.venv/bin/python -m pytest tests/test_bundle_verifier.py tests/test_goal_harness_slice.py -q
.venv/bin/python -m pytest tests/test_bundle_manifest.py -q
git diff --check
```

### 完成标准

- verifier 能区分 manifest missing / invalid / valid；
- invalid declared refs fail；
- existing verifier behavior 不回归；
- commit 完成。

## Phase 7: Code Runtime Pilot

### 目标

用 deterministic Codexarium-like code-runtime 任务验证 adaptive loop。

注意：这是 clean-room pilot，不能读取或复制本地已有 Codexarium 代码。

### 最小产物

```text
package/SKILL.md
package/skillfoundry.bundle.json
package/runtime/
package/tests/
adaptive/capability_state.json
adaptive/next_step_contract_001.json
adaptive/observation_report_001.json
adaptive/state_correction_001.json
adaptive/decision_ledger.json
final_report.json or existing final report ref
```

runtime 可以是小型 Python CLI 或 Rust fixture。优先选择 repo 当前测试环境最稳定的实现，不为了展示而增加工具链风险。

### 测试要求

- 至少两轮 adaptive loop；
- 一次 observation -> correction -> next contract；
- manifest 声明 code runtime；
- verifier 能检查 runtime asset refs；
- final verifier passed；
- registry 只在 verified 后批准；
- final report refs-only。

### 验收命令

```bash
.venv/bin/python -m pytest tests/test_adaptive_graph.py tests/test_bundle_verifier.py tests/test_forgeunit_skillfoundry_composition.py -q
git diff --check
```

必要时增加专用 pilot 测试文件，例如：

```text
tests/test_code_runtime_pilot.py
```

### 完成标准

- deterministic code-runtime pilot 通过；
- 不依赖本地 Codexarium；
- 不默认调用 live Codex；
- commit 完成。

## Phase 8: Mini Knowledge Runtime Pilot

### 目标

用 Mini-EdaSkill-like 小型任务验证 knowledge-runtime。

不要复刻完整 EdaSkill。只验证：

- 文档输入；
- 转换 / 结构化；
- runtime KB；
- query tool；
- skill / bundle manifest；
- adaptive evidence；
- verifier。

### 最小产物

```text
package/data/runtime_kb.jsonl
package/data/runtime_kb.manifest.json
package/scripts/query_runtime_kb.py
package/references/workflow.md
package/SKILL.md
package/skillfoundry.bundle.json
```

也可以使用 SQLite，但第一版若 JSONL 足够验证流程，优先 JSONL，避免过早引入数据库复杂度。

### 测试要求

- synthetic docs source 不含私有资料；
- manifest hash / count 匹配；
- sample query 返回预期条目；
- query script 可运行；
- final report refs-only；
- raw source 不进入 public summary；
- adaptive loop 至少记录一个 knowledge-specific decision。

### 验收命令

```bash
.venv/bin/python -m pytest tests/test_mini_knowledge_runtime_pilot.py -q
.venv/bin/python -m pytest tests/test_adaptive_graph.py tests/test_bundle_verifier.py -q
git diff --check
```

### 完成标准

- 证明 reference-heavy capability bundle 可以通过 adaptive loop 生产；
- 记录哪些 primitives 可能应下沉到底座；
- commit 完成。

## Phase 9: Substrate Extraction Assessment

### 目标

基于 Phase 2-8 的实际实现，判断哪些抽象应下沉到 ContextForge / ForgeUnit，哪些应留在 SkillFoundry。

### 新增文档

```text
docs/ADAPTIVE_STEERING_SUBSTRATE_EXTRACTION_PLAN.md
```

### 必答问题

- `NextStepContract` 字段是否足够稳定？
- `ObservationReport` 是否可以成为 ForgeUnit work-unit report envelope？
- `CapabilityStateEstimate` 是通用 `StateEstimate`，还是 SkillFoundry domain state？
- 是否需要 `EvidenceReliability`？
- `DecisionLedger` 应进入 ContextForge ledger，还是留在 product app？
- ForgeUnit 是否应原生理解 next-step contract？
- ContextForge 是否应原生支持 state correction / checkpoint / replay？
- LangGraph route 是否足够薄？
- 哪些字段是 Capability Bundle 专属语义，不应下沉？

### 验收命令

```bash
git diff --check
.venv/bin/python -m pytest -q
```

### 完成标准

- 文档明确 keep / extract / defer；
- 不直接大改底座；
- full pytest 通过；
- commit 完成。

## 全局验证门

每个阶段至少运行该阶段目标测试和：

```bash
git diff --check
```

每完成两个阶段，运行：

```bash
.venv/bin/python -m pytest -q
```

最终必须运行：

```bash
.venv/bin/python -m pytest -q
git diff --check
git status --short
```

## 失败处理协议

如果某个阶段失败，不要直接扩大改动面。

先写出：

```text
Observation: 发生了什么？
Diagnosis: 为什么失败？
Options: 至少两条可选路线是什么？
Decision: 选择哪条路线？
Fallback: 如果仍失败，下一步是什么？
```

然后按以下优先级处理：

1. 修复局部实现；
2. 缩小 phase 范围；
3. 拆分测试和实现；
4. 写 redesign note；
5. 推迟到底座 extraction 阶段；
6. 只有在目标/红线不成立时才进入 spec revision。

## 禁止事项

本 goal 内不要做：

- full MCP platform；
- service deployment platform；
- long-term memory daemon；
- live Codex default path；
- full EdaSkill rebuild；
- full Codexarium rebuild；
- 读取本地私有 Codexarium 实现；
- 大规模 ContextForge / ForgeUnit public API rewrite；
- 把 raw prompt / raw transcript / full model output 写入 public state；
- 为了追求抽象而增加无法验证的 framework 层。

## 完成定义

这个 `/goal` 完成时，应满足：

- Phase 2-9 均完成或明确记录 defer 理由；
- adaptive schema / workspace / graph / bundle manifest / bundle verifier / pilots 均有测试；
- product state 和 final report 保持 refs-only；
- verifier 权威高于 worker self-report；
- deterministic pilots 通过；
- extraction assessment 完成；
- full pytest 通过；
- `git diff --check` 通过；
- 所有阶段 commit 清晰；
- docs index 指向最新执行计划和 extraction plan。
