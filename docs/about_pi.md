可以。我先说明一下进展：云沙箱克隆 `pi` 仓库仍然提示授权状态异常，所以我暂时没有用本地 `grep`/AST 工具全量扫 repo；但我已经通过 GitHub API 和 raw 源码读了几块关键代码：

- `packages/agent/src/agent-loop.ts`
- `packages/agent/src/agent.ts`
- `packages/agent/src/types.ts`
- `packages/agent/src/harness/agent-harness.ts`
- `packages/agent/src/harness/types.ts`
- `packages/agent/src/harness/compaction/*`
- `packages/coding-agent/src/core/*` 目录结构
- `AGENTS.md`

基于这些，我可以先给你一版比较深入的源码级判断。

---

## 先给结论

我现在对 pi 的判断是：

> **pi 的核心价值不是单纯“模型更强”，而是它把 agent runtime 拆成了非常清楚的事件流、session tree、context transform、tool gate、provider hook、compaction、branch navigation、skill/template invocation 等工程边界。**

这意味着它在真实任务中可能表现好，不一定是因为“推理能力超过 Codex / Claude Code”，而是因为它在以下几个方面更可控：

1. **状态流清楚**
2. **工具执行语义清楚**
3. **上下文进入模型前有显式变换层**
4. **session 是树状、可 fork、可 compact、可 navigate 的**
5. **provider 请求前后有 hook**
6. **运行过程中可以 steer / followUp / nextTurn**
7. **技能、模板、工具、session、模型选择都被 harness 化**

这对你的 `ContextForge / ForgeUnit / SkillFoundry` 非常有参考价值。

不过也要注意：**pi 和 Codex / Claude Code 的强弱比较，公开 README 和源码本身不能证明。**  
如果有人说 pi 在很多实际任务中更强，我更倾向于解释为：它的 harness 和交互/上下文机制在某些真实工作流里更适配，而不是模型智能本身一定更高。

---

# 1. pi 的 runtime 分了两层：`Agent` 和 `AgentHarness`

源码里有两个层次非常重要。

## 第一层：低层 `Agent` / `agentLoop`

`packages/agent/src/agent-loop.ts` 是一个比较纯粹的 agent loop。它的职责是：

```text
prompt / continue
  -> turn_start
  -> assistant streaming
  -> tool call extraction
  -> tool execution
  -> tool result message
  -> turn_end
  -> steering / follow-up
  -> next turn or agent_end
```

它有几个非常值得借鉴的点。

### 1.1 AgentMessage 和 LLM Message 严格分离

代码注释直接写了：

> Agent loop works with AgentMessage throughout. Transforms to Message[] only at the LLM call boundary.

也就是说，pi 内部不是直接把所有状态塞给模型，而是：

```text
AgentMessage[]
  -> transformContext()
  -> AgentMessage[]
  -> convertToLlm()
  -> Message[]
  -> LLM
```

这个模式非常适合你的 ContextForge。

你现在的 `ContextForge` 已经有：

- Ledger
- ContextView
- PromptView
- PromptCachePlan
- WorkerRun
- VerificationResult

pi 这里给你的启发是：**不要让 ledger / graph state / transcript / prompt 混在一起。**

你的体系里可以形成类似分层：

```text
完整历史：Ledger
当前可见面：ContextView
模型输入草案：PromptView
worker 输入：WorkerInput
外部 worker 返回：WorkerEvidence
验证结果：VerificationResult
```

这和 pi 的 `transformContext` / `convertToLlm` 思路是高度同构的。

---

### 1.2 tool execution 被拆成 prepare / execute / finalize

pi 的工具调用不是“模型一说调用就直接执行”。

它大概分成：

```text
assistant emits toolCall
  -> find tool
  -> prepareArguments()
  -> validateToolArguments()
  -> beforeToolCall()
  -> execute()
  -> afterToolCall()
  -> emit tool_execution_end
  -> create toolResult message
```

这特别适合你的 `ForgeUnit`。

你现在讲的核心是 worker 不能自证、边界必须可审计。那么 pi 这里的 `beforeToolCall` / `afterToolCall` 可以映射为：

```text
beforeToolCall  -> Policy / WriteScope / Permission Gate
execute         -> Worker action / Tool action
afterToolCall   -> Evidence normalization / Redaction / Verification pre-check
toolResult      -> refs-only result / ledger append
```

如果你保留 Codex worker，也可以借这个思想改造 `CodexBoundaryWorker`：

```text
CodexBoundaryWorker before-run:
  - validate UnitContract
  - validate write scope
  - build ContextView
  - create evidence manifest path

CodexBoundaryWorker after-run:
  - normalize changed files
  - collect artifact refs
  - enforce forbidden paths
  - check worker_result.json
  - produce WorkerRun
```

这本质上就是 pi tool lifecycle 的 work-unit 版本。

---

### 1.3 并行/串行工具执行语义非常清楚

pi 支持：

- 全局 `toolExecution: "parallel" | "sequential"`
- 单个 tool 可以声明 `executionMode`
- 如果任意 tool 需要 sequential，整个 batch sequential
- parallel 模式下：
  - preflight 顺序执行
  - 允许的 tool 并发执行
  - `tool_execution_end` 按完成顺序发出
  - toolResult message 仍按 assistant 源顺序写回

这个细节很高级。因为它解决了一个真实 agent runtime 里的坑：

> 并发执行可以提升速度，但 transcript 顺序必须稳定，否则模型下一轮看到的上下文会漂。

对你的 `ForgeUnit` 来说，这可以迁移成：

```text
WorkUnit execution mode:
  - sequential
  - parallel
  - exclusive
  - human-gated
  - verifier-gated
```

并且可以区分：

```text
实际完成顺序：event stream order
语义归档顺序：contract/source order
```

这个对多 agent 集群特别关键。

---

### 1.4 steering / follow-up 是 runtime 原生机制

pi 的 `Agent` 有：

- `steer()`
- `followUp()`
- `nextTurn()` 在 Harness 层出现
- `QueueMode = "all" | "one-at-a-time"`

底层 loop 中，steering 是：

```text
当前 assistant turn + tool calls 完成
  -> drain steering messages
  -> inject into context
  -> next LLM call
```

follow-up 是：

```text
agent 原本要停止
  -> drain follow-up messages
  -> continue another turn
```

这和你提出的 **Kalman-style “走一步看一步” steering** 很贴合。

但区别是：

- pi 的 steering 更像“用户/系统中途插话”
- 你的 steering 更像“控制论式方向修正”

所以你可以借 pi 的队列机制，但把语义提升为：

```text
SteeringUpdate:
  prior_direction
  observation
  uncertainty
  verifier_signal
  next_guidance
  stop_or_continue
```

也就是说，pi 给你的是 runtime primitive；你的体系可以把它升级成 governance primitive。

---

# 2. `AgentHarness` 是比 `Agent` 更接近你需求的部分

如果只看 `agent-loop.ts`，pi 像一个普通 agent runtime。  
但 `packages/agent/src/harness/agent-harness.ts` 才是你真正应该重点研究的部分。

它把低层 `AgentLoop` 包装成一个更完整的 harness。

里面有这些核心概念：

- `ExecutionEnv`
- `Session`
- `AgentHarnessResources`
- `Skill`
- `PromptTemplate`
- `AgentHarnessStreamOptions`
- `AgentHarnessPhase`
- `pendingSessionWrites`
- `steerQueue`
- `followUpQueue`
- `nextTurnQueue`
- `compact()`
- `navigateTree()`
- `skill()`
- `promptFromTemplate()`

这已经不是简单 agent loop 了，而是一个可持久化、可扩展、可 hook 的工作环境。

---

## 2.1 它有明确 phase

`AgentHarnessPhase` 包括：

```ts
"idle" | "turn" | "compaction" | "branch_summary" | "retry"
```

这点很值得你借鉴。

你的 `ForgeUnit` / `SkillFoundry` 也应该有明确 phase，而不是只有 status。

比如：

```text
UnitPhase:
  idle
  preparing_context
  dispatching_worker
  waiting_worker
  ingesting_evidence
  verifying
  repairing
  promoting
  failed
  cancelled
```

`SkillFoundry` 可以进一步有：

```text
SkillBuildPhase:
  frontdesk
  spec_freeze
  context_boundary
  forgeunit_dispatch
  worker_execution
  evidence_ingest
  verification
  repair
  registry_promote
  export
```

pi 的价值在于提醒你：**phase 不是 UI 状态，而是 runtime 安全边界。**

例如 pi 的 `compact()` 要求：

```ts
if (this.phase !== "idle") throw new AgentHarnessError("busy", "compact() requires idle harness");
```

这说明它避免在 streaming/tool execution 中间做危险上下文重写。

你的 ContextForge 也应该严格规定：

- 什么时候允许 compact
- 什么时候允许 checkpoint
- 什么时候允许 branch switch
- 什么时候允许 promote artifact
- 什么时候允许修改 SkillSpec

---

## 2.2 Session write 有 pending buffer

`AgentHarness` 里有 `pendingSessionWrites`。

它不是任意时刻直接写 session，而是在 agent run 中把某些写操作缓冲，到 turn boundary / save point 再 flush。

这对你的系统非常重要。

你的体系里目前应该也会遇到类似问题：

- worker 正在执行时，能不能追加 steering？
- verifier 正在跑时，能不能改 contract？
- repair loop 期间，artifact registry 什么时候写入？
- graph state 什么时候只写 refs，什么时候写完整 evidence？

pi 的处理方式是：

```text
运行中：
  pendingSessionWrites.push(...)

turn_end / agent_end:
  flushPendingSessionWrites()
  emit save_point
```

这可以直接映射到你的 ledger：

```text
Worker running:
  pending ledger entries

Unit boundary reached:
  flush entries
  create checkpoint
  emit save_point
```

这会让你的系统更可靠。

---

## 2.3 它把 provider hook 做成一等公民

`AgentHarness` 有这些 hook：

- `before_provider_request`
- `before_provider_payload`
- `after_provider_response`

这很关键。

因为很多 agent 框架只关心“模型返回了什么”，但 pi 允许你在 provider 请求前后介入：

```text
before_provider_request:
  patch streamOptions / headers / metadata

before_provider_payload:
  inspect or modify provider payload

after_provider_response:
  record status / headers
```

对你的 ContextForge 来说，这可以对应：

```text
before_worker_dispatch:
  inspect WorkerInput
  attach cache metadata
  enforce policy

before_worker_payload:
  redact forbidden context
  attach run IDs
  attach evidence manifest instruction

after_worker_response:
  record usage
  record external IDs
  record status
  update PromptCachePlan
```

尤其是你如果保留 Codex worker，这个思想仍然有价值。  
你可以做：

```text
before_codex_exec:
  - generate prompt
  - write boundary manifest
  - write expected output contract
  - snapshot environment

after_codex_exec:
  - collect stdout/stderr
  - collect changed files
  - collect worker_result.json
  - record exit code
  - normalize evidence refs
```

也就是说，pi 的 provider hook 可以转译成你的 worker hook。

---

## 2.4 它的 session 是树，不是线性日志

`harness/types.ts` 里有很多 session tree 结构：

- `SessionTreeEntryBase`
- `MessageEntry`
- `CompactionEntry`
- `BranchSummaryEntry`
- `CustomEntry`
- `LabelEntry`
- `LeafEntry`
- `getPathToRoot`
- `fork`
- `navigateTree`

这点非常重要。

多数 agent 系统把 session 当线性 transcript，但 pi 明显把它当成可分叉、可导航的树。

这对 coding agent 很有价值，因为真实开发任务经常是：

```text
尝试路径 A
  -> 失败
回到某个点
尝试路径 B
  -> 成功
```

如果只是线性 append，失败路径会污染上下文。  
如果是 session tree，就可以 fork / navigate / summarize branch。

这对你的 `SkillFoundry` 更重要，因为 skill 生成过程天然会有多次候选、失败、repair、promote。

你可以借鉴成：

```text
SkillBuildTree:
  root: frozen SkillSpec
  branch A: candidate implementation
  branch B: repair attempt
  branch C: alternative runtime bundle design
  leaf: verifier-passed candidate
```

并且每个 branch 都可以有：

- evidence refs
- verifier result
- repair notes
- compacted branch summary

这比单纯重试计数强很多。

---

# 3. pi 的 compaction 机制值得重点看

虽然我还没有完整展开 `compaction.ts`，但从接口和 `AgentHarness.compact()` 逻辑看，pi 的 compaction 不是简单 summarize all。

它有：

- `prepareCompaction`
- `DEFAULT_COMPACTION_SETTINGS`
- `CompactionPreparation`
- `firstKeptEntryId`
- `messagesToSummarize`
- `turnPrefixMessages`
- `isSplitTurn`
- `tokensBefore`
- `previousSummary`
- `fileOps`
- `settings`

特别是 `fileOps`：

```ts
interface FileOperations {
  read: Set<string>;
  written: Set<string>;
  edited: Set<string>;
}
```

这说明 pi 的上下文压缩不是纯文本压缩，而会保留文件操作事实。

这对 coding agent 很重要，因为压缩时最容易丢的是：

- 读过哪些文件
- 改过哪些文件
- 为什么改
- 测试结果
- 当前 repo 状态

对你的 ContextForge 来说，这和你说的 evidence / ledger 非常一致。

你可以把 compaction 拆成：

```text
Narrative summary:
  任务进展、决策、失败、下一步

Operational summary:
  read files
  edited files
  created artifacts
  commands run
  tests failed/passed

Verification summary:
  which criteria passed
  which criteria failed
  open risks

Boundary summary:
  forbidden context still forbidden
  write scope still active
  unresolved policy warnings
```

这会比普通“总结历史”强很多。

---

# 4. pi 的 `ExecutionEnv` 抽象很适合你

`harness/types.ts` 里有：

```ts
interface FileSystem { ... }
interface Shell { ... }
interface ExecutionEnv extends FileSystem, Shell {}
```

而且它规定：

> Operation methods must never throw or reject. All filesystem failures must be encoded in Result.

这是很强的工程约束。

它把本地文件系统、shell、执行环境抽象成一个稳定 capability surface。

对你的 ForgeUnit 来说，这可以直接借鉴。

你现在如果要让 work unit 支持不同 worker 和不同环境，应该有类似：

```text
ExecutionEnv:
  read_text
  write_file
  list_dir
  exec
  artifact_store
  temp_dir
  cleanup
```

并且所有失败都返回结构化错误：

```text
FileError:
  not_found
  permission_denied
  is_directory
  invalid
  aborted

ExecutionError:
  timeout
  aborted
  spawn_error
  shell_unavailable
```

这能让 verifier / repair loop 更容易做决策。

你现在的体系强调 refs-only 和 evidence，那 `ExecutionEnv` 就不只是工具层，而是 evidence source。

---

# 5. pi 的 skill / prompt template 机制与你的 SkillFoundry 有直接关系

pi 的 `AgentHarness` 里有：

- `Skill`
- `PromptTemplate`
- `resources`
- `skill(name, additionalInstructions?)`
- `promptFromTemplate(name, args)`

它的 Skill 类型包含：

```ts
name
description
content
filePath
disableModelInvocation?
```

并且注释提到，skill 会以 XML-formatted block 进入 system prompt。

这和你的 `SkillFoundry` 很相关，但你要注意两者层级不同：

## pi 的 skill

更像：

```text
给 agent 的可调用能力说明 / prompt resource
```

## 你的 SkillFoundry skill

应该更像：

```text
可安装、可运行、可验证、可复用的 capability bundle
```

所以 pi 的 skill 机制可以作为你的低阶资源形态参考，但你不要把 SkillFoundry 降级成 prompt skill 管理器。

你可以借它的两个点：

1. **skill listing 和 explicit invocation 分离**
   - 有些 skill 可以给模型看
   - 有些 skill 只能由应用显式调用

2. **skill invocation 有统一 formatter**
   - 不要在各处手写 prompt
   - 所有 skill 调用都通过规范化入口

对 SkillFoundry 来说可以是：

```text
CapabilityBundle:
  manifest
  skill.md
  runtime_bundle
  verifier_spec
  acceptance_criteria
  evidence_contract
  invocation_template
  safety_policy
```

然后：

```text
formatCapabilityInvocation(bundle, task_input)
```

这会比单个 SKILL.md 更强。

---

# 6. 为什么 pi 可能在真实任务里表现好？

我现在认为可能有几个原因。

## 6.1 它把交互 interruption 做成 runtime 机制

Codex / Claude Code 当然也能被用户打断，但 pi 的 `steer` / `followUp` / `nextTurn` 是在 runtime 层明确建模的。

真实任务不是一次性 prompt，而是：

```text
agent 正在跑
用户发现方向不对
插入 correction
agent 当前工具跑完后接收 correction
继续
```

这对复杂任务很重要。

---

## 6.2 它把 session 做成可治理对象

pi 有：

- save point
- compaction
- branch summary
- tree navigation
- fork
- labels
- leaf

这意味着它不是简单“聊天记录”，而是一个工作树。

真实工程任务常常需要回退、分支、总结、切换上下文。  
这会显著影响实际体验。

---

## 6.3 它对 provider 细节暴露了足够 hook

pi 不是完全黑盒调用 LLM。它允许在 payload、headers、stream options、response 处接 hook。

这让它可以适配：

- cache retention
- transport
- provider metadata
- auth headers
- retry
- response diagnostics

这些小东西对实际稳定性很重要。

---

## 6.4 它对工具执行顺序和事件结算非常认真

`Agent.subscribe()` 的 listener 会被 await。  
`agent_end` 是最后事件，但 agent 真正 idle 要等 `agent_end` listeners settle。

这个细节说明作者踩过很多异步状态坑。

你的 ForgeUnit 也应该吸收这个思想：

```text
unit_end event emitted
≠ unit fully settled

unit settled
= all ledger writes, artifact writes, verifier callbacks, UI subscribers completed
```

这对可靠性非常关键。

---

# 7. 对你的三个项目，具体可借鉴点

## 7.1 ContextForge 应该借 pi 的这些东西

### A. `transformContext -> convertToLlm` 分层

你可以变成：

```text
Ledger
  -> ContextViewCompiler
  -> PromptView
  -> WorkerInputCompiler
  -> WorkerInput
```

不要直接从 ledger 拼 prompt。

---

### B. CompactionPreparation

你可以设计：

```text
ContextCompactionPreparation:
  entries_to_summarize
  entries_to_keep
  first_kept_entry_id
  previous_summary
  file_ops
  artifact_ops
  verifier_status
  token_pressure
  cache_epoch
  split_turn_warning
```

这比普通 summary 强很多。

---

### C. Provider/Worker hook

ContextForge 可以有：

```text
before_context_compile
after_context_compile
before_worker_payload
after_worker_response
before_verification
after_verification
before_checkpoint
after_checkpoint
```

这些 hook 不应该只是 callback，而应该成为审计事件。

---

## 7.2 ForgeUnit 应该借 pi 的这些东西

### A. phase lock

每个 UnitRun 都应该有明确 phase，并规定哪些操作只能在 idle / boundary 执行。

比如：

```text
cannot repair while worker_running
cannot promote before verifier_passed
cannot compact while evidence_ingest
cannot mutate UnitContract after frozen
```

---

### B. event settlement

ForgeUnit 可以定义：

```text
unit_start
context_prepared
worker_dispatched
worker_event
worker_completed
evidence_ingested
verification_started
verification_completed
repair_scheduled
unit_end
unit_settled
```

注意 `unit_end` 和 `unit_settled` 分开。

---

### C. execution order vs transcript order

如果未来多 worker 并发，你要分清：

```text
event completion order
semantic source order
ledger append order
graph state update order
```

pi 在 parallel tool execution 里的处理可以直接借鉴。

---

## 7.3 SkillFoundry 应该借 pi 的这些东西

### A. Session tree / branch navigation

SkillFoundry 的构建过程应该天然是树：

```text
FrozenSpec
  -> candidate A
    -> repair A1
    -> repair A2
  -> candidate B
    -> verifier passed
```

每个分支都有 summary 和 evidence。

---

### B. Skill invocation vs model-visible skill listing

SkillFoundry 生成的 skill 可以分：

```text
model_visible: true/false
explicit_invocation_only: true/false
```

有些 capability 不应该让 agent 自由调用，只能由 orchestrator 显式调用。

---

### C. save point

每次通过关键阶段都写 save point：

```text
spec_frozen save point
context_compiled save point
worker_result_ingested save point
verification_passed save point
registry_promoted save point
```

这比只写状态字段更强。

---

# 8. pi 中不建议你照搬的地方

## 8.1 不要把你的体系做成“一个大聊天 agent”

pi 的中心还是 agent conversation/session。

你的中心应该是：

```text
GoalContract
UnitContract
WorkerRun
Evidence
Verification
Artifact
Registry
```

所以可以借 runtime 技术，不要借产品中心。

---

## 8.2 不要把 SkillFoundry skill 降级成 prompt skill

pi 的 skill 比较接近 agent skill prompt resource。  
你的目标是 runtime bundle / capability bundle。  
层级比它更高。

---

## 8.3 不要为了自研 worker 过早复制 tool loop

你前面说暂时不考虑去掉 Codex worker，这个判断是对的。

现在你应该做的是：

```text
Codex remains strong worker
Your system owns:
  contract
  context boundary
  evidence
  verification
  registry
  replay
  steering
```

pi 可以增强你的边界治理，而不是要求你马上重写 Codex。

---

# 9. 我建议你下一步重点深挖 pi 的 5 个源码区

如果要继续系统调研，我建议下一步按这个顺序：

## 1. `packages/agent/src/harness/session/*`

目标：看它 session tree 怎么持久化、fork、leaf、branch summary。

你要借鉴给：

- ContextForge Ledger
- SkillFoundry build tree
- ForgeUnit run history

---

## 2. `packages/agent/src/harness/compaction/compaction.ts`

目标：看它怎么决定哪些消息总结、哪些保留、怎么处理 split turn、file ops。

你要借鉴给：

- ContextForge PromptCachePlan
- Checkpoint summary
- Worker evidence summary

---

## 3. `packages/coding-agent/src/core/agent-session.ts`

这个文件很大，103KB，应该是产品级 agent session 的核心。

目标：看 coding-agent 如何把 harness、tools、UI、session、commands 接起来。

你要借鉴给：

- SkillFoundry orchestration shell
- FrontDesk / Verifier / Registry 集成方式

---

## 4. `packages/coding-agent/src/core/extensions/*`

目标：看它 self-extensible / extension 机制。

你要借鉴给：

- runtime bundle 插件机制
- generated Skill 的安装/加载/调用边界

---

## 5. `packages/coding-agent/src/core/package-manager.ts`

这个文件也很大，77KB。  
考虑 README 里强调 supply-chain hardening，它可能包含安装/更新/依赖治理逻辑。

你要借鉴给：

- SkillFoundry 生成 bundle 后如何安全安装
- dependency policy
- lifecycle script policy
- registry promotion gate

---

# 10. 对你当前路线的直接建议

我建议你不要把“学习 pi”理解成“参考一个更强的 coding agent”。

更应该理解为：

> **pi 是一个真实产品打磨出来的 agent harness 工程样本，它的价值在于暴露了很多复杂任务 runtime 必须面对的工程边界。**

对你最有价值的迁移路线是：

```text
ContextForge:
  学 pi 的 context/session/compaction/hook 设计

ForgeUnit:
  学 pi 的 event lifecycle/tool gate/phase lock/settlement 设计

SkillFoundry:
  学 pi 的 skill/template/session tree/save point/extension 设计
```

你原本的哲学没有错：

```text
LangGraph = 宏观编排
ContextForge = 上下文和证据外骨骼
ForgeUnit = 受控 work unit
SkillFoundry = 实验场和 capability factory
Codex = 强 worker
Verifier = 免疫系统
```

pi 可以帮你补强的是：

```text
运行中怎么插话
状态什么时候落盘
上下文什么时候压缩
session 怎么分支
工具/worker 怎么被 gate
事件什么时候才算 settled
provider/worker 请求怎么 hook
skill/template 怎么规范调用
```

这些都是让项目从“思想正确”走向“工程可靠”的部分。

---

## 总结一句

**pi 值得你深度参考，但不是因为它可以替代 Codex，而是因为它把 agent runtime 中最容易被忽略的工程语义做成了一等公民：事件、队列、session tree、compaction、hook、phase、settlement、skill invocation。**

如果你把这些思想吸收到 `ContextForge / ForgeUnit / SkillFoundry`，你的体系会更像一个成熟的复杂任务 harness，而不是只依赖 Codex worker 的外壳。

[^1]: [pi `agent-loop.ts`](https://raw.githubusercontent.com/earendil-works/pi/main/packages/agent/src/agent-loop.ts)  
[^2]: [pi `agent.ts`](https://raw.githubusercontent.com/earendil-works/pi/main/packages/agent/src/agent.ts)  
[^3]: [pi `types.ts`](https://raw.githubusercontent.com/earendil-works/pi/main/packages/agent/src/types.ts)  
[^4]: [pi `agent-harness.ts`](https://raw.githubusercontent.com/earendil-works/pi/main/packages/agent/src/harness/agent-harness.ts)  
[^5]: [pi harness `types.ts`](https://raw.githubusercontent.com/earendil-works/pi/main/packages/agent/src/harness/types.ts)  
[^6]: [pi coding-agent core directory](https://api.github.com/repos/earendil-works/pi/contents/packages/coding-agent/src/core?ref=main)  
[^7]: [pi `AGENTS.md`](https://raw.githubusercontent.com/earendil-works/pi/main/AGENTS.md)