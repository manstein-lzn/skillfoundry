# SkillFoundry Capability Bundle Vision

最后更新：2026-05-24

## 文档地位

本文是 SkillFoundry 当前阶段的产品宪法。

它固定的是长期方向，而不是短期实现清单。后续实现可以演进，目录可以调整，worker 可以替换，Codex / Claude / GPT 模型能力也会继续变化；但只要项目仍叫 SkillFoundry，就应当遵守本文定义的产品判断、边界原则和验收哲学。

本文不声称当前代码已经完整实现所有能力。当前实现状态仍以 `README.md`、`docs/SYSTEM_MAP.md`、`docs/FORGEUNIT_SKILLFOUNDRY_COMPOSITION.md` 和测试结果为准。

本文回答一个更根本的问题：

```text
SkillFoundry 到底在生产什么？
```

答案不是 prompt，也不是普通 Codex Skill 模板。

答案是：

```text
SkillFoundry 生产 AI-native Capability Bundle。
Codex 是操作者。
Skill 是领域入口。
Capability Bundle 是可安装、可运行、可验证、可复用的持久化工具。
```

## 一句话愿景

SkillFoundry 要成为 AI 时代的生产力工具铸造厂。

它把可重复的人类工作、领域知识、工程流程和执行工具，固化成可被 Codex 等强 agent 调用的能力包。

```text
Codex is the universal AI workbench.
A Skill is the domain-specific doorway.
SkillFoundry turns arbitrary needs into verified AI-native capability bundles.
```

中文表述：

```text
Codex 是通用 AI 工作台。
Skill 是领域能力入口。
SkillFoundry 把任意需求铸造成经过验证的 AI 原生能力包。
```

## 核心判断

大模型的能力已经溢出。GPT-5.5、Codex exec、Codex SDK thread 这类强 agent 已经有能力完成长时间复杂工程任务，包括：

- 需求澄清；
- 领域资料理解；
- 复杂文档转换；
- 代码开发；
- Rust / Python / Go / Node / SKILL 等语言实现；
- 数据库构建；
- 查询工具开发；
- MCP server 包装；
- 测试与调试；
- 交付文档整理；
- 多轮修复。

真正稀缺的不是一次性智能劳动，而是把一次性智能劳动沉淀为可复用工具的能力。

SkillFoundry 的价值不在于替强模型思考所有细节，而在于把强模型放进一个可冻结、可执行、可验证、可审计、可分发的工程体系中。

因此：

```text
强模型负责复杂创造和工程执行。
SkillFoundry 负责把需求变成工程合同。
ContextForge 负责边界、证据、上下文、缓存和 checkpoint。
ForgeUnit 负责受控 work-unit harness。
Codex exec / strong worker 负责实际构建。
Verifier 负责真伪。
Registry 负责沉淀和复用。
```

## 不是 Prompt 工厂

SkillFoundry 不是 `SKILL.md` 生成器。

SkillFoundry 也不是把 prompt 写得更长、更精致的工具。

在轻量场景下，最终产物可以只有一份 `SKILL.md` 和少量 references；但这只是 Capability Bundle 的最小形态，不是 SkillFoundry 的能力上限。

专业场景中的 skill 往往需要：

- 领域数据库；
- 结构化 reference corpus；
- 查询脚本；
- 编译产物；
- 本地服务；
- MCP server；
- API wrapper；
- fixtures；
- oracle；
- verification checklist；
- 环境探测脚本；
- install / healthcheck / smoke test；
- handoff 文档；
- 权限与数据边界声明。

因此，SkillFoundry 的最终产物应该被理解为：

```text
Skill = AI-Native Capability Bundle
```

而不是：

```text
Skill = prompt
```

## Capability Bundle 定义

Capability Bundle 是一个面向 AI agent 的领域能力单元。

它必须同时具备两类接口。

第一类是 Agent Interface：

- Codex / agent 何时应该触发它；
- agent 应该先读哪些文档；
- agent 可以调用哪些工具；
- 哪些资料是官方事实；
- 哪些内容只是本地假设；
- 哪些风险必须标为 adapter-bound；
- 什么时候必须停下来澄清；
- 如何使用查询工具、MCP 或本地服务；
- 什么状态才能声称完成。

第二类是 Runtime Interface：

- CLI；
- API；
- MCP server；
- 数据库；
- 编译产物；
- 查询脚本；
- 转换 pipeline；
- tests；
- healthcheck；
- build / install / smoke 命令。

一个能力包可以非常小，也可以接近一个完整应用服务分发包。

实现形态不设限，运行契约必须严格。

```text
No arbitrary implementation limit.
Strict runtime contract.
```

## 标准 Bundle 结构

推荐的通用结构如下：

```text
package/
  SKILL.md
  skillfoundry.bundle.json
  README.md
  references/
  scripts/
  tests/
  data/
  assets/
  src/
  bin/
  service/
  mcp/
  examples/
  verification/
```

不是每个 bundle 都必须包含所有目录。

但每个 bundle 必须清楚说明：

- 它的入口是什么；
- 它暴露哪些能力；
- 它依赖哪些运行环境；
- 它包含哪些 runtime assets；
- 它需要哪些权限；
- 它如何安装；
- 它如何运行；
- 它如何停止；
- 它如何自检；
- 它如何验证；
- 它是否可以分发；
- 它是否包含私有资料；
- 它如何升级。

## Bundle Manifest

SkillFoundry 应当逐步引入正式的 bundle manifest：

```text
package/skillfoundry.bundle.json
```

该 manifest 是 Capability Bundle 的机器可读 contract。

示例结构：

```json
{
  "schema_version": "skillfoundry.bundle.v1",
  "bundle_id": "layout-engineer-assistant",
  "bundle_type": "full_runtime_bundle",
  "entrypoint": "SKILL.md",
  "capability_surface": {
    "codex_skill": {
      "entry": "SKILL.md"
    },
    "cli_tools": [],
    "api_services": [],
    "mcp_servers": [],
    "query_tools": []
  },
  "runtime_assets": [],
  "data_assets": [],
  "references": [],
  "environment": {},
  "permissions": {},
  "verification": {},
  "distribution": {}
}
```

manifest 的职责：

- 让 Codex 知道这个 bundle 有什么能力；
- 让 Verifier 知道应该验收什么；
- 让 Registry 知道是否能注册；
- 让用户知道如何安装和使用；
- 让后续系统知道如何接入 MCP、服务、数据库或 CLI；
- 让版本升级和兼容性检查有事实依据。

## Capability Surface

Capability Surface 描述一个 bundle 向 agent 和机器暴露的能力。

一个 bundle 可以暴露多种 surface：

```yaml
capability_surface:
  codex_skill:
    entry: SKILL.md
  cli:
    - name: query-kb
      command: python scripts/query_kb.py
  mcp:
    - name: layout-kb
      manifest: mcp/server.json
      start_command: python mcp/server.py
  service:
    - name: local-api
      start_command: ./bin/server
      healthcheck: http://127.0.0.1:8787/health
  database:
    - name: official-kb
      path: data/official_kb.sqlite
      manifest: data/official_kb.manifest.json
```

Codex Skill 不应该是唯一实现。它是 AI 入口。

CLI、MCP、服务、数据库、编译产物和脚本共同构成实际生产力。

## Bundle Profiles

SkillFoundry 不应限制实现形态，但应提供少量 profile，帮助 FrontDesk、Builder 和 Verifier 对齐默认合同。

推荐 profile：

```text
prompt_only
script_tool
code_runtime
knowledge_runtime
mcp_runtime
service_runtime
full_runtime_bundle
```

这些 profile 不是限制，而是默认验收框架。

### prompt_only

适合轻量知识流程和行为协议。

典型产物：

- `SKILL.md`
- `references/*.md`
- trigger / non-trigger 规则；
- usage workflow；
- safety notes。

典型验证：

- frontmatter 合法；
- trigger 明确；
- references 存在；
- 不泄漏 raw prompt / raw transcript；
- 不声称自己已经通过外部验证。

### script_tool

适合把重复操作固化为脚本工具。

典型产物：

- `SKILL.md`
- `scripts/*.py` / `scripts/*.sh`
- `tests/`
- examples。

典型验证：

- 脚本 `--help` 可运行；
- smoke test 通过；
- 输入输出路径安全；
- README 命令和真实 CLI 一致。

### code_runtime

适合 Rust / Python / Go / Node 等代码型能力包。

典型产物：

- `src/`
- `bin/` 或构建说明；
- `tests/`
- fixtures；
- CLI 或 API contract。

典型验证：

- build 命令通过；
- test 命令通过；
- lint / type check 通过；
- CLI smoke 通过；
- 关键 fixtures 输出稳定。

### knowledge_runtime

适合 EDA、法律、医学、内部规范、API 文档等 reference-heavy 专业场景。

典型产物：

- `SKILL.md`
- `references/workflow.md`
- `references/corpus_map.md`
- `references/runtime_kb_usage.md`
- `data/runtime_kb.sqlite` 或 `data/runtime_kb.jsonl`
- `data/runtime_kb.manifest.json`
- `scripts/query_runtime_kb.py`
- `tests/test_runtime_kb.py`

典型验证：

- manifest hash 匹配；
- document count 匹配；
- schema 合法；
- sample query 有结果；
- query script 可运行；
- runtime bundle 不依赖构建机绝对路径；
- raw corpus 和中间态不进入公开 summary；
- handoff 明确说明知识边界。

### mcp_runtime

适合把领域能力暴露给 Codex / agent 的 MCP 工具。

典型产物：

- `mcp/server.py` 或编译产物；
- `mcp/manifest.json`；
- `SKILL.md` 中的 MCP 使用协议；
- fallback CLI 或 API；
- tests。

典型验证：

- server self-test 通过；
- tool list smoke 通过；
- 权限声明存在；
- start / stop / healthcheck 清晰；
- MCP 不暴露未声明路径、密钥或私有数据。

### service_runtime

适合完整本地服务或 API 分发包。

典型产物：

- `service/`
- `bin/`
- API schema；
- start / stop / healthcheck；
- logs / data path policy；
- tests。

典型验证：

- 服务能启动；
- healthcheck 通过；
- API smoke 通过；
- 端口和路径可配置；
- 无后台孤儿进程；
- README 命令可复现。

### full_runtime_bundle

适合完整生产力工具包，可能同时包含代码、数据库、MCP、服务、reference corpus 和验证套件。

典型验证是所有相关 profile 的组合，并额外要求 technical closure review。

## SkillFoundry 生产线

Capability Bundle 的生产线应当保持清晰：

```text
FrontDesk
  -> Capability Design
  -> Frozen Spec / Acceptance Criteria / Verification Spec
  -> ContextForge Boundary
  -> ForgeUnit Work Unit
  -> Codex exec / strong worker
  -> Runtime Bundle Candidate
  -> Verifier
  -> Repair Loop
  -> Final Report
  -> Registry
```

各部件职责如下。

### FrontDesk

FrontDesk 负责把模糊需求转成工程合同。

它不负责实现，但必须澄清：

- 用户真正要固化的工作是什么；
- 目标用户是谁；
- 何时触发；
- 产物形态是什么；
- 是否需要代码；
- 是否需要数据库；
- 是否需要 MCP；
- 是否需要本地服务；
- 是否需要处理原始文档；
- 哪些资料可分发；
- 哪些资料只能用于构建；
- 哪些验收命令必须通过。

FrontDesk 的输出必须足以让 Builder 开始工作，也必须足以让 Verifier 判断真假。

### Capability Design

Capability Design 负责选择 bundle profile 和能力面。

它要回答：

- 这是 prompt-only、code-runtime、knowledge-runtime、MCP-runtime，还是 full-runtime-bundle；
- `SKILL.md` 只是入口，还是主要产物；
- 是否需要 `skillfoundry.bundle.json`；
- 是否需要 data manifest；
- 是否需要 build pipeline；
- 是否需要 query tool；
- 是否需要 MCP server；
- 是否需要 local API service；
- 是否需要 oracle 和 fixtures；
- 哪些 runtime assets 需要 hash 和 provenance。

### ContextForge

ContextForge 是 agent 工作外骨骼。

在 Capability Bundle 生产中，它负责：

- 目标合同；
- 可见上下文；
- forbidden context；
- raw conversation 隔离；
- refs-only 状态；
- PromptCachePlan；
- checkpoint；
- ledger；
- worker attempt evidence；
- replay；
- verification evidence；
- repair basis。

它不替强模型完成创造。它负责让创造过程可控、可追踪、可恢复。

### ForgeUnit

ForgeUnit 是 LangGraph node 内的 work-unit harness。

它负责把 Codex exec 或其他强 worker 放进明确边界：

- 输入 refs；
- 写入范围；
- 尝试次数；
- 执行命令；
- attempt evidence；
- repair packet；
- refs-only state。

### Codex exec / Strong Worker

Codex exec 是肌肉和智能。

它可以自由完成复杂工程工作：

- 写代码；
- 构建数据库；
- 设计查询工具；
- 实现 MCP；
- 跑测试；
- 修 bug；
- 写文档；
- 组织 runtime bundle。

但它不是验收者。

worker self-report 不是事实。只有 verifier evidence 是事实。

### Verifier

Verifier 是免疫系统。

它必须独立判断 bundle 是否满足 frozen spec。

对复杂 bundle，Verifier 不应只检查 `package/SKILL.md` 是否存在，而应检查：

- bundle manifest；
- required artifacts；
- profile-specific commands；
- package hash；
- forbidden leakage；
- data manifest；
- service healthcheck；
- MCP smoke；
- CLI smoke；
- source provenance；
- technical closure review。

### Registry

Registry 只沉淀 verifier-passed bundle。

它记录：

- bundle id；
- version；
- package hash；
- verification hash；
- artifact manifest hash；
- capability surface；
- distribution status；
- compatibility notes。

Registry 不是垃圾桶。失败、未验收、worker 自报完成的产物不能注册为可用资产。

## Verification 哲学

SkillFoundry 的质量不来自“模型说做完了”。

质量来自可执行验收。

每个 bundle 都必须能回答：

```text
如何证明它真的可安装？
如何证明它真的可运行？
如何证明它真的能被 Codex 使用？
如何证明它没有泄漏构建过程中的私有资料？
如何证明它的数据库和 manifest 一致？
如何证明它的服务或 MCP 可以启动？
如何证明 README 里的命令是真的？
如何证明 worker 没有越界？
```

这意味着 VerificationSpec 需要从简单 artifact 检查升级为 profile-specific contract。

示例：

```yaml
verification:
  required:
    - bundle_manifest_valid
    - skill_entry_valid
    - no_raw_prompt_leakage
    - runtime_assets_hash_match
    - install_smoke
    - profile_specific_tests
```

knowledge-runtime 示例：

```yaml
verification:
  commands:
    - python package/scripts/query_runtime_kb.py search --query smoke --json
    - python package/tests/test_runtime_kb.py
  checks:
    - data/runtime_kb.manifest.json sha256 matches data/runtime_kb.sqlite
    - sample query returns at least one result
    - final report contains refs and hashes only
```

code-runtime 示例：

```yaml
verification:
  commands:
    - cargo test
    - cargo clippy -- -D warnings
    - cargo run -- --help
```

mcp-runtime 示例：

```yaml
verification:
  commands:
    - python package/mcp/server.py --self-test
    - python package/tests/test_mcp_tools.py
  checks:
    - mcp manifest exists
    - tool list smoke passes
    - declared permissions match implementation
```

## EdaSkill 的启发

EdaSkill 证明，专业 skill 的主要价值不一定在 prompt。

在 EDA / Virtuoso / Cadence SKILL 这种专业领域里，大模型不应该凭记忆猜 API、对象语义和版图环境。

高质量 skill 应该提供：

- 官方文档 corpus；
- 结构化 runtime knowledge base；
- manifest 和 hash；
- query script；
- corpus map；
- runtime usage protocol；
- spec mode / delivery mode；
- adapter-bound 风险说明；
- `.il` 交付边界；
- Python oracle；
- test vectors；
- verification checklist；
- handoff 文档。

这种 skill 本质上是：

```text
领域知识库 + 工作流协议 + 工具入口 + 验证合同
```

而不是 prompt。

SkillFoundry 如果要稳定生产 EdaSkill 级产物，就必须把 knowledge-runtime / full-runtime-bundle 作为正式 profile，而不是让 Codex exec 在黑盒里自由发挥后只检查 `SKILL.md`。

## Codexarium 的启发

Codexarium 这类 code-heavy skill 说明另一件事：

Capability Bundle 也可以是完整代码工具。

它可能包含：

- Rust crate；
- CLI；
- parser；
- formatter；
- local cache；
- tests；
- examples；
- compiled binary；
- MCP wrapper；
- Codex Skill entry；
- API 文档。

对这类 bundle，SkillFoundry 的重点不是生成一份华丽说明，而是让 Codex exec 在工程边界内开发真实工具，并让 Verifier 跑真实 build/test/lint/smoke。

Codexarium 类任务应当优先走 code-runtime 或 full-runtime-bundle profile。

## MCP 的位置

MCP 是 Capability Surface 的一种，不是唯一形态。

SkillFoundry 不应强迫所有 bundle 都变成 MCP，也不应忽略 MCP。

合理定位是：

```text
SKILL.md = agent 入口协议
CLI = 最小机器接口
MCP = agent-friendly tool interface
Service = 长驻能力接口
Database = 领域知识资产
Verifier = 事实判断接口
```

一个 bundle 可以这样降级：

```text
MCP 可用 -> Codex 通过 MCP 调用
MCP 不可用 -> Codex 通过 CLI 调用
CLI 不可用 -> 停止并报告 bundle 不完整
```

SkillFoundry 后续可以生成：

- MCP server；
- MCP manifest；
- CLI-to-MCP wrapper；
- SQLite-to-MCP query adapter；
- local service-to-MCP adapter。

但 MCP 必须被验证：

- server 能启动；
- tools 能列出；
- sample call 能返回；
- 权限声明准确；
- 不暴露未声明路径或私有数据。

## 数据与资料边界

Capability Bundle 可能由大量原始资料构建而来。

这些资料不一定都能进入 runtime 包。

SkillFoundry 必须区分：

```text
source materials
build intermediates
runtime assets
public summaries
private evidence
```

原则：

- 原始对话不进入构建状态；
- raw prompt / raw transcript 不进入公开 summary；
- 私有 PDF、内部文档、客户资料不得无声明进入可分发 bundle；
- runtime database 必须有 manifest 和 hash；
- 构建中间态可以作为 evidence 保存，但不默认分发；
- final report 应引用 refs、hashes、counts、commands，而不是泄漏原文。

专业 skill 的价值在于把复杂资料压缩成 runtime knowledge artifact，而不是把所有原始资料扔进 skill。

## 缓存与上下文哲学

SkillFoundry 不应该把所有资料拼进 prompt。

专业 bundle 更应该依赖：

- stable prefix；
- refs-only state；
- runtime query tools；
- compact summaries；
- source hashes；
- retrieval evidence；
- PromptCachePlan；
- checkpoint。

长任务中，缓存命中和上下文质量都很重要。

默认策略：

- 稳定的系统协议、bundle contract、frozen spec 应尽量保持 stable prefix；
- 运行时证据、查询结果、attempt summary 应进入动态 suffix；
- 大型 corpus 应通过工具查询，不应直接塞进 prompt；
- checkpoint 记录任务状态，不替代 runtime knowledge base；
- 对用户不显式设置 token 总预算时，不应人为施加小上下文预算。

## 生产力工具的复用逻辑

人们会反复让 Codex 做相似工作。

如果每次都从零开始让 Codex 理解领域、搭工具、查文档、写流程，就是浪费智能。

SkillFoundry 的目标是把一次复杂工作沉淀为可复用能力：

```text
第一次：用户提出模糊需求，SkillFoundry 构建 bundle。
第二次：用户安装 bundle，Codex 直接进入领域入口。
第三次：bundle 进入 registry，更多人复用。
后续：反馈、修复、版本升级、能力扩展。
```

这就是 AI 时代的“铲子”。

不是让所有人都成为工具开发者，而是让强 agent 把可重复工作固化为工具，再让所有人通过 Codex 使用这些工具。

## 可行性边界

当前方向可行，但不能混淆愿景和已实现能力。

当前 SkillFoundry 已经具备的基础：

- FrontDesk；
- frozen spec；
- ContextForge boundary；
- ForgeUnit command boundary；
- Codex exec / deterministic fake worker；
- attempts；
- verifier；
- repair loop；
- registry；
- final report；
- refs-only product state；
- package tree hash。

这足以支撑第一版 Capability Bundle 工厂。

当前仍缺少的一等抽象：

- bundle manifest；
- bundle profile；
- capability surface；
- runtime asset manifest；
- profile-specific verification；
- knowledge build plan；
- MCP / service runtime contract；
- professional technical closure checklist。

因此，近期目标不是重写系统，而是把这些抽象逐步落为小而硬的 contract。

## 工程演进原则

### 原则一：不重做 Codex

Codex exec / Codex SDK thread / GPT-5.5 是强执行体。

SkillFoundry 不应试图重新实现完整 Codex agent。

SkillFoundry 应该做 harness、contract、verification、registry。

### 原则二：不信任 worker self-report

worker 可以报告自己做了什么，但不能决定自己通过验收。

Verifier 才是事实边界。

### 原则三：实现不设限，契约必须严格

Capability Bundle 可以包含任何语言、服务、数据库、MCP、二进制或脚本。

但必须声明：

- 能力面；
- 权限；
- 依赖；
- 运行方式；
- 验证方式；
- 分发边界。

### 原则四：复杂资料必须 artifact 化

大型 PDF、官方文档、内部知识库不应该直接塞进 prompt。

它们应该被转换成 runtime artifact，并通过工具查询。

### 原则五：默认 refs-only

产品状态、final report、registry summary 默认只引用 refs、hashes、counts、commands 和 verification evidence。

不要把 raw prompt、raw transcript、私有原文、worker 内部推理放进公开状态。

### 原则六：Profile 是默认合同，不是牢笼

profile 帮助系统选择默认问题、默认产物和默认 verifier。

用户和 worker 可以扩展 profile，但不能逃避验收。

### 原则七：先闭环，再扩展

不要为了所有边界情况过度设计。

先做最小可验证闭环：

```text
bundle manifest
capability surface
profile-specific required artifacts
profile-specific verification commands
refs-only final report
registry only after verifier pass
```

然后通过真实产品打磨。

## 下一步最小落点

为了让本愿景进入代码，推荐下一步只做四个小落点：

1. 新增 `package/skillfoundry.bundle.json` 作为可选但优先的 bundle manifest。
2. 在 frozen spec / worker input 中加入 `package_profile`。
3. 在 VerificationSpec 中支持 `profile_specific_commands` 或等价结构。
4. 在 verifier 中增加最小 bundle manifest 校验和 profile artifact 校验。

这四步足以让 SkillFoundry 从“Codex Skill 工厂”升级为“Capability Bundle 工厂”的第一版。

不需要立刻实现完整 MCP 平台、服务部署平台或知识库构建平台。

## 宪法级结论

SkillFoundry 的长期产品定义：

```text
SkillFoundry is a capability foundry for the Codex-centered AI era.
It turns repeatable human work into verified AI-native capability bundles.
Codex is the operator. The bundle is the durable tool.
```

中文定义：

```text
SkillFoundry 是面向 Codex 中心工作流的 AI 能力铸造厂。
它把可重复的人类工作固化成经过验证的 AI 原生能力包。
Codex 是操作者，Capability Bundle 是持久化工具。
```

这就是本项目的新宪法。
