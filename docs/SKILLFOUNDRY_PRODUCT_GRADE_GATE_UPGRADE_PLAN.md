# SkillFoundry Product-Grade Gate Upgrade Plan

最后更新：2026-05-26

## 文档用途

本文是基于 `codexarium-dialog-032` 产品级评审结论形成的 SkillFoundry
升级计划。

它不是 Codexarium 修复计划。Codexarium 只是一个暴露系统缺口的试验品。
真正要加固的是 SkillFoundry 如何把用户的人话需求转成产品级工程合同，并在
registry 前阻止 near-miss candidate 被误称为 product-grade 交付物。

核心结论：

```text
用户负责表达痛点。
FrontDesk 负责理解人话。
SkillFoundry 负责把人话编译成工程合同。
Builder 负责实现。
Verifier / ProductGate 负责不让半成品冒充产品。
```

## 背景问题

`codexarium-dialog-032` 证明当前主链路已经能生成复杂 Skill：

```text
FrontDesk
  -> ContextForge Goal Runtime
  -> ForgeUnit SkillFoundry vNext
  -> Codex exec command boundary
  -> Rust helper / references / examples / tests
  -> SkillFoundry Verifier
  -> Acceptance Coverage
  -> ContextForge Verification Bridge
  -> Registry
```

但是产品级评审发现，生成包仍然存在关键 near-miss：

- no-overwrite 语义没有覆盖同批 write plan 内部重复路径 / 重复标题；
- runtime helper 用手写字符串扫描解析 JSON，不适合产品级结构化输入；
- tests/fixtures 覆盖面不足；
- install / distribution 体验不完整；
- acceptance evidence 的 mode 命名不够白盒，第三方 reviewer 容易误读；
- registry 只有 `registered`，无法表达 candidate 与 product-grade 的差异。

这说明当前系统的问题不是“Codexarium 没修好”，而是：

```text
SkillFoundry 当前已经能生成复杂 candidate，
但还没有足够强的产品级交付门。
```

## 核心原则

### 1. FrontDesk 不问实现细节

FrontDesk 面向用户。用户不会提供实现级标准。

用户只会说：

```text
不要覆盖我的文件。
不要自动扫描我的电脑。
遇到冲突先问我。
我想把官方 PDF 整理成大模型好用的资料库。
```

用户不会说：

```text
请检测 same-plan duplicate target path。
请用 serde_json typed parser。
请覆盖 symlink parent / non-md target / CLI exit code matrix。
请区分 synthetic acceptance check 和 verifier result check。
```

因此 FrontDesk 只冻结用户可理解的语义合同。实现级标准必须由系统自动推断和注入。

### 2. 用户语义和工程合同分层

SkillFoundry 需要把每个需求分成三层：

```text
Layer 1: User Intent Contract
  用户能看懂，FrontDesk 输出。

Layer 2: Delivery Profile Contract
  SkillFoundry 推断，系统内部使用。

Layer 3: Product Acceptance Matrix
  Verifier / QA / ProductGate 使用。
```

示例：

```yaml
user_intent_contract:
  goal: "把用户提供的 compact evidence 整理成本地 wiki atomic notes"
  must_not:
    - "自动扫描电脑"
    - "读取聊天记录"
    - "覆盖已有笔记"
  desired_behavior:
    - "冲突时输出 proposal"
    - "用户确认后再写"

delivery_profile_contract:
  profiles:
    - codex_skill
    - runtime_helper_skill
    - local_file_safety_skill
    - structured_input_skill
  risk_domains:
    - filesystem_write
    - privacy_boundary
    - structured_json_input

product_acceptance_matrix:
  runtime:
    - duplicate path detection
    - duplicate title detection
    - path traversal rejection
    - absolute path rejection
    - symlink component rejection
    - CLI exit code coverage
  docs:
    - install instructions
    - examples
    - safety boundaries
  evidence:
    - synthetic fixtures only
    - no raw conversation
    - verifier freshness
```

### 3. Profile 驱动，而不是产品写死

Codexarium 暴露的问题应沉淀为通用 profile 能力，而不是 Codexarium 特例。

第一批 profile：

```text
codex_skill
prompt_only_skill
runtime_helper_skill
local_file_safety_skill
structured_input_skill
reference_heavy_skill
knowledge_db_skill
data_conversion_skill
mcp_connector_skill
service_bundle_skill
toolchain_skill
```

第一批 risk domain：

```text
filesystem_write
privacy_sensitive_input
structured_data_validation
external_document_ingestion
domain_knowledge_reliability
network_boundary
runtime_execution
long_running_service
distribution_package
```

## 目标架构

新增一个 SkillFoundry 层面的编译和质量门：

```text
FrontDesk User Spec
  -> Product Contract Compiler
  -> Delivery Profile Contract
  -> Product Acceptance Matrix
  -> Builder Task Pack
  -> Verifier / QA
  -> ProductGradeGate
  -> candidate_registered / product_grade_registered
```

### Product Contract Compiler

输入：

- `frontdesk/core_need_brief.json`
- `frontdesk/solution_plan.json`
- frozen `skill_spec.yaml`
- frozen `acceptance_criteria.yaml`
- user-visible constraints

输出：

```text
product_contract/delivery_profile.json
product_contract/risk_profile.json
product_contract/product_acceptance_matrix.json
product_contract/compiler_report.json
```

职责：

- 从用户语义中推断 delivery profiles；
- 从 must / must_not / expected outputs 中推断 risk domains；
- 根据 profiles + risk domains 注入产品级默认标准；
- 生成 Builder 需要实现的 runtime / docs / tests / evidence 要求；
- 生成 QA / ProductGate 需要检查的 acceptance matrix。

### ProductGradeGate

输入：

- verifier result；
- acceptance coverage；
- product acceptance matrix；
- generated package；
- optional reviewer report；
- ContextForge bridge evidence。

输出：

```text
qa/product_grade_report.json
qa/product_repair_packet.json
```

职责：

- 判断 candidate 是否达到 product-grade；
- 把 blocking / major findings 结构化成 repair packet；
- 阻止 product-grade registry promotion；
- 允许 near-miss candidate 被保留为 candidate。

### Registry 分级

现有 `registered` 容易过度宣称。需要增加分级：

```text
generated
verified
candidate_registered
product_grade_registered
published
deprecated
quarantined
```

`codexarium-dialog-032` 这类结果应是：

```yaml
status: candidate_registered
product_grade: false
reason: product_review_blocking_findings
```

只有 ProductGradeGate 通过后，才能进入：

```yaml
status: product_grade_registered
```

## MVP 范围

第一版只实现一个 profile 族：

```text
runtime_helper_skill
local_file_safety_skill
structured_input_skill
```

原因：

- Codexarium 已经暴露真实样本；
- 这类 Skill 最容易出现“看起来能跑但安全语义漏掉”的 near-miss；
- 后续 EdaSkill、MCP skill、knowledge DB skill 都可沿同一机制扩展。

### MVP 自动注入规则

当 Product Contract Compiler 检测到：

```text
runtime_helper_skill + local_file_safety_skill
```

且用户语义中出现：

```text
不覆盖 / no overwrite / conflict proposal / explicit root / 写入本地文件
```

必须注入：

```yaml
required_runtime_behaviors:
  - existing target path conflict detection
  - existing title conflict detection
  - same-plan duplicate path detection
  - same-plan duplicate title detection
  - path traversal rejection
  - absolute path rejection
  - backslash path rejection
  - non-markdown target rejection
  - symlink component rejection
  - nonexistent root handling
  - explicit conflict proposal output
  - no write on validation-only command

required_tests:
  - valid fixture
  - existing path conflict fixture
  - existing title conflict fixture
  - duplicate path fixture
  - duplicate title fixture
  - path traversal fixture
  - absolute path fixture
  - backslash fixture
  - non-md target fixture
  - symlink fixture
  - invalid compact note fixture
  - malformed manifest fixture
  - CLI ok exit code
  - CLI invalid exit code
  - CLI conflict exit code
```

当检测到：

```text
structured_input_skill
```

且出现：

```text
JSON manifest / schema / evidence / compact notes / write plan
```

必须注入：

```yaml
required_structured_input_behaviors:
  - typed parser or equivalent structured parser
  - schema/version validation
  - required field validation
  - duplicate ID detection
  - referenced ID existence check
  - deterministic JSON output serialization
  - malformed JSON rejection
```

注意：规则不应写死 Rust / serde。对 Rust，可以推荐 `serde_json`；对 Python，可以推荐 `pydantic` 或 `jsonschema`；对 Node，可以推荐 `zod` 或 JSON Schema。核心是“结构化解析和明确 schema”，不是某个库。

## Evidence Semantics 升级

当前 `coverage_mode: verifier_check` 同时承担真实 verifier check 和 synthetic acceptance check，容易误导第三方 reviewer。

需要拆分：

```text
verifier_result_check
acceptance_synthetic_static_check
runtime_fixture_check
runtime_command_check
source_code_behavior_check
manual_review_check
llm_reviewer_check
required_evidence_check
```

每个 coverage item 应包含：

```json
{
  "coverage_mode": "runtime_command_check",
  "evaluator": "skillfoundry.product_gate.runtime_matrix",
  "criterion_id": "PG-RUNTIME-CLI-CONFLICT",
  "command_ref": "qa/runtime_checks/conflict_command.json",
  "expected_exit_code": 3,
  "actual_exit_code": 3,
  "evidence_refs": [
    "qa/runtime_checks/conflict_stdout.json",
    "package/tests/fixtures/conflict_plan.json"
  ]
}
```

第三方 reviewer 应能不读代码就看懂：

- 谁检查的；
- 检查了什么；
- 证据在哪里；
- 是否执行了真实命令；
- 结果是否与当前 package hash 绑定。

## Work Packages

### WP1: Product Contract Schema

新增 schema：

```text
src/skillfoundry/product_contract.py
tests/test_product_contract.py
```

核心对象：

```text
DeliveryProfileContract
RiskProfile
ProductAcceptanceMatrix
ProductAcceptanceItem
ProductContractCompilerReport
ProductGradeReport
ProductRepairPacket
```

验收：

- schema round-trip；
- refs-only；
- no raw conversation；
- unknown profile fail closed or warning by policy；
- deterministic hash。

### WP2: Product Contract Compiler MVP

新增：

```text
src/skillfoundry/product_contract_compiler.py
tests/test_product_contract_compiler.py
```

第一版使用 deterministic keyword / structured-field inference，不调用 LLM。

输入：

- `skill_spec.yaml`
- `acceptance_criteria.yaml`
- `frontdesk/solution_plan.json`

输出：

- `product_contract/delivery_profile.json`
- `product_contract/product_acceptance_matrix.json`

验收：

- Codexarium-like spec -> runtime helper + local file safety + structured input；
- EdaSkill-like spec -> reference heavy + data conversion + domain reliability；
- prompt-only spec -> 不注入 runtime matrix；
- no raw user text in graph state。

### WP3: Runtime Helper Product Matrix

新增 runtime matrix evaluator：

```text
src/skillfoundry/product_runtime_checks.py
tests/test_product_runtime_checks.py
```

第一版检查：

- package 是否包含 runtime；
- tests/fixtures 是否覆盖 matrix；
- cargo / pytest / node test command 是否存在；
- command evidence 是否执行；
- duplicate path/title fixture 是否存在并失败；
- CLI exit code 是否符合预期。

验收：

- 032 这类 candidate 应在 ProductGradeGate 失败；
- 加固后的 candidate 才能 product-grade pass。

### WP4: Evidence Mode Refactor

调整 acceptance coverage result：

- 拆分 synthetic static check 和 verifier result check；
- 保持向后兼容读取旧字段；
- 新增 provenance 字段；
- ContextForge bridge 继续验证 freshness。

验收：

- 旧测试不破；
- 新结果不再让第三方 reviewer 误以为 synthetic check 来自 verifier result；
- registry provenance 中可区分 verifier / acceptance / product gate。

### WP5: ProductGradeGate

新增：

```text
src/skillfoundry/product_grade_gate.py
tests/test_product_grade_gate.py
```

职责：

- 汇总 verifier、acceptance、product matrix、reviewer report；
- 输出 `qa/product_grade_report.json`；
- blocking finding -> `product_grade: false`；
- 生成 `qa/product_repair_packet.json`。

验收：

- no blocking + required matrix pass -> product_grade true；
- blocking runtime safety issue -> product_grade false；
- report refs/hash 可验证；
- no worker self-report as acceptance。

### WP6: Registry Promotion Split

调整 registry：

- 保留现有 `registered` 行为兼容；
- 新增 `candidate_registered`；
- 新增 `product_grade_registered`；
- ProductGradeGate 失败时仍可记录 candidate，但不能 product-grade promotion。

验收：

- 032-like result -> candidate_registered；
- product gate pass -> product_grade_registered；
- registry decision 包含 product grade refs。

### WP7: Reviewer Repair Loop

把 reviewer findings 转成 repair packet：

```json
{
  "finding_id": "P0-runtime-intra-plan-conflict",
  "severity": "blocking",
  "affected_profiles": [
    "runtime_helper_skill",
    "local_file_safety_skill"
  ],
  "required_fix": "detect same-plan duplicate target path and title conflicts",
  "required_tests": [
    "duplicate path fixture",
    "duplicate title fixture",
    "CLI conflict exit code"
  ]
}
```

验收：

- reviewer report 可结构化；
- repair worker 不需要原始 reviewer 长文本；
- repair 后重新走 ProductGradeGate。

当前 MVP 已实现：

```text
src/skillfoundry/product_repair_loop.py
tests/test_product_repair_loop.py
```

新增结构化输入：

```text
qa/product_reviewer_report.json
```

新增/扩展 schema：

```text
ProductReviewerReport
ProductRepairItem
ProductRepairPacket.repair_items
ProductRepairPacket.source_refs
ProductRepairPacket.trust_boundaries
```

`ProductRepairPlanner` 会读取：

```text
qa/product_grade_report.json
qa/product_reviewer_report.json   # optional
```

并输出：

```text
qa/product_repair_packet.json
```

关键约束：

- product gate finding 和 reviewer finding 会被 namespace：
  `product_gate:<finding_id>` / `reviewer_report:<finding_id>`；
- 只把 `major` / `blocking` finding 编译为 repair item；
- reviewer report 只接受结构化短 finding，不允许 `raw_prompt`、`raw_transcript`、`messages` 等原始上下文字段；
- repair packet 明确声明：
  `raw_prompt_included=false`、`raw_transcript_included=false`、`raw_reviewer_text_included=false`；
- 如果缺少 `qa/product_grade_report.json`，planner fail-closed，生成 blocking repair item，要求先运行 ProductGradeGate。

## 实施顺序

推荐短期顺序：

```text
Phase 0: 文档和测试样本冻结
Phase 1: Product Contract Schema
Phase 2: Compiler MVP
Phase 3: Runtime Helper Matrix
Phase 4: ProductGradeGate
Phase 5: Registry Promotion Split
Phase 6: Evidence Mode Refactor
Phase 7: Reviewer Repair Loop
Phase 8: Codexarium candidate rerun
```

Phase 0 / 1 / 2 可以很快落地；Phase 3 / 4 是核心价值；Phase 5 / 6 解决可信表达；Phase 7 才进入自动修复闭环。

## 当前实现状态

截至 2026-05-26，第一版已经落地以下内容：

```text
Implemented:
  - WP1 Product Contract Schema
  - WP2 Product Contract Compiler MVP
  - WP3 Runtime Helper Product Matrix 的命令执行骨架
  - WP4 Evidence Mode Refactor 的 acceptance result MVP
  - WP5 ProductGradeGate MVP
  - WP6 Registry Promotion Split 的 MVP
  - WP7 Reviewer Repair Loop 的 deterministic MVP
  - reference_heavy / data_conversion / knowledge_db / service_bundle 的静态产品证据门禁 MVP

Not implemented yet:
  - 针对 reference_heavy / knowledge_db / service_bundle 等 profile 的真实执行命令门禁
  - MCP connector / toolchain 等 profile 的专用产品门禁
```

当前 runtime matrix runner 使用候选包声明的：

```text
package/skillfoundry.runtime_checks.json
```

作为可执行产品检查计划，并把执行证据写入：

```text
qa/product_runtime_check_result.json
qa/runtime_checks/*.stdout.txt
qa/runtime_checks/*.stderr.txt
```

这让 ProductGradeGate 能够区分：

```text
candidate has docs/tests text that claims behavior
candidate actually declares and passes executable product checks
```

Acceptance coverage result 现在保留旧字段：

```text
coverage_mode
```

同时新增：

```text
evidence_mode
evaluator
evidence_provenance
```

用于区分：

```text
verifier_result_check
acceptance_synthetic_static_check
runtime_fixture_check
runtime_command_check
required_evidence_check
qa_report_check
manual_review_check
```

这样第三方 reviewer 不再需要猜测 `coverage_mode: verifier_check`
到底来自真实 verifier result，还是来自 SkillFoundry acceptance 的 synthetic static check。

Registry 现在区分：

```text
add_verified / add_candidate
  -> registry_status: candidate_registered

add_product_grade
  -> requires qa/product_grade_report.json
  -> requires product_grade=true
  -> registry_status: product_grade_registered
```

ProductGradeGate 现在还会对以下 profile 执行静态证据门禁：

```text
reference_heavy_skill
  - PG-REFERENCE-SOURCE-INVENTORY
  - requires source inventory and source hash evidence

data_conversion_skill
  - PG-REFERENCE-CONVERSION-PROVENANCE
  - requires conversion commands, tool versions, and failed-source handling

knowledge_db_skill
  - PG-REFERENCE-CITATION-MAPPING
  - requires citation/source mapping and retrieval smoke evidence

service_bundle_skill
  - PG-SERVICE-STARTUP-CONTRACT
  - PG-SERVICE-HEALTHCHECK
  - PG-SERVICE-SHUTDOWN-BOUNDARY
```

这些检查仍然是 MVP 级 required-evidence gate，不等价于真实启动服务、
真实构建知识库或真实跑检索评测。它们的作用是让缺少核心证据的候选包
不能进入 product-grade promotion。

## 成功标准

第一阶段成功标准：

```text
给定 codexarium-dialog-032 生成包，
ProductGradeGate 必须判定 product_grade=false，
并给出结构化 blocking finding：
same-plan duplicate path/title conflict is not covered.
```

第二阶段成功标准：

```text
给定 repair 后的新 candidate，
ProductGradeGate 必须要求 runtime matrix 全部通过，
并将 registry promotion 从 candidate_registered 提升到 product_grade_registered。
```

第三阶段成功标准：

```text
给定 EdaSkill-like 需求，
Product Contract Compiler 必须自动推断 reference_heavy_skill + data_conversion_skill，
并注入 source document inventory、conversion provenance、citation/source mapping、
retrieval smoke tests、random sample factual QA 等验收项。
```

## 非目标

短期不做：

- 重写 FrontDesk；
- 让用户回答实现级问题；
- 直接修改 ContextForge / ForgeUnit 公共 API；
- 把所有 profile 一次性做完；
- 追求完全自动发布；
- 对 Codexarium 原版实现做任何泄漏式比较。

短期目标是让 SkillFoundry 拥有第一版产品判断力。

## 关键判断

这次升级的真正目的不是提高某个 Skill 的质量，而是提高 SkillFoundry 的交付判断力。

```text
FrontDesk 不能变成技术审问器。
用户不需要懂工程验收。
SkillFoundry 必须替用户承担产品级工程标准。
```

如果这层做好，后续任意复杂需求都会被系统自动转成更严肃的交付合同：

- Codexarium -> local file safety runtime；
- EdaSkill -> reference-heavy knowledge runtime；
- MCP skill -> connector/service boundary；
- data conversion skill -> source/provenance/conversion QA；
- service bundle -> runtime, install, health check, rollback, security profile。

这就是 SkillFoundry 从“能生成 skill”升级为“AI 时代铲子工厂”的关键一步。
