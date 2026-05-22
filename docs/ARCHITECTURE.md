# SkillFoundry 架构设计 v0.2

> Historical note: this document describes the v0/WP0-WP12 architecture. It is
> retained for product and security context, but it is not the v2 execution
> authority. Current v2 architecture and migration decisions live in
> `docs/SKILLFOUNDRY_CONTEXTFORGE_REFACTOR_PLAN.md`. In v2, ContextForge is the
> Goal Harness / agent exoskeleton for strong agent nodes, not only a recorder
> for SkillFoundry-owned LLM calls.

## 1. 架构定位

SkillFoundry 的第一阶段是 **外部 worker 监督型 Codex Skill 工厂**。

它不自建完整 ActionRuntime，也不把 ContextForge 描述成能够控制所有 worker 内部过程的总线。系统边界是：

```text
User Requirement
  -> LangGraph workflow
  -> SkillFoundry-owned LLM nodes through ContextForge
  -> Workspace protocol
  -> WorkerAdapter
  -> external Codex Worker or FakeWorker
  -> independent Verifier
  -> Registry gate
  -> Verification report
```

关键原则：

- LangGraph 管流程和轻量状态；
- Workspace 管文件即上下文协议；
- WorkerAdapter 管外部 worker 调用边界；
- Codex Worker 是黑盒 builder；
- ContextForge 管 SkillFoundry 自有 LLM 调用，并记录 worker 边界证据；
- Verifier 是主质量门；
- Registry 只保存 approved asset。

## 2. 系统层次

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

各层之间通过文件引用、hash、manifest 和机器可读结果连接，避免把长文本和不可控内部状态塞进 LangGraph state。

## 3. LangGraph State 边界

LangGraph 只保存流程决策所需的轻量引用。

允许保存：

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

禁止保存：

```text
完整 Skill package
完整 worker transcript
raw tool logs
完整 replay bundle
大型 prompt 正文
完整 verification logs
```

原因：

- checkpoint 应该可控、轻量、可恢复；
- 大 artifact 应由 workspace 和 artifact store 管；
- worker 黑盒内部记录不应伪装成 LangGraph 可控状态；
- 验收证据需要 hash 和 manifest，而不是聊天上下文。

## 4. Workspace 协议

Workspace 是系统的事实边界。每个 job 必须有独立目录：

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

### 4.1 锁定输入

构建前必须锁定：

- `build_contract.yaml`；
- `skill_spec.yaml`；
- `verification_spec.yaml`；
- `worker_input.md`；
- 初始 artifact manifest。

锁定意味着：

- 内容 hash 写入 manifest；
- 后续 attempt 引用 hash；
- verifier 能发现锁定输入被修改；
- registry 记录最终使用的 spec 和 verification spec hash。

### 4.2 写权限

第一阶段的保守规则：

- worker 只能写 `package/` 和当前 `attempts/<n>/`；
- verifier 只能写 `verifier/`；
- registry 只能由平台写；
- ContextForge artifact 只能由 ContextForge adapter 写；
- 所有路径必须 resolve 后确认仍在 job workspace 内；
- 符号链接、`..`、绝对路径和隐藏跳转必须被路径策略处理。

### 4.3 Artifact Manifest

`artifact_manifest.json` 至少记录：

```text
artifact_id
path
kind
sha256
created_by
created_at
job_id
attempt_id
locked
```

任何参与验收或注册的文件都必须有 manifest 记录和 hash。

## 5. WorkerAdapter 边界

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

### 5.1 FakeWorker

WP3 先实现 FakeWorker，用于协议和 Verifier 闭环验证。

FakeWorker 应支持：

- 生成一个最小 Skill package；
- 生成一个故意失败 package；
- 根据 repair input 修复；
- 模拟缺失 execution report；
- 模拟路径越权尝试。

### 5.2 CodexWorker

CodexWorker 是真实外部 worker 适配器。它只能在 WP1-WP7 通过后试点。

SkillFoundry 对 CodexWorker 的声明边界：

- 可以规定输入文件、可写目录、timeout、attempt limit；
- 可以记录 transcript、diff、execution report、hash、duration；
- 可以记录 usage 不可得原因；
- 不能控制或 replay Codex 内部 prompt、tool loop、context compaction、cache 或 cost。

CodexWorker 的成功输出仍必须通过 Verifier；builder self-report 不是 acceptance evidence。

## 6. ContextForge 集成点

ContextForge 在 SkillFoundry 中有两个角色。

### 6.1 Owned LLM Call Runtime

SkillFoundry 自有 LLM 节点必须走：

```text
ContextRequest
  -> PromptView
  -> ModelCallEnvelope
  -> ContextKernel.invoke_model()
  -> ModelCallRecord / UsageRecord / ReplayBundle
```

适用节点：

- clarify；
- spec_generate；
- route；
- failure_analyze；
- repair_plan；
- optional_llm_judge；
- report_summary。

这些调用可以要求 prompt 可归因、memory 显式注入、tool output governance、usage 记录和 replay artifact。

### 6.2 Worker Boundary Evidence Ledger

Codex Worker 不是 owned LLM call。ContextForge 对它只做边界证据记录：

- worker invocation id；
- input manifest；
- workspace hash；
- transcript artifact ref；
- output diff ref；
- execution report ref；
- duration；
- verifier result ref；
- registry decision ref；
- usage availability 或 unavailable reason。

禁止在架构文档或实现中声称：

- Codex Worker 内部 prompt 属于 ContextForge 可控范围；
- Codex Worker 内部 tool loop 属于 ContextForge replay 范围；
- Codex Worker prompt cache 由 ContextForge 掌握；
- 真实 Codex integration、sandbox、shell runtime、MCP runtime、权限系统、队列或 UI 已由 ContextForge 提供。

## 7. Verifier Gate

Verifier 是独立主质量门。它的输入来自 workspace 和 manifest，不来自 builder 自报。

第一版检查：

- package 结构；
- `SKILL.md` required sections；
- trigger / non-trigger scenarios；
- required inputs / expected outputs；
- reference 和 script 路径安全；
- path confinement；
- artifact manifest 完整性；
- hash 一致性；
- verification result schema；
- sandbox smoke；
- fixture case；
- 可选 LLM judge。

硬规则：

- LLM judge 不能是唯一 gate；
- builder self-report 不能作为 pass 证据；
- 缺 required section 必 fail；
- 路径穿越必 fail；
- hash mismatch 必 fail；
- 缺 artifact manifest 必 fail；
- verifier 失败时 registry 必须拒绝。

## 8. Registry 信任模型

Registry 是 approved asset store。它信任的是 Verifier 和 hash，不信任 builder 自报。

Registry 写入条件：

- `VerificationResult.passed == true`；
- package hash 与 manifest 一致；
- verification spec hash 已记录；
- worker invocation 已记录；
- artifact manifest hash 已记录；
- approval status 明确；
- quarantine status 明确。

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

Registry 需要支持后续 quarantine 和 rollback。被 quarantine 的 Skill 不能作为默认复用候选。

## 9. 安全基线

WP1-WP8 必须保持 fail-closed。

安全基线：

- 默认拒绝 workspace 外路径；
- 默认拒绝未声明写路径；
- 默认拒绝缺失 manifest 的关键 artifact；
- 默认拒绝 hash mismatch；
- 默认拒绝 verifier 未通过 package；
- 默认不把 raw logs 直接注入 prompt；
- 默认不把 worker transcript 当作可信事实；
- timeout 和 attempt limit 必填；
- environment allowlist 必填；
- registry 不接受 builder self-report；
- unsafe requirement 可 route 到 reject 或 human review。

## 10. 端到端数据流

```text
User Requirement
  -> intake
  -> owned LLM clarify through ContextForge
  -> SkillSpec
  -> owned LLM route through ContextForge
  -> BuildContract + VerificationSpec
  -> workspace locked inputs
  -> WorkerAdapter invocation
  -> external worker writes package and attempt artifacts
  -> ContextForge records worker boundary evidence
  -> Verifier reads package, specs, manifest, hashes
  -> VerificationResult
  -> repair loop or Registry gate
  -> approved RegistryEntry
  -> final Verification Report
```

这个数据流的验收重点是边界证据和独立验证，而不是 worker 的内部自述。
