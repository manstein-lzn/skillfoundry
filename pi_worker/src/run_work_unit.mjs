#!/usr/bin/env node

import { existsSync, lstatSync, readFileSync, realpathSync } from "node:fs";
import { appendFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { register } from "node:module";
import { dirname, resolve } from "node:path";

import {
  createAssistantMessageEventStream,
  fauxAssistantMessage,
  fauxText,
  fauxToolCall,
  registerFauxProvider,
} from "./pi_ai_shim.mjs";

const AGENT_ENTRYPOINT = new URL("../../../pi/packages/agent/src/agent.ts", import.meta.url);
const OUTPUT_SCHEMA_VERSION = "skillfoundry.pi_worker_output.v1";

register(new URL("./pi_ai_loader.mjs", import.meta.url));

const inputPath = process.argv[2];

if (!inputPath) {
  console.error("usage: node run_work_unit.mjs <pi_worker_input.json>");
  process.exit(2);
}

const input = JSON.parse(await readFile(inputPath, "utf-8"));
const workspaceRoot = resolve(String(input.workspace_root));
const expectedOutputs = normalizeExpectedOutputs(input.contract?.expected_outputs);
const allowedScope = normalizeRefList(input.contract?.allowed_scope);
const broadOutputRefs = expectedOutputs.filter((ref) => !isConcreteFileRef(ref));
const concreteOutputRefs = expectedOutputs.filter((ref) => isConcreteFileRef(ref));
const artifactTargets =
  concreteOutputRefs.length > 0 ? concreteOutputRefs : defaultArtifactTargetsForBroadOutputs(broadOutputRefs);
const visibleRefs = normalizeRefList(input.contract?.visible_refs);
const eventAppendDelayMs = nonNegativeIntegerFromEnv("PI_WORKER_EVENT_APPEND_DELAY_MS");
const providerMode = normalizeProviderMode(input.runtime?.model_provider ?? process.env.PI_WORKER_PROVIDER ?? "faux");
const events = [];
const writtenArtifactRefs = new Set();
let toolExecutions = 0;
let modelCalls = 0;
let assistantUsage = {
  input: 0,
  output: 0,
  cacheRead: 0,
  cacheWrite: 0,
  totalTokens: 0,
  cost: {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
    total: 0,
  },
};

const workspaceListRefsTool = {
  label: "Workspace refs",
  name: "list_workspace_refs",
  description: "List visible refs and writable scope roots for this SkillFoundry work unit.",
  parameters: {
    type: "object",
    additionalProperties: false,
    properties: {},
  },
  execute: async () => ({
    content: [
      {
        type: "text",
        text: JSON.stringify(
          {
            visible_refs: visibleRefs,
            allowed_scope: allowedScope,
            expected_outputs: expectedOutputs,
            concrete_artifact_targets: artifactTargets,
            broad_output_refs: broadOutputRefs,
          },
          null,
          2,
        ),
      },
    ],
    details: {
      visible_refs: visibleRefs,
      allowed_scope: allowedScope,
      expected_outputs: artifactTargets,
    },
  }),
};

const workspaceReadRefTool = {
  label: "Read ref",
  name: "read_workspace_ref",
  description: "Read a visible workspace-relative ref from this SkillFoundry work unit.",
  parameters: {
    type: "object",
    additionalProperties: false,
    properties: {
      path: { type: "string" },
    },
    required: ["path"],
  },
  execute: async (_toolCallId, args) => {
    const ref = normalizeRelativeRef(String(args.path));
    if (!isVisibleRef(ref)) {
      throw new Error(`Ref is not visible to this work unit: ${ref}`);
    }
    const path = resolveWorkspacePath(workspaceRoot, ref, { mustExist: true });
    const text = await readFile(path, "utf-8");
    return {
      content: [{ type: "text", text }],
      details: { path: ref, bytes: Buffer.byteLength(text, "utf8") },
    };
  },
};

const workspaceWriteArtifactTool = {
  label: "Artifact writer",
  name: "write_workspace_artifact",
  description: "Write a workspace-relative artifact under the allowed SkillFoundry work-unit scope.",
  parameters: {
    type: "object",
    additionalProperties: false,
    properties: {
      path: { type: "string" },
      content: { type: "string" },
    },
    required: ["path", "content"],
  },
  execute: async (_toolCallId, args, signal) => {
    if (signal?.aborted) {
      throw new Error("Operation aborted");
    }
    const ref = normalizeRelativeRef(String(args.path));
    if (!isAllowedWriteRef(ref)) {
      throw new Error(`Ref is outside allowed write scope: ${ref}`);
    }
    const content = ref === "package/skillfoundry.bundle.json" ? canonicalBundleManifestContent(input) : String(args.content);
    await writeWorkspaceText(workspaceRoot, ref, content);
    writtenArtifactRefs.add(ref);
    return {
      content: [{ type: "text", text: `wrote ${ref}` }],
      details: { path: ref, bytes: Buffer.byteLength(content, "utf8") },
    };
  },
};

const startedAt = Date.now();
const runtime = configureRuntime(providerMode);

if (runtime.faux) {
  runtime.faux.setResponses([
    () => {
      const content = [fauxText("Preparing the requested artifacts.")];
      content.push(fauxToolCall("list_workspace_refs", {}, { id: "list-refs" }));
      visibleRefs.forEach((ref, index) => {
        if (existsSync(resolve(workspaceRoot, ref))) {
          content.push(fauxToolCall("read_workspace_ref", { path: ref }, { id: `read-${index + 1}` }));
        }
      });
      artifactTargets.forEach((ref, index) => {
        content.push(
          fauxToolCall(
            "write_workspace_artifact",
            { path: ref, content: artifactContentFor(input, ref) },
            { id: `write-${index + 1}` },
          ),
        );
      });
      return fauxAssistantMessage(content, {
        stopReason: content.some((block) => block.type === "toolCall") ? "toolUse" : "stop",
      });
    },
    (context) => {
      const toolResults = context.messages.filter((message) => message.role === "toolResult");
      const writtenPaths = toolResults
        .flatMap((message) =>
          message.content
            .filter((block) => block.type === "text")
            .map((block) => block.text),
        )
        .filter(Boolean);
      return fauxAssistantMessage(
        `Completed ${writtenPaths.length || artifactTargets.length} artifact(s): ${artifactTargets.join(", ")}.`,
      );
    },
  ]);
}

const { Agent } = await import(AGENT_ENTRYPOINT.href);

const agent = new Agent({
  initialState: {
    systemPrompt: buildSystemPrompt(input),
    model: runtime.model,
    thinkingLevel: runtime.thinkingLevel,
    tools: [workspaceListRefsTool, workspaceReadRefTool, workspaceWriteArtifactTool],
  },
  sessionId: String(input.job_id ?? "pi-worker"),
  toolExecution: "sequential",
  ...(runtime.streamFn ? { streamFn: runtime.streamFn } : {}),
});

agent.subscribe(async (event) => {
  events.push(event);
  if (event.type === "tool_execution_start") {
    toolExecutions += 1;
  }
  await appendWorkspaceJsonLine(workspaceRoot, input.events_ref, event);
  if (eventAppendDelayMs > 0) {
    await sleep(eventAppendDelayMs);
  }
});

await writeWorkspaceText(workspaceRoot, input.events_ref, "");
await agent.prompt(buildPrompt(input, artifactTargets));

const assistantMessages = agent.state.messages.filter((message) => message.role === "assistant");
for (const message of assistantMessages) {
  assistantUsage.input += message.usage?.input ?? 0;
  assistantUsage.output += message.usage?.output ?? 0;
  assistantUsage.cacheRead += message.usage?.cacheRead ?? 0;
  assistantUsage.cacheWrite += message.usage?.cacheWrite ?? 0;
  assistantUsage.totalTokens += message.usage?.totalTokens ?? 0;
  assistantUsage.cost.input += message.usage?.cost?.input ?? 0;
  assistantUsage.cost.output += message.usage?.cost?.output ?? 0;
  assistantUsage.cost.cacheRead += message.usage?.cost?.cacheRead ?? 0;
  assistantUsage.cost.cacheWrite += message.usage?.cost?.cacheWrite ?? 0;
  assistantUsage.cost.total += message.usage?.cost?.total ?? 0;
}

const producedArtifacts = uniqueRefs([
  ...artifactTargets.filter((ref) => safeWorkspaceExists(workspaceRoot, ref)),
  ...Array.from(writtenArtifactRefs).filter((ref) => safeWorkspaceExists(workspaceRoot, ref)),
]);
const missingArtifacts = artifactTargets.filter((ref) => !producedArtifacts.includes(ref));
const status = missingArtifacts.length === 0 ? "completed" : "failed";
const failures = missingArtifacts.map((ref) => `expected artifact was not produced: ${ref}`);
const changedRefs = uniqueRefs([
  ...producedArtifacts,
  input.output_ref,
  input.session_ref,
  input.events_ref,
  input.metrics_ref,
]);

await writeJsonLines(
  workspaceRoot,
  input.session_ref,
  agent.state.messages.map((message) => ({
    role: message.role,
    message,
  })),
);

const metrics = {
  runtime: runtime.runtimeName,
  provider_mode: runtime.providerMode,
  model_provider: runtime.model.provider,
  model: runtime.model.id,
  usage_source: runtime.usageSource,
  model_calls: Math.max(modelCalls, assistantMessages.length),
  tool_calls: toolExecutions,
  visible_ref_count: visibleRefs.length,
  allowed_scope_count: allowedScope.length,
  produced_artifact_count: producedArtifacts.length,
  cache_read_tokens: assistantUsage.cacheRead,
  cache_write_tokens: assistantUsage.cacheWrite,
  input_tokens: assistantUsage.input,
  output_tokens: assistantUsage.output,
  total_tokens: assistantUsage.totalTokens,
  cache_hit_ratio: cacheHitRatio(assistantUsage),
  cost_input: assistantUsage.cost.input,
  cost_output: assistantUsage.cost.output,
  cost_cache_read: assistantUsage.cost.cacheRead,
  cost_cache_write: assistantUsage.cost.cacheWrite,
  cost_total: assistantUsage.cost.total,
  assistant_messages: assistantMessages.length,
  event_count: events.length,
};

await writeWorkspaceJson(workspaceRoot, input.metrics_ref, metrics);

const output = {
  schema_version: OUTPUT_SCHEMA_VERSION,
  job_id: input.job_id,
  iteration: input.iteration,
  status,
  produced_artifacts: producedArtifacts,
  changed_refs: changedRefs,
  commands_run: [formatCommand([...normalizeCommand(input.runtime?.command), inputPath])],
  tests_run: [],
  failures,
  worker_claims: [buildWorkerClaim(producedArtifacts.length, runtime.providerMode)],
  verifier_evidence: [input.events_ref, input.metrics_ref, ...producedArtifacts],
  new_unknowns: missingArtifacts,
  recommended_next_steps:
    status === "completed"
      ? ["Run SkillFoundry verifier on the PiWorker output."]
      : ["Inspect PiWorker tool events and allowed_scope before retrying."],
  verification_status: status === "completed" ? "not_run" : "failed",
  input_ref: input.input_ref,
  output_ref: input.output_ref,
  session_ref: input.session_ref,
  events_ref: input.events_ref,
  metrics_ref: input.metrics_ref,
  duration_ms: Date.now() - startedAt,
  metrics,
};

await writeWorkspaceJson(workspaceRoot, input.output_ref, output);

function buildSystemPrompt(inputData) {
  return [
    "You are PiWorker's owned Agent runtime.",
    "Your job is to materialize workspace artifacts, not to describe them.",
    "Use write_workspace_artifact to create each requested artifact before stopping.",
    "A text-only response does not satisfy the work-unit contract.",
    "When writing package/SKILL.md, produce a real skill with a title and the sections Overview, When To Use, When Not To Use, Inputs, Outputs, Workflow, and Safety.",
    "When writing package/skillfoundry.bundle.json, emit the canonical skillfoundry.bundle.v1 prompt_only manifest with no extra top-level fields.",
    "When frontdesk/task_contract.json is visible, treat it as the authoritative frozen product contract.",
    "Keep the skill specific to the objective and do not mirror raw logs or secrets.",
    `Job: ${inputData.job_id}`,
    `Iteration: ${inputData.iteration}`,
    `Objective: ${inputData.contract?.next_objective ?? "Generate the requested artifacts."}`,
  ].join("\n");
}

function buildPrompt(inputData, targets) {
  const excerpts = visibleRefExcerpts();
  return [
    `Generate these concrete workspace-relative artifacts by calling write_workspace_artifact: ${targets.join(", ")}`,
    `Expected outputs from the work-unit contract: ${expectedOutputs.join(", ") || "(none)"}`,
    broadOutputRefs.length
      ? `Directory-like expected outputs are writable scopes, not file paths: ${broadOutputRefs.join(", ")}. Write concrete files under those scopes; never write the directory path itself.`
      : "",
    "Do not answer only in text; the artifact must be written through the tool.",
    `Why now: ${inputData.contract?.why_now ?? "Run the owned runtime boundary."}`,
    "Use visible FrontDesk task-contract content for product intent; the next-step contract only bounds the current work unit.",
    `Visible refs: ${visibleRefs.join(", ") || "(none)"}`,
    `Allowed scope: ${allowedScope.join(", ") || "(none)"}`,
    `Exit criteria: ${(inputData.contract?.exit_criteria ?? []).join(" | ") || "Artifacts written."}`,
    excerpts ? `Visible ref excerpts:\n${excerpts}` : "",
  ].join("\n");
}

function artifactContentFor(inputData, ref) {
  if (ref === "package/SKILL.md") {
    return [
      "# PiWorker Skill",
      "",
      `Job: ${inputData.job_id}`,
      `Iteration: ${inputData.iteration}`,
      "",
      "## Objective",
      String(inputData.contract?.next_objective ?? "Generate the requested artifact."),
      "",
      "## Overview",
      "This skill boundary was generated by PiWorker as a governed workspace artifact.",
      "",
      "## When To Use",
      "Use this skill when you need a small, explicit workspace-bound skill package that must be written through the PiWorker tool loop.",
      "",
      "## When Not To Use",
      "Do not use this skill for unconstrained shell work, raw log mirroring, or secret handling.",
      "",
      "## Inputs",
      "- `skill_spec.yaml`",
      "- `verification_spec.yaml`",
      "- `adaptive/attempts/*/pi_worker_input.json`",
      "",
      "## Outputs",
      "- `package/SKILL.md`",
      "- `package/skillfoundry.bundle.json`",
      "",
      "## Workflow",
      "1. Inspect visible workspace refs.",
      "2. Write only within the allowed scope.",
      "3. Stop once the requested artifacts exist.",
      "",
      "## Safety",
      "- Keep secrets out of workspace artifacts.",
      "- Fail closed on out-of-scope writes and symlink targets.",
      "",
    ].join("\n");
  }

  if (ref === "package/skillfoundry.bundle.json") {
    return canonicalBundleManifestContent(inputData);
  }

  if (ref === "package/Cargo.toml") {
    return [
      "[package]",
      `name = "${safeCargoPackageName(inputData.job_id ?? "pi-worker-skill")}"`,
      'version = "0.1.0"',
      'edition = "2021"',
      "",
      "[lib]",
      'path = "src/lib.rs"',
      "",
    ].join("\n");
  }

  if (ref === "package/src/lib.rs" || ref.endsWith("/src/lib.rs")) {
    return [
      "pub fn validate_path(path: &str) -> Result<(), String> {",
      '    if path.is_empty() || path.starts_with("/") || path.contains("..") {',
      '        return Err("unsafe path".to_string());',
      "    }",
      "    Ok(())",
      "}",
      "",
      "#[cfg(test)]",
      "mod tests {",
      "    use super::validate_path;",
      "",
      "    #[test]",
      "    fn rejects_parent_traversal() {",
      '        assert!(validate_path("../secret").is_err());',
      "    }",
      "",
      "    #[test]",
      "    fn accepts_relative_wiki_page() {",
      '        assert!(validate_path("projects/demo.md").is_ok());',
      "    }",
      "}",
      "",
    ].join("\n");
  }

  if (ref.endsWith("/repair_evidence.md")) {
    return [
      "# Repair Evidence",
      "",
      "PiWorker wrote concrete package artifacts requested by the adaptive repair contract.",
      "",
    ].join("\n");
  }

  return [
    `# Artifact: ${ref}`,
    "",
    "Generated by PiWorker.",
    "",
  ].join("\n");
}

function canonicalBundleManifestContent(inputData) {
  return (
    JSON.stringify(
      {
        schema_version: "skillfoundry.bundle.v1",
        bundle_id: String(inputData.job_id),
        bundle_type: "prompt_only",
        entrypoint: "SKILL.md",
        capability_surface: {},
        runtime_assets: [],
        data_assets: [],
        references: [],
        environment: {},
        permissions: {},
        verification: {},
        distribution: {},
      },
      null,
      2,
    ) + "\n"
  );
}

function safeCargoPackageName(value) {
  const normalized = String(value)
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  const safe = normalized || "pi-worker-skill";
  return /^[a-zA-Z]/.test(safe) ? safe : `skill-${safe}`;
}

function visibleRefExcerpts() {
  const excerpts = [];
  let remaining = 12000;
  for (const ref of visibleRefs) {
    if (remaining <= 0) {
      break;
    }
    if (!isTextLikeRef(ref)) {
      continue;
    }
    const text = readVisibleWorkspaceText(ref, Math.min(remaining, 4000));
    if (!text) {
      continue;
    }
    remaining -= text.length;
    excerpts.push(`--- ${ref} ---\n${text}`);
  }
  return excerpts.join("\n\n");
}

function readVisibleWorkspaceText(ref, limit = 8000) {
  const normalized = normalizeRelativeRef(String(ref));
  if (!isVisibleRef(normalized) || !isTextLikeRef(normalized)) {
    return "";
  }
  try {
    const path = resolveWorkspacePath(workspaceRoot, normalized, { mustExist: true });
    const text = readFileSync(path, "utf-8");
    return text.length > limit ? `${text.slice(0, limit)}\n[truncated]` : text;
  } catch {
    return "";
  }
}

function isTextLikeRef(ref) {
  return /\.(json|jsonl|md|txt|yaml|yml)$/i.test(ref);
}

async function writeWorkspaceText(root, ref, text) {
  const path = resolveWorkspacePath(root, ref);
  if (existsSync(path)) {
    const stats = lstatSync(path);
    if (!stats.isFile()) {
      throw new Error(`Target path is not a regular file: ${path}`);
    }
  }
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, text, "utf-8");
}

async function writeWorkspaceJson(root, ref, payload) {
  await writeWorkspaceText(root, ref, JSON.stringify(payload, null, 2) + "\n");
}

async function writeJsonLines(root, ref, entries) {
  const lines = entries.map((entry) => JSON.stringify(entry)).join("\n") + "\n";
  await writeWorkspaceText(root, ref, lines);
}

async function appendWorkspaceJsonLine(root, ref, entry) {
  const path = resolveWorkspacePath(root, ref);
  await mkdir(dirname(path), { recursive: true });
  await appendFile(path, `${JSON.stringify(entry)}\n`, "utf-8");
}

function nonNegativeIntegerFromEnv(name) {
  const value = process.env[name];
  if (value === undefined || value === "") {
    return 0;
  }
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) {
    throw new Error(`${name} must be a non-negative integer`);
  }
  return parsed;
}

function sleep(ms) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

function normalizeExpectedOutputs(value) {
  return normalizeRefList(value);
}

function defaultArtifactTargetsForBroadOutputs(refs) {
  if (!refs.length) {
    return ["package/SKILL.md"];
  }
  const targets = [];
  for (const ref of refs) {
    if (ref === "package") {
      targets.push("package/SKILL.md");
    } else {
      targets.push(`${ref.replace(/\/+$/, "")}/repair_evidence.md`);
    }
  }
  if (typeof input.attempt_dir_ref === "string" && input.attempt_dir_ref) {
    const repairEvidenceRef = `${normalizeRelativeRef(input.attempt_dir_ref)}/repair_evidence.md`;
    if (isAllowedWriteRef(repairEvidenceRef)) {
      targets.push(repairEvidenceRef);
    }
  }
  return uniqueRefs(targets);
}

function isConcreteFileRef(ref) {
  return /(^|\/)[^/]+\.[A-Za-z0-9][A-Za-z0-9._-]*$/.test(ref);
}

function normalizeRefList(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item) => typeof item === "string" && item.length > 0)
    .map((item) => normalizeRelativeRef(item));
}

function normalizeRelativeRef(ref) {
  const normalized = ref.replace(/\\/g, "/");
  if (!normalized || normalized.startsWith("/") || /^[A-Za-z]:/.test(ref)) {
    throw new Error(`Invalid workspace ref: ${ref}`);
  }
  if (normalized.includes("\0") || normalized.split("/").some((segment) => segment === "" || segment === "." || segment === "..")) {
    throw new Error(`Invalid workspace ref: ${ref}`);
  }
  return normalized;
}

function isVisibleRef(ref) {
  return visibleRefs.includes(ref);
}

function isAllowedWriteRef(ref) {
  return allowedScope.some((scopeRef) => ref === scopeRef || ref.startsWith(`${scopeRef.replace(/\/+$/, "")}/`));
}

function uniqueRefs(refs) {
  const seen = new Set();
  const result = [];
  for (const ref of refs) {
    if (typeof ref !== "string" || ref.length === 0) {
      continue;
    }
    if (seen.has(ref)) {
      continue;
    }
    seen.add(ref);
    result.push(ref);
  }
  return result;
}

function formatCommand(args) {
  return args.join(" ");
}

function normalizeCommand(command) {
  if (!Array.isArray(command)) {
    return [];
  }
  return command.filter((part) => typeof part === "string" && part.length > 0);
}

function buildWorkerClaim(producedCount, providerMode) {
  const providerLabel = providerMode === "live" ? "live provider" : "deterministic faux provider";
  return producedCount > 0
    ? `Pi Agent runtime wrote ${producedCount} artifact(s) through a ${providerLabel}.`
    : "Pi Agent runtime completed without producing artifacts.";
}

function configureRuntime(mode) {
  if (mode === "faux") {
    const faux = registerFauxProvider({
      api: "pi-agent-faux",
      provider: "pi-worker",
      models: [
        {
          id: "pi-agent-faux-1",
          name: "Pi Agent Faux",
          reasoning: false,
          input: ["text", "image"],
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
          contextWindow: 128000,
          maxTokens: 16384,
        },
      ],
    });
    return {
      runtimeName: "pi-agent-faux",
      providerMode: "faux",
      usageSource: "estimated",
      model: faux.getModel(),
      thinkingLevel: "off",
      faux,
      streamFn: null,
    };
  }

  const modelId = String(input.runtime?.model || process.env.PI_WORKER_MODEL || "gpt-5.5");
  const baseUrl = stripTrailingSlash(
    String(input.runtime?.metadata?.base_url || process.env.PI_WORKER_BASE_URL || "https://apihub.cwise.dev"),
  );
  const apiKey = String(process.env.PI_WORKER_API_KEY || process.env.OPENAI_API_KEY || "");
  if (!apiKey) {
    throw new Error("PI_WORKER_API_KEY or OPENAI_API_KEY is required when PI_WORKER_PROVIDER=live");
  }
  const model = {
    id: modelId,
    name: modelId,
    api: "pi-worker-openai-responses",
    provider: "pi-worker-live",
    baseUrl,
    reasoning: true,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 400000,
    maxTokens: Number(input.runtime?.metadata?.max_tokens || process.env.PI_WORKER_MAX_TOKENS || 4096),
  };
  return {
    runtimeName: "pi-agent-live",
    providerMode: "live",
    usageSource: "provider_reported",
    model,
    thinkingLevel: String(input.runtime?.metadata?.thinking_level || process.env.PI_WORKER_THINKING_LEVEL || "xhigh"),
    faux: null,
    streamFn: (requestModel, context, options) =>
      streamOpenAICompatibleResponses(requestModel, context, {
        ...options,
        apiKey,
        baseUrl,
        reasoningEffort: liveReasoningEffort(context),
        toolChoice: liveToolChoice(context),
      }),
  };
}

function streamOpenAICompatibleResponses(model, context, options = {}) {
  const stream = createAssistantMessageEventStream();
  modelCalls += 1;
  queueMicrotask(async () => {
    const output = assistantMessage({
      api: model.api,
      provider: model.provider,
      model: model.id,
    });
    try {
      const response = await fetch(openAIEndpointUrl(options.baseUrl, "responses"), {
        method: "POST",
        headers: {
          authorization: `Bearer ${options.apiKey}`,
          "content-type": "application/json",
        },
        body: JSON.stringify(buildResponsesPayload(model, context, options)),
        signal: options.signal,
      });
      const text = await response.text();
      let payload;
      try {
        payload = text ? JSON.parse(text) : {};
      } catch (error) {
        throw new Error(`OpenAI-compatible response was not JSON: ${text.slice(0, 500)}`);
      }
      if (!response.ok) {
        throw new Error(`OpenAI-compatible API error (${response.status}): ${extractErrorMessage(payload)}`);
      }
      applyResponsesPayload(output, payload, model);
      stream.push({ type: "start", partial: cloneJson(output) });
      emitContentEvents(stream, output);
      stream.push({ type: "done", reason: output.stopReason, message: output });
      stream.end(output);
    } catch (error) {
      output.stopReason = options.signal?.aborted ? "aborted" : "error";
      output.errorMessage = error instanceof Error ? error.message : String(error);
      stream.push({ type: "error", reason: output.stopReason, error: output });
      stream.end(output);
    }
  });
  return stream;
}

function buildResponsesPayload(model, context, options) {
  const payload = {
    model: model.id,
    input: responsesInput(context),
    tools: responsesTools(context.tools ?? []),
    tool_choice: responsesToolChoice(options.toolChoice),
    store: false,
    max_output_tokens: model.maxTokens,
  };
  const promptCacheKey = livePromptCacheKey();
  if (promptCacheKey) {
    payload.prompt_cache_key = promptCacheKey;
  }
  if (model.reasoning && options.reasoningEffort) {
    payload.reasoning = { effort: options.reasoningEffort };
  }
  return payload;
}

function responsesInput(context) {
  const messages = [];
  if (context.systemPrompt) {
    messages.push({ role: "system", content: context.systemPrompt });
  }
  for (const message of context.messages) {
    if (message.role === "user") {
      messages.push({ role: "user", content: messageContentText(message) });
    } else if (message.role === "assistant") {
      const toolCalls = message.content.filter((block) => block.type === "toolCall");
      const text = message.content.filter((block) => block.type === "text").map((block) => block.text).join("\n");
      if (text) {
        messages.push({ role: "assistant", content: text });
      }
      for (const toolCall of toolCalls) {
        messages.push({
          type: "function_call",
          call_id: String(toolCall.id).split("|")[0],
          name: toolCall.name,
          arguments: JSON.stringify(toolCall.arguments ?? {}),
        });
      }
    } else if (message.role === "toolResult") {
      messages.push({
        type: "function_call_output",
        call_id: String(message.toolCallId).split("|")[0],
        output: messageContentText(message),
      });
    }
  }
  return messages;
}

function responsesTools(tools) {
  return tools.map((tool) => ({
    type: "function",
    name: tool.name,
    description: tool.description,
    parameters: tool.parameters ?? { type: "object", properties: {} },
    strict: true,
  }));
}

function responsesToolChoice(value) {
  if (value === undefined || value === null || value === "") {
    return "auto";
  }
  const normalized = String(value).trim();
  if (["auto", "required", "none"].includes(normalized)) {
    return normalized;
  }
  return { type: "function", name: normalized };
}

function liveToolChoice(context) {
  const configured = input.runtime?.metadata?.tool_choice || process.env.PI_WORKER_TOOL_CHOICE;
  if (configured !== undefined && configured !== null && configured !== "") {
    return configured;
  }
  if (context.messages.some((message) => message.role === "toolResult" && message.toolName === "write_workspace_artifact" && message.isError)) {
    return "none";
  }
  const missingArtifacts = artifactTargets.filter((ref) => !safeWorkspaceExists(workspaceRoot, ref));
  return missingArtifacts.length > 0 ? "write_workspace_artifact" : "none";
}

function liveReasoningEffort(context) {
  const missingArtifacts = artifactTargets.filter((ref) => !safeWorkspaceExists(workspaceRoot, ref));
  const forceReasoning = String(
    input.runtime?.metadata?.reasoning_with_tools || process.env.PI_WORKER_REASONING_WITH_TOOLS || "",
  )
    .trim()
    .toLowerCase();
  if (missingArtifacts.length > 0 && !["1", "true", "yes", "on"].includes(forceReasoning)) {
    return "";
  }
  return String(input.runtime?.metadata?.reasoning_effort || process.env.PI_WORKER_REASONING_EFFORT || "xhigh");
}

function livePromptCacheKey() {
  const configured = input.runtime?.metadata?.prompt_cache_key ?? process.env.PI_WORKER_PROMPT_CACHE_KEY;
  if (configured === undefined || configured === null || configured === "") {
    return "";
  }
  return String(configured);
}

function messageContentText(message) {
  if (typeof message.content === "string") {
    return message.content;
  }
  if (!Array.isArray(message.content)) {
    return "";
  }
  return message.content
    .filter((block) => block.type === "text")
    .map((block) => block.text)
    .join("\n");
}

function applyResponsesPayload(output, payload, model) {
  output.responseId = payload.id;
  const content = [];
  for (const item of payload.output ?? []) {
    if (item.type === "message") {
      const text = (item.content ?? [])
        .map((part) => part.text ?? part.refusal ?? "")
        .filter(Boolean)
        .join("");
      if (text) {
        content.push(fauxText(text));
      }
    } else if (item.type === "function_call") {
      content.push({
        type: "toolCall",
        id: `${item.call_id || randomId("call")}|${item.id || randomId("fc")}`,
        name: item.name,
        arguments: parseJsonObject(item.arguments),
      });
    } else if (item.type === "reasoning") {
      const thinking = (item.summary ?? []).map((part) => part.text ?? "").filter(Boolean).join("\n\n");
      if (thinking) {
        content.push({ type: "thinking", thinking, thinkingSignature: JSON.stringify(item) });
      }
    }
  }
  output.content = content.length ? content : [fauxText("")];
  output.usage = usageFromResponsesPayload(payload, model);
  output.stopReason = output.content.some((block) => block.type === "toolCall") ? "toolUse" : "stop";
}

function emitContentEvents(stream, output) {
  output.content.forEach((block, index) => {
    if (block.type === "text") {
      stream.push({ type: "text_start", contentIndex: index, partial: output });
      if (block.text) {
        stream.push({ type: "text_delta", contentIndex: index, delta: block.text, partial: output });
      }
      stream.push({ type: "text_end", contentIndex: index, content: block.text, partial: output });
    } else if (block.type === "thinking") {
      stream.push({ type: "thinking_start", contentIndex: index, partial: output });
      if (block.thinking) {
        stream.push({ type: "thinking_delta", contentIndex: index, delta: block.thinking, partial: output });
      }
      stream.push({ type: "thinking_end", contentIndex: index, content: block.thinking, partial: output });
    } else if (block.type === "toolCall") {
      stream.push({ type: "toolcall_start", contentIndex: index, partial: output });
      stream.push({ type: "toolcall_end", contentIndex: index, toolCall: block, partial: output });
    }
  });
}

function assistantMessage({ api, provider, model }) {
  return {
    role: "assistant",
    content: [],
    api,
    provider,
    model,
    usage: createEmptyUsage(),
    stopReason: "stop",
    timestamp: Date.now(),
  };
}

function usageFromResponsesPayload(payload, model) {
  const usage = payload.usage ?? {};
  const cachedTokens = usage.input_tokens_details?.cached_tokens ?? 0;
  const inputTokens = Math.max(0, (usage.input_tokens ?? 0) - cachedTokens);
  const outputTokens = usage.output_tokens ?? 0;
  const totalTokens = usage.total_tokens ?? inputTokens + outputTokens + cachedTokens;
  return usageWithCost(
    {
      input: inputTokens,
      output: outputTokens,
      cacheRead: cachedTokens,
      cacheWrite: 0,
      totalTokens,
    },
    model,
  );
}

function usageWithCost(usage, model) {
  const cost = {
    input: ((model.cost.input ?? 0) / 1000000) * usage.input,
    output: ((model.cost.output ?? 0) / 1000000) * usage.output,
    cacheRead: ((model.cost.cacheRead ?? 0) / 1000000) * usage.cacheRead,
    cacheWrite: ((model.cost.cacheWrite ?? 0) / 1000000) * usage.cacheWrite,
    total: 0,
  };
  cost.total = cost.input + cost.output + cost.cacheRead + cost.cacheWrite;
  return { ...usage, cost };
}

function createEmptyUsage() {
  return {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
    totalTokens: 0,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
  };
}

function cacheHitRatio(usage) {
  const denominator = usage.input + usage.cacheRead;
  return denominator > 0 ? usage.cacheRead / denominator : 0;
}

function parseJsonObject(value) {
  if (!value) {
    return {};
  }
  try {
    const parsed = typeof value === "string" ? JSON.parse(value) : value;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function extractErrorMessage(payload) {
  return payload?.error?.message || payload?.message || JSON.stringify(payload).slice(0, 500);
}

function randomId(prefix) {
  return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
}

function normalizeProviderMode(value) {
  const normalized = String(value || "faux").trim().toLowerCase();
  if (["faux", "fake", "offline", "pi-worker"].includes(normalized)) {
    return "faux";
  }
  if (["live", "openai", "openai-responses", "responses"].includes(normalized)) {
    return "live";
  }
  throw new Error(`Unsupported PI_WORKER_PROVIDER: ${value}`);
}

function stripTrailingSlash(value) {
  return value.replace(/\/+$/, "");
}

function openAIEndpointUrl(baseUrl, endpoint) {
  const normalized = stripTrailingSlash(String(baseUrl));
  const versionedBase = normalized.endsWith("/v1") ? normalized : `${normalized}/v1`;
  return `${versionedBase}/${String(endpoint).replace(/^\/+/, "")}`;
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

function resolveWorkspacePath(root, ref, { mustExist = false } = {}) {
  const safeRef = normalizeRelativeRef(ref);
  const rootPath = realpathSync(root);
  const parts = safeRef.split("/");
  let current = rootPath;

  for (let index = 0; index < parts.length; index += 1) {
    current = resolve(current, parts[index]);
    try {
      const stats = lstatSync(current);
      if (stats.isSymbolicLink()) {
        throw new Error(`Symlink path is not allowed: ${current}`);
      }
      if (index < parts.length - 1 && !stats.isDirectory()) {
        throw new Error(`Parent path is not a directory: ${current}`);
      }
    } catch (error) {
      if (error instanceof Error && "code" in error && error.code === "ENOENT") {
        break;
      }
      throw error;
    }
  }

  const target = resolve(rootPath, safeRef);
  try {
    const stats = lstatSync(target);
    if (stats.isSymbolicLink()) {
      throw new Error(`Symlink path is not allowed: ${target}`);
    }
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      if (mustExist) {
        throw new Error(`Ref does not exist: ${safeRef}`);
      }
    } else {
      throw error;
    }
  }

  return target;
}

function safeWorkspaceExists(root, ref) {
  try {
    const path = resolveWorkspacePath(root, ref, { mustExist: true });
    return lstatSync(path).isFile();
  } catch {
    return false;
  }
}
