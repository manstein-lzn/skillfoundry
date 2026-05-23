# SkillFoundry On ForgeUnit Product Direction

最后更新：2026-05-23

状态：后续方向文档，不是当前代码完成声明

## 0. 一句话结论

SkillFoundry 后续不应该继续演化成一套独立的多 agent 框架。

它应该成为第一个正式产品场景：

```text
LangGraph + ForgeUnit + ContextForge + Codex exec
```

这套通用基础设施负责 agent 协作的共性能力；SkillFoundry 只负责
Codex Skill 工厂这个领域的专用规则。

更直接地说：

```text
ForgeUnit = 通用 agent work-unit 外骨骼
ContextForge = 上下文 / 缓存 / checkpoint 基础设施
LangGraph = 产品流程编排
Codex exec = 强执行体
SkillFoundry = 第一个产品应用：把模糊需求铸造成 verified Codex Skill
```

这意味着后续不要再把 SkillFoundry 当作“从头到尾独立构建的一套工程”
来推进。旧 SkillFoundry 代码和 WP0-WP17 文档是产品经验、业务规则和
验收样本，不是未来通用 agent runtime 的技术约束。

## 1. 为什么要换成这个方向

旧 SkillFoundry 复杂的根源不是产品目标错了，而是它在一个产品仓库里
同时承担了太多基础设施职责：

```text
graph orchestration
context adapter
worker boundary
prompt/cache plan
repair runtime
verifier bridge
registry gate
evidence summary
Codex/external worker distinction
```

这些能力大部分不是 SkillFoundry 专用能力，而是任何长期运行的多 agent
产品都会需要的基础设施。

如果继续把它们留在 SkillFoundry 里，后续每做一个新产品都会重复一遍。

更干净的方向是：

```text
通用能力下沉到 ForgeUnit / ContextForge。
产品能力留在 SkillFoundry。
LangGraph 只做流程编排。
Codex exec 继续负责强智能执行。
```

这也符合当前实践结论：

- 不重做 Codex 的工具循环、上下文利用和长任务执行能力。
- 不把 Codex 的自我报告当作验收。
- 用 ForgeUnit 约束每个 work unit 的输入、写范围、证据和验收。
- 用 ContextForge 管理 context packet、stable prefix、cache plan 和 checkpoint。
- 用 SkillFoundry 专用 verifier / registry 定义什么叫“合格 Skill”。

## 2. 目标架构

未来 SkillFoundry 的架构应该是三层：

```text
Foundation Layer
  ContextForge
  ForgeUnit
  Codex exec

Orchestration Layer
  LangGraph product flow

Domain Layer
  SkillFoundry front desk
  SkillSpec / AcceptanceCriteria / VerificationSpec
  Skill verifier
  Skill registry
  API / UI
```

各层职责如下。

| 层 | 负责什么 | 不负责什么 |
| --- | --- | --- |
| LangGraph | 产品阶段、路由、重试、人审入口 | worker 内部工具循环、证据验收、上下文缓存 |
| ForgeUnit | UnitContract、worker boundary、write scope、worker_result、evidence、verify、repair、promotion | Skill 领域规则、需求澄清、registry 业务语义 |
| ContextForge | ContextPacket、ContextView、PromptCachePlan、stable prefix、dynamic refs、checkpoint | Codex 内部 prompt/tool loop、Skill 业务验收 |
| Codex exec | 强智能执行、读写文件、工具调用、多轮修正 | 事实权、验收权、registry approval |
| SkillFoundry | 需求澄清、SkillSpec、Skill verifier、Skill registry、产品 API/UI | 通用 agent runtime、通用 work-unit harness、通用 context runtime |

## 3. SkillFoundry 应该保留的专用内容

SkillFoundry 的核心价值是 Codex Skill 工厂，而不是通用 agent 框架。

因此它应该保留并强化这些领域能力：

### 3.1 Front Desk

Front Desk 负责把用户的模糊需求整理成可构建的冻结规格。

它需要回答：

```text
用户到底要什么能力？
Skill 的触发场景是什么？
不触发场景是什么？
需要哪些输入？
期望输出是什么？
安全边界是什么？
验收标准是什么？
是否需要用户确认方案？
```

Front Desk 可以使用 LangGraph / ForgeUnit / ContextForge，但它的业务语义
属于 SkillFoundry。

### 3.2 Domain Schemas

SkillFoundry 应该定义自己的领域对象：

```text
CoreNeed
SolutionPlan
FrozenSkillSpec
AcceptanceCriteria
VerificationSpec
SkillPackageManifest
RegistryDecision
```

这些对象可以被转换成 ForgeUnit TaskPack，但不应该反过来污染 ForgeUnit
的通用模型。

### 3.3 TaskPack Factory

SkillFoundry 应该提供一个非常明确的转换层：

```text
FrozenSkillSpec
  -> ForgeUnit TaskPack
  -> ForgeUnit UnitContract(s)
```

例如：

```text
skillfoundry_job/
  task.yaml
  inputs/
    skill_spec.yaml
    acceptance_criteria.yaml
    verification_spec.yaml
    build_contract.yaml
```

这个 task pack 是 SkillFoundry 和 ForgeUnit 的边界。

### 3.4 Skill Verifier

SkillFoundry 的 verifier 负责判断 Skill 包是否真的合格：

```text
SKILL.md 是否存在
frontmatter 是否合法
触发说明是否清晰
references / scripts / tests 路径是否安全
smoke tests 是否通过
acceptance criteria 是否覆盖
是否泄漏 raw prompt / secrets / raw transcript
package hash 是否和 registry decision 匹配
```

ForgeUnit 只运行 verifier、记录 verifier 结果，并把结果纳入后续 route。

### 3.5 Registry

SkillFoundry Registry 是产品资产库。

它决定：

```text
Skill 是否可以注册
版本如何管理
重复 skill 如何处理
registry entry hash 如何生成
approval evidence 如何保存
```

ForgeUnit 只需要记录 registry decision ref / promotion evidence，不应该内置
Skill registry 业务规则。

### 3.6 API / UI

SkillFoundry 的 API/UI 负责：

```text
提交需求
展示方案
批准或要求修改
启动 build
展示 refs-only evidence
展示 verifier / repair / registry 状态
下载或安装已批准 skill
```

UI 不应该展示 raw prompt、raw transcript、raw provider payload 或 package
全文，除非后续明确做了权限和审计设计。

## 4. SkillFoundry 不应该再自建的内容

后续不要在 SkillFoundry 中继续扩展这些通用基础设施：

```text
通用 worker runtime
通用 context ledger
通用 prompt cache plan
通用 Codex boundary
通用 evidence manifest
通用 repair runtime
通用 promotion record
通用 refs-only graph state validator
通用 run inspect/history
```

这些应该由 ForgeUnit / ContextForge 提供。

SkillFoundry 可以组合它们，但不要重新实现它们。

## 5. 未来最小执行流

未来的 SkillFoundry 产品闭环应该长这样：

```text
1. 用户提交自然语言需求
2. Front Desk 产出 CoreNeed 和 SolutionPlan
3. 用户批准或 deterministic gate freeze
4. SkillFoundry 生成 ForgeUnit task pack
5. LangGraph 进入 build node
6. ForgeUnit 调用 codex-exec worker
7. Codex 写 package/SKILL.md、evidence/manifest.json、worker_result.json
8. ForgeUnit ingest worker_result
9. ForgeUnit 调用 SkillFoundry verifier
10. verifier 通过则进入 registry gate
11. registry 批准后 ForgeUnit 记录 promotion
12. API/UI 展示 refs-only evidence 和最终结果
```

失败时：

```text
verifier failed
  -> ForgeUnit 生成 repair packet
  -> Codex exec repair
  -> ForgeUnit ingest repair result
  -> SkillFoundry verifier re-run
  -> registry gate or human review
```

这个流程里：

```text
Codex 负责做事。
ForgeUnit 负责工作边界和验收推进。
ContextForge 负责上下文视界和缓存纪律。
LangGraph 负责阶段流转。
SkillFoundry 负责领域判断。
```

## 5.1 当前已落地的第一层适配

ForgeUnit v1.2 完成后，SkillFoundry 已经开始落地最小产品适配层：

```text
src/skillfoundry/forgeunit_adapter.py
```

当前它只做第一层边界打通：

```text
SkillFoundry JobWorkspace
  -> task.yaml
  -> ForgeUnitNode("codex_exec", dry_run=True)
  -> refs-only SkillFoundry v2 state
```

对应说明见：

```text
docs/FORGEUNIT_PRODUCT_ADAPTER_SLICE.md
```

这还不是完整产品主路径替换。它的价值是先把
`JobWorkspace -> ForgeUnit task pack -> ForgeUnit public API` 这条边界跑通，
后续再把真实 Codex exec、SkillFoundry verifier、repair、registry gate 接上。

## 6. 期望的代码形态

ForgeUnit 完成后，清爽版 SkillFoundry 可以收敛成：

```text
src/skillfoundry/
  domain.py
    CoreNeed
    SolutionPlan
    FrozenSkillSpec
    SkillPackageManifest
    RegistryDecision

  frontdesk.py
    clarify_requirement()
    propose_solution_plan()
    freeze_skill_spec()

  taskpack.py
    build_skill_task_pack(frozen_spec) -> ForgeUnitTaskPack
    build_repair_task_pack(failed_run) -> ForgeUnitTaskPack

  verifier.py
    verify_skill_package(package_ref, acceptance_criteria) -> VerificationResult

  registry.py
    approve_verified_skill(...)
    reject_unverified_skill(...)

  graph.py
    LangGraph product flow using ForgeUnit nodes

  api.py
    submit_requirement()
    approve_plan()
    run_build()
    inspect_job()
```

旧代码中的许多能力仍有参考价值，但未来不应该按旧模块边界继续堆叠：

```text
graph_v2.py
goal_runtime.py
workers_v2.py
verification_bridge.py
contracts.py
frontdesk_goal_runtime.py
frontdesk_loop.py
```

这些模块可以作为业务规则和测试样本来源，但不要把 ForgeUnit 拖回它们的
历史复杂度里。

## 7. ForgeUnit 在接入 SkillFoundry 前应完成的能力

SkillFoundry 正式作为第一个产品场景之前，ForgeUnit 至少应该补齐：

### 7.1 Repair Loop

```text
verify failed -> repair task packet -> codex-exec repair -> ingest -> reverify
```

这是 SkillFoundry 必需能力，因为真实 Skill 构建一定会失败和修复。

### 7.2 LangGraph Node Adapter / Public Python API

正式接入不应该靠 shell 调 CLI。

SkillFoundry 应该能这样使用 ForgeUnit：

```python
from forgeunit.langgraph import ForgeUnitNode
```

或者：

```python
from forgeunit.api import run_unit, advance_run, inspect_run
```

CLI 继续用于人工操作和 smoke test。

### 7.3 Thin ContextPacket / PromptCachePlan

不做长期记忆系统，但需要结构化上下文包：

```text
stable prefix refs
task refs
dynamic refs
forbidden refs
cache epoch
expected cacheable tokens
```

这让 SkillFoundry 可以清楚声明：

```text
builder 能看 skill_spec / acceptance_criteria / verification_spec
builder 不能看 raw frontdesk conversation
repair 能看 failed verification result
verifier 能看 package 和 evidence
```

### 7.4 External Verifier Command / Structured Result

ForgeUnit 需要能运行 SkillFoundry 专用 verifier，并把 verifier 结果纳入
UnitRun / VerificationResult。

### 7.5 Promotion Record

ForgeUnit 的 promote 不应只是 status 标记。

它需要记录：

```text
promotion_id
run_id
artifact_refs
verification_refs
registry_decision_ref
promotion_status
created_at
```

这样 SkillFoundry 的 registry approval 才能被审计。

### 7.6 Result Wrapper

真实 Codex exec 可能完成了工作，但忘记写标准 `worker_result.json` 或
manifest。

ForgeUnit 后续最好提供 wrapper / diagnostic 能力：

```text
codex exec 做事
ForgeUnit wrapper 扫描 expected outputs / evidence
生成或校验 worker_result
失败时生成 diagnostic evidence
```

这不是第一天必须完成，但在真实 SkillFoundry pilot 前很有价值。

## 8. SkillFoundry 第一版 Pilot

不要一开始接回旧 SkillFoundry 全量代码。

第一版应该新增一个最小 pilot：

```text
examples/skillfoundry_skill_pilot/
  inputs/
    skill_spec.yaml
    acceptance_criteria.yaml
    verification_spec.yaml
  task.yaml
```

目标只验证：

```text
FrozenSkillSpec -> ForgeUnit task pack
  -> codex-exec build
  -> SkillFoundry verifier
  -> repair if needed
  -> registry decision
  -> promotion record
```

只有这个 pilot 跑通后，再决定如何把旧 SkillFoundry 里的 Front Desk、
API/UI 和 registry 产品能力接回新骨架。

## 9. 新旧 SkillFoundry 的关系

旧 SkillFoundry 不是要丢弃，而是要重新定位：

```text
旧代码 = 产品规则样本 + 测试样本 + 历史经验
新方向 = 基于 ForgeUnit / ContextForge 的产品应用
```

后续迁移方式应该是：

1. 从旧代码中提取稳定领域规则。
2. 把领域规则变成 SkillFoundry verifier / registry / frontdesk schema。
3. 让 taskpack factory 生成 ForgeUnit task packs。
4. 用 LangGraph + ForgeUnit 跑产品流程。
5. 逐步替换旧 graph/runtime/worker/context glue。

不要反过来：

```text
不要为了兼容旧 graph_v2 / goal_runtime / workers_v2，
把 ForgeUnit 设计成 SkillFoundry 旧架构的子模块。
```

## 10. 非目标

这个方向明确不包含：

```text
重做 Codex agent loop
自研 owned LLM worker 作为主路径
长期记忆文件系统
复杂 scheduler / worker pool
数据库驱动的 workflow engine
向量检索式 memory
把旧 SkillFoundry graph_v2 作为未来唯一架构
把 raw prompt / raw transcript 传进 LangGraph state
让 builder self-report 通过 registry
```

这些都可能在未来某些产品阶段有价值，但不是当前主线。

## 11. 判断标准

当后续 SkillFoundry 真的接入 ForgeUnit 时，应该用这些标准判断架构是否
清爽：

- SkillFoundry 代码里没有通用 worker runtime。
- SkillFoundry 代码里没有通用 context/cache/checkpoint runtime。
- LangGraph state 只保存 refs、IDs、hashes、status 和 route。
- Codex exec worker 的输出必须经过 ForgeUnit ingest。
- Verifier 和 registry gate 决定是否通过，builder self-report 不算。
- SkillFoundry 只定义领域 schema、verifier、registry、frontdesk 和 API/UI。
- ForgeUnit 的同一套能力可以复用于第二个产品场景，而不依赖 SkillFoundry。

如果这些成立，说明 SkillFoundry 已经从“复杂多 agent 框架”变成了
“基于通用 agent 基础设施的清爽产品应用”。

## 12. 后续推荐路径

推荐顺序：

```text
1. 继续完成 ForgeUnit 内核：
   repair loop
   LangGraph adapter
   thin ContextPacket / PromptCachePlan
   external verifier bridge
   promotion record

2. 在 ForgeUnit 中做一个 SkillFoundry-style pilot task pack。

3. 在 SkillFoundry 中新增 taskpack factory 和 verifier adapter。

4. 用新的 LangGraph product graph 调 ForgeUnit node。

5. 再逐步接回 Front Desk / API / registry。
```

这条路线的目标不是“重构旧 SkillFoundry”，而是：

```text
用 SkillFoundry 证明 ForgeUnit 是一个可复用的 agent work-unit 产品底座。
```
