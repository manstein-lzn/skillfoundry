# Adaptive Steering Implementation Plan

最后更新：2026-05-24

## 文档用途

本文是把 `AGENT_WORK_SUBSTRATE_VISION.md` 和 `SKILLFOUNDRY_CAPABILITY_BUNDLE_VISION.md` 落到 SkillFoundry 当前代码库的开发计划。

## 当前实现状态

截至 2026-05-24：

- Phase 0 文档基线已落地；
- Phase 1 Adaptive Schema MVP 已落地；
- Phase 2 Adaptive Workspace Artifacts 已落地；
- Phase 3 Refs-only Product State Integration 已落地；
- Phase 4 Adaptive Graph Loop MVP 已落地；
- Phase 5 Bundle Manifest MVP 已落地；
- Phase 6 Bundle Verifier MVP 已落地；
- Phase 7 及之后仍未实现。

已实现的 Phase 1 代码入口：

```text
src/skillfoundry/adaptive.py
tests/test_adaptive_schema.py
src/skillfoundry/adaptive_workspace.py
tests/test_adaptive_workspace.py
src/forgeunit_skillfoundry/state.py
src/forgeunit_skillfoundry/report.py
src/forgeunit_skillfoundry/adaptive_graph.py
tests/test_forgeunit_skillfoundry_composition.py
tests/test_adaptive_graph.py
src/skillfoundry/bundle.py
src/skillfoundry/bundle_verifier.py
tests/test_bundle_manifest.py
tests/test_bundle_verifier.py
```

当前已通过验证：

```bash
.venv/bin/python -m pytest tests/test_adaptive_schema.py -q
.venv/bin/python -m pytest tests/test_adaptive_schema.py tests/test_adaptive_workspace.py -q
.venv/bin/python -m pytest tests/test_forgeunit_skillfoundry_composition.py -q
.venv/bin/python -m pytest tests/test_adaptive_graph.py tests/test_forgeunit_skillfoundry_composition.py -q
.venv/bin/python -m pytest tests/test_bundle_manifest.py tests/test_bundle_verifier.py -q
.venv/bin/python -m pytest tests/test_bundle_verifier.py tests/test_goal_harness_slice.py tests/test_bundle_manifest.py -q
.venv/bin/python -m pytest -q
git diff --check
```

目标不是一次性实现完整通用 agent substrate，也不是立刻修改 ContextForge / ForgeUnit 的公共 API。

目标是用最小、可验证、可回滚的方式，在 SkillFoundry 层先实现一版 adaptive steering loop：

```text
Capability State Estimate
  -> Next-Step Contract
  -> ForgeUnit Work Unit
  -> Observation Report
  -> State Correction
  -> route continue / repair / redesign / reviewer / closure
```

该计划完成后，SkillFoundry 将从单纯 plan-and-execute 的 Codex Skill 工厂，演进为第一版卡尔曼式 Capability Bundle 工厂。

## 总体判断

短期不直接改 ContextForge / ForgeUnit 核心实现。

原因：

- 当前底座已经能支撑 workspace、refs-only 状态、ForgeUnit command boundary、LangGraph route、verifier、repair、registry。
- Adaptive steering 的字段和边界还需要通过 SkillFoundry 真实场景验证。
- 过早把 primitives 下沉到 ContextForge / ForgeUnit，容易设计出空泛抽象。

正确节奏：

```text
Prototype in SkillFoundry.
Validate with Codexarium / Mini-EdaSkill-like pilots.
Identify stable primitives.
Generalize into ContextForge / ForgeUnit.
Keep LangGraph thin.
```

## 分层落点

### SkillFoundry

第一版实现位置。

负责：

- capability-bundle 领域 schema；
- adaptive steering artifacts；
- workspace refs；
- product state / evidence summary refs-only 输出；
- SkillFoundry graph loop；
- bundle manifest；
- profile-specific verifier。

### ForgeUnit

第一版不改核心。

SkillFoundry 将 `NextStepContract` 作为普通输入 artifact 交给现有 ForgeUnit command boundary。

后续如果稳定，再考虑将 `NextStepContract`、`ObservationReport`、work-unit envelope 下沉到 ForgeUnit。

### ContextForge

第一版不改核心。

SkillFoundry 先把 `CapabilityStateEstimate`、`ObservationReport`、`StateCorrection`、`DecisionLedger` 作为 workspace refs-only artifacts 保存。

后续如果稳定，再考虑将 `StateEstimate`、`EvidenceReliability`、`StateCorrection`、`DecisionLedger` 下沉到 ContextForge。

### LangGraph

不改库。

只在 SkillFoundry composition 层增加 adaptive loop 拓扑。

LangGraph 只负责 route，不拥有 state estimate、evidence reliability 或 domain quality 语义。

## 非目标

本计划不做：

- 完整 MCP 平台；
- 服务部署平台；
- 通用知识库构建平台；
- 多租户平台；
- 后台 scheduler；
- long-term memory daemon；
- 对 ContextForge / ForgeUnit 的公共 API 重构；
- 真实 EdaSkill 全量复刻；
- 默认 live Codex 调用。

真实复杂产品验证放在后续 pilot 阶段。

## Phase 0: 文档基线

目标：

把当前 vision 和 implementation plan 固定成后续开发依据。

范围：

- `docs/AGENT_WORK_SUBSTRATE_VISION.md`
- `docs/SKILLFOUNDRY_CAPABILITY_BUNDLE_VISION.md`
- `docs/ADAPTIVE_STEERING_IMPLEMENTATION_PLAN.md`
- `README.md`
- `docs/README.md`

验收：

```bash
git diff --check
```

完成标准：

- docs 入口能看到 substrate vision、Capability Bundle vision、本计划；
- 文档明确 SkillFoundry 是组合应用，不是底座；
- 文档明确短期先在 SkillFoundry 层实现，不先大改 ContextForge / ForgeUnit。

## Phase 1: Adaptive Schema MVP

目标：

把 adaptive steering 从愿景变成可测试 schema。

建议新增：

```text
src/skillfoundry/adaptive.py
tests/test_adaptive_schema.py
```

核心 schema：

```text
CapabilityStateEstimate
NextStepContract
ObservationReport
StateCorrection
DecisionRecord
DecisionLedger
```

建议字段：

```text
CapabilityStateEstimate:
  schema_version
  job_id
  iteration
  objective
  current_phase
  known_good
  known_bad
  known_unknowns
  current_risks
  latest_verification_status
  next_best_step
  confidence
  metadata

NextStepContract:
  schema_version
  job_id
  iteration
  current_state_ref
  next_objective
  why_now
  allowed_scope
  visible_refs
  expected_outputs
  exit_criteria
  stop_conditions
  estimated_followups
  risk_if_too_large
  risk_if_too_small
  metadata

ObservationReport:
  schema_version
  job_id
  iteration
  contract_ref
  produced_artifacts
  changed_refs
  commands_run
  tests_run
  failures
  worker_claims
  verifier_evidence
  new_unknowns
  recommended_next_steps
  metadata

StateCorrection:
  schema_version
  job_id
  iteration
  previous_state_ref
  observation_ref
  corrected_state_ref
  decision
  rationale
  next_route
  metadata

DecisionRecord:
  decision_id
  iteration
  context
  options
  chosen_option
  rationale
  risk
  expected_evidence
  fallback
  reviewer
  created_at

DecisionLedger:
  schema_version
  job_id
  decisions
```

Validation rules：

- reject unknown fields；
- required strings non-empty；
- refs must be safe relative paths；
- list fields must be JSON-safe；
- forbidden raw fields rejected:
  - `conversation`
  - `messages`
  - `prompt`
  - `raw_prompt`
  - `transcript`
  - `raw_transcript`
  - `model_output`
  - `raw_model_output`

验收：

```bash
.venv/bin/python -m pytest tests/test_adaptive_schema.py -q
git diff --check
```

完成标准：

- 所有 schema 可 JSON round trip；
- unsafe refs 被拒绝；
- forbidden raw fields 被拒绝；
- 当前没有 graph / worker 行为变更。

## Phase 2: Adaptive Workspace Artifacts

目标：

让 adaptive schema 在 JobWorkspace 中成为稳定 artifacts。

建议新增或扩展：

```text
src/skillfoundry/adaptive_workspace.py
tests/test_adaptive_workspace.py
```

标准 refs：

```text
adaptive/capability_state.json
adaptive/next_step_contract_{iteration:03d}.json
adaptive/observation_report_{iteration:03d}.json
adaptive/state_correction_{iteration:03d}.json
adaptive/decision_ledger.json
```

Helper：

```text
write_capability_state_estimate
read_capability_state_estimate
write_next_step_contract
write_observation_report
write_state_correction
append_decision_record
read_decision_ledger
```

验收：

```bash
.venv/bin/python -m pytest tests/test_adaptive_workspace.py -q
git diff --check
```

完成标准：

- artifacts 写入路径安全；
- iteration refs 稳定；
- decision ledger 可追加；
- artifact manifest 是否注册由本阶段明确策略决定；
- raw prompt / raw transcript 不进入任何 public summary。

## Phase 3: Refs-Only Product State Integration

目标：

把 adaptive artifacts 纳入 SkillFoundry product state / evidence summary，但只暴露 refs 和少量状态，不暴露 raw body。

可能修改：

```text
src/forgeunit_skillfoundry/state.py
src/forgeunit_skillfoundry/report.py
src/forgeunit_skillfoundry/product.py
tests/test_forgeunit_skillfoundry_composition.py
```

输出应包含：

```text
refs:
  adaptive_state
  latest_next_step_contract
  latest_observation_report
  latest_state_correction
  decision_ledger

contextforge / adaptive summary:
  latest_iteration
  latest_route
  latest_decision
  latest_verification_status
```

验收：

```bash
.venv/bin/python -m pytest tests/test_forgeunit_skillfoundry_composition.py -q
git diff --check
```

完成标准：

- product state 是 refs-only；
- serialized state 不包含 raw prompt、raw transcript、worker full output；
- existing composition tests 继续通过。

## Phase 4: Adaptive Graph Loop MVP

目标：

在 SkillFoundry composition 层增加最小 adaptive loop。

第一版不需要智能 steering agent，先使用 deterministic policy。

建议图形：

```text
initialize_adaptive_state
  -> propose_next_step
  -> execute_work_unit
  -> collect_observation
  -> correct_state
  -> route_after_correction
```

Route：

```text
continue
repair
redesign
review_required
final_verify
failed
```

Policy MVP：

- package 缺 `SKILL.md` -> next step 要求生成 skill entry；
- package 缺 bundle manifest -> next step 要求生成 manifest；
- verifier failed -> next step 生成 repair contract；
- repeated failure -> review_required；
- verifier passed -> final closure。

建议测试：

```text
tests/test_adaptive_graph.py
```

验收：

```bash
.venv/bin/python -m pytest tests/test_adaptive_graph.py tests/test_forgeunit_skillfoundry_composition.py -q
git diff --check
```

完成标准：

- happy path 能完成；
- verifier fail 能生成 repair next-step；
- repeated failure 能进入 review_required；
- state correction refs 写入；
- graph state 保持 refs-only。

## Phase 5: Bundle Manifest MVP

目标：

让 Capability Bundle 有机器可读 manifest。

建议新增：

```text
src/skillfoundry/bundle.py
tests/test_bundle_manifest.py
```

标准 ref：

```text
package/skillfoundry.bundle.json
```

Schema MVP：

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

Allowed bundle types：

```text
prompt_only
script_tool
code_runtime
knowledge_runtime
mcp_runtime
service_runtime
full_runtime_bundle
```

验收：

```bash
.venv/bin/python -m pytest tests/test_bundle_manifest.py -q
git diff --check
```

完成标准：

- manifest JSON round trip；
- entrypoint / runtime refs path-safe；
- bundle_type 枚举校验；
- unknown fields fail。

## Phase 6: Bundle Verifier MVP

目标：

Verifier 开始理解 bundle manifest 和 profile 最小检查。

建议新增或扩展：

```text
src/skillfoundry/bundle_verifier.py
tests/test_bundle_verifier.py
```

MVP checks：

- `package/skillfoundry.bundle.json` 存在时必须 schema 合法；
- entrypoint 存在；
- declared runtime assets 存在；
- refs 不允许绝对路径或 parent traversal；
- `prompt_only` profile 检查 `package/SKILL.md` frontmatter；
- `code_runtime` profile 支持声明 verification commands，但第一版可先记录为 required/manual evidence，避免开放任意 shell。

验收：

```bash
.venv/bin/python -m pytest tests/test_bundle_verifier.py tests/test_goal_harness_slice.py -q
git diff --check
```

完成标准：

- manifest 缺失时按当前兼容策略处理；
- manifest 存在但无效时 verifier fail；
- package hash 仍覆盖整个 package tree；
- worker self-report 仍不是验收。

## Phase 7: Code Runtime Pilot

目标：

用 Codexarium-like code-runtime 任务验证 adaptive loop。

建议先做 deterministic / fake worker pilot，不默认 live Codex。

最小产物：

- `package/SKILL.md`
- `package/skillfoundry.bundle.json`
- code runtime mock 或小型 Rust/Python CLI；
- tests；
- adaptive artifacts；
- final verification；
- refs-only final report。

验收：

```bash
.venv/bin/python -m pytest tests/test_adaptive_graph.py tests/test_bundle_verifier.py tests/test_forgeunit_skillfoundry_composition.py -q
```

完成标准：

- 至少两轮 adaptive loop；
- 一次 observation -> correction -> next contract；
- final verifier passed；
- registry 只在 verified 后批准。

## Phase 8: Mini Knowledge Runtime Pilot

目标：

用 Mini-EdaSkill-like 小型任务验证 knowledge-runtime。

不要一上来复刻完整 EdaSkill。

最小产物：

- 小型公开 / synthetic docs；
- `package/data/runtime_kb.sqlite` 或 `runtime_kb.jsonl`；
- `package/data/runtime_kb.manifest.json`；
- `package/scripts/query_runtime_kb.py`；
- `package/references/workflow.md`；
- `package/SKILL.md`；
- sample query test；
- adaptive artifacts；
- final verifier。

验收：

- manifest hash 匹配；
- document count 匹配；
- sample query 返回；
- query script 可运行；
- final report refs-only；
- raw source 不进入 public summary。

完成标准：

- 证明 reference-heavy capability bundle 可以通过 adaptive loop 生产；
- 记录哪些 primitives 应下沉到 ContextForge / ForgeUnit。

## Phase 9: 下沉评估

目标：

在 SkillFoundry pilot 后判断哪些抽象应移动到底座。

评估问题：

- `NextStepContract` 字段是否稳定？
- `ObservationReport` 是否有通用 envelope？
- `StateEstimate` 是强 schema 还是 domain JSON？
- 是否需要 `EvidenceReliability`？
- `DecisionLedger` 是否应进入 ContextForge ledger？
- ForgeUnit 是否应原生理解 next-step contract？
- LangGraph route 是否足够薄？

产物：

```text
docs/ADAPTIVE_STEERING_SUBSTRATE_EXTRACTION_PLAN.md
```

完成标准：

- 明确哪些留在 SkillFoundry；
- 明确哪些下沉 ContextForge；
- 明确哪些下沉 ForgeUnit；
- 明确 LangGraph 不承载哪些语义。

## 推荐开发顺序

第一批 commit：

```text
Phase 0: docs baseline
```

第二批 commit：

```text
Phase 1: adaptive schema MVP
```

第三批 commit：

```text
Phase 2: workspace artifacts
```

第四批 commit：

```text
Phase 3-4: refs-only integration + adaptive graph MVP
```

第五批 commit：

```text
Phase 5-6: bundle manifest + verifier MVP
```

第六批 commit：

```text
Phase 7-8: pilots
```

## 当前下一步

建议立即执行 Phase 0。

之后进入 Phase 1，先实现：

```text
src/skillfoundry/adaptive.py
tests/test_adaptive_schema.py
```

第一版只做 schema，不接 graph、不接 worker、不改 ContextForge / ForgeUnit。

这是把愿景转成可测试 contract 的最小动作。
