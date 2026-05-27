function createUsage(partial = {}) {
  return {
    input: partial.input ?? 0,
    output: partial.output ?? 0,
    cacheRead: partial.cacheRead ?? 0,
    cacheWrite: partial.cacheWrite ?? 0,
    totalTokens: partial.totalTokens ?? 0,
    cost: {
      input: partial.cost?.input ?? 0,
      output: partial.cost?.output ?? 0,
      cacheRead: partial.cost?.cacheRead ?? 0,
      cacheWrite: partial.cost?.cacheWrite ?? 0,
      total: partial.cost?.total ?? 0,
    },
  };
}

function randomId(prefix) {
  return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
}

function isObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function clone(value) {
  return typeof structuredClone === "function" ? structuredClone(value) : JSON.parse(JSON.stringify(value));
}

function normalizeAssistantContent(content) {
  if (typeof content === "string") {
    return [fauxText(content)];
  }
  return Array.isArray(content) ? content.map((block) => clone(block)) : [clone(content)];
}

function messageToText(message) {
  if (message.role === "user") {
    if (typeof message.content === "string") {
      return message.content;
    }
    return message.content
      .filter((block) => block.type === "text")
      .map((block) => block.text)
      .join("\n");
  }
  if (message.role === "assistant") {
    return assistantContentToText(message.content);
  }
  if (message.role === "toolResult") {
    return message.content
      .filter((block) => block.type === "text")
      .map((block) => block.text)
      .join("\n");
  }
  return "";
}

function assistantContentToText(content) {
  return content
    .map((block) => {
      if (block.type === "text") {
        return block.text;
      }
      if (block.type === "thinking") {
        return block.thinking;
      }
      return `${block.name}:${JSON.stringify(block.arguments)}`;
    })
    .join("\n");
}

function estimateTokens(text) {
  return Math.ceil(text.length / 4);
}

function commonPrefixLength(a, b) {
  const length = Math.min(a.length, b.length);
  let index = 0;
  while (index < length && a[index] === b[index]) {
    index++;
  }
  return index;
}

function serializeContext(context) {
  const parts = [];
  if (context.systemPrompt) {
    parts.push(`system:${context.systemPrompt}`);
  }
  for (const message of context.messages) {
    parts.push(`${message.role}:${messageToText(message)}`);
  }
  if (context.tools?.length) {
    parts.push(`tools:${JSON.stringify(context.tools)}`);
  }
  return parts.join("\n\n");
}

function withUsageEstimate(message, context, options, promptCache) {
  const promptText = serializeContext(context);
  const promptTokens = estimateTokens(promptText);
  const outputTokens = estimateTokens(assistantContentToText(message.content));
  let cacheRead = 0;
  let cacheWrite = 0;

  if (options?.sessionId && options?.cacheRetention !== "none") {
    const previousPrompt = promptCache.get(options.sessionId);
    if (previousPrompt) {
      const cachedChars = commonPrefixLength(previousPrompt, promptText);
      cacheRead = estimateTokens(previousPrompt.slice(0, cachedChars));
      cacheWrite = estimateTokens(promptText.slice(cachedChars));
    }
    promptCache.set(options.sessionId, promptText);
  }

  return {
    ...message,
    usage: createUsage({
      input: promptTokens,
      output: outputTokens,
      cacheRead,
      cacheWrite,
      totalTokens: promptTokens + outputTokens,
    }),
  };
}

function toAssistantMessage(content, options = {}) {
  return {
    role: "assistant",
    content: normalizeAssistantContent(content),
    api: options.api ?? "faux",
    provider: options.provider ?? "faux",
    model: options.model ?? "faux-1",
    usage: createUsage(),
    stopReason: options.stopReason ?? "stop",
    errorMessage: options.errorMessage,
    responseId: options.responseId,
    responseModel: options.responseModel,
    timestamp: options.timestamp ?? Date.now(),
  };
}

function createErrorMessage(error, api, provider, model) {
  return {
    role: "assistant",
    content: [fauxText("")],
    api,
    provider,
    model,
    usage: createUsage(),
    stopReason: "error",
    errorMessage: error instanceof Error ? error.message : String(error),
    timestamp: Date.now(),
  };
}

function cloneAssistantMessage(message, api, provider, model) {
  const cloned = clone(message);
  cloned.api = api;
  cloned.provider = provider;
  cloned.model = model;
  if (!cloned.usage) {
    cloned.usage = createUsage();
  } else if (!cloned.usage.cost) {
    cloned.usage = createUsage(cloned.usage);
  }
  return cloned;
}

function cloneModelDefinition(definition, api, provider) {
  return {
    id: definition.id,
    name: definition.name ?? definition.id,
    api,
    provider,
    baseUrl: definition.baseUrl ?? "http://localhost:0",
    reasoning: definition.reasoning ?? false,
    input: definition.input ?? ["text", "image"],
    cost: definition.cost ?? {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
    },
    contextWindow: definition.contextWindow ?? 128000,
    maxTokens: definition.maxTokens ?? 16384,
  };
}

function matchesType(value, type) {
  switch (type) {
    case "string":
      return typeof value === "string";
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    case "boolean":
      return typeof value === "boolean";
    case "null":
      return value === null;
    case "array":
      return Array.isArray(value);
    case "object":
      return isObject(value);
    default:
      return true;
  }
}

function coercePrimitive(value, type) {
  switch (type) {
    case "string":
      if (value === null || value === undefined) return "";
      if (typeof value === "string") return value;
      return String(value);
    case "number":
      if (typeof value === "number" && Number.isFinite(value)) return value;
      if (typeof value === "string" && value.trim() !== "") {
        const parsed = Number(value);
        if (Number.isFinite(parsed)) return parsed;
      }
      if (typeof value === "boolean") return value ? 1 : 0;
      return value;
    case "integer":
      if (typeof value === "number" && Number.isInteger(value)) return value;
      if (typeof value === "string" && value.trim() !== "") {
        const parsed = Number(value);
        if (Number.isInteger(parsed)) return parsed;
      }
      if (typeof value === "boolean") return value ? 1 : 0;
      return value;
    case "boolean":
      if (typeof value === "boolean") return value;
      if (typeof value === "string") {
        if (value === "true") return true;
        if (value === "false") return false;
      }
      if (typeof value === "number") {
        if (value === 1) return true;
        if (value === 0) return false;
      }
      return value;
    case "null":
      if (value === "" || value === 0 || value === false || value === undefined) return null;
      return value;
    default:
      return value;
  }
}

function coerceWithSchema(value, schema) {
  if (!schema || typeof schema !== "object") {
    return value;
  }

  if (Array.isArray(schema.type)) {
    for (const type of schema.type) {
      const candidate = coerceWithSchema(value, { ...schema, type });
      if (matchesType(candidate, type)) {
        return candidate;
      }
    }
    return value;
  }

  let nextValue = value;

  if (Array.isArray(schema.allOf)) {
    for (const nested of schema.allOf) {
      nextValue = coerceWithSchema(nextValue, nested);
    }
  }

  if (schema.anyOf) {
    for (const nested of schema.anyOf) {
      const candidate = coerceWithSchema(clone(nextValue), nested);
      if (validateValue(candidate, nested).ok) {
        nextValue = candidate;
        break;
      }
    }
  }

  if (schema.oneOf) {
    for (const nested of schema.oneOf) {
      const candidate = coerceWithSchema(clone(nextValue), nested);
      if (validateValue(candidate, nested).ok) {
        nextValue = candidate;
        break;
      }
    }
  }

  if (typeof schema.type === "string") {
    nextValue = coercePrimitive(nextValue, schema.type);
  }

  if (schema.type === "object" || schema.properties || schema.required || schema.additionalProperties !== undefined) {
    if (!isObject(nextValue)) {
      return nextValue;
    }
    const objectValue = { ...nextValue };
    if (schema.properties) {
      for (const [key, nested] of Object.entries(schema.properties)) {
        if (key in objectValue) {
          objectValue[key] = coerceWithSchema(objectValue[key], nested);
        }
      }
    }
    if (schema.additionalProperties && isObject(schema.additionalProperties)) {
      for (const [key, nestedValue] of Object.entries(objectValue)) {
        if (schema.properties && Object.hasOwn(schema.properties, key)) {
          continue;
        }
        objectValue[key] = coerceWithSchema(nestedValue, schema.additionalProperties);
      }
    }
    return objectValue;
  }

  if (schema.type === "array" || schema.items) {
    if (!Array.isArray(nextValue)) {
      return nextValue;
    }
    if (schema.items && !Array.isArray(schema.items)) {
      return nextValue.map((item) => coerceWithSchema(item, schema.items));
    }
    return nextValue;
  }

  return nextValue;
}

function validateValue(value, schema, path = "root") {
  const errors = [];

  function visit(candidate, candidateSchema, candidatePath) {
    if (!candidateSchema || typeof candidateSchema !== "object") {
      return;
    }

    if (Array.isArray(candidateSchema.type)) {
      if (!candidateSchema.type.some((type) => matchesType(candidate, type))) {
        errors.push(`${candidatePath}: expected one of ${candidateSchema.type.join(", ")}`);
        return;
      }
    } else if (typeof candidateSchema.type === "string" && !matchesType(candidate, candidateSchema.type)) {
      errors.push(`${candidatePath}: expected ${candidateSchema.type}`);
      return;
    }

    if ((candidateSchema.type === "object" || candidateSchema.properties) && isObject(candidate)) {
      const required = Array.isArray(candidateSchema.required) ? candidateSchema.required : [];
      for (const key of required) {
        if (!Object.hasOwn(candidate, key)) {
          errors.push(`${candidatePath}.${key}: is required`);
        }
      }
      if (candidateSchema.properties) {
        for (const [key, nested] of Object.entries(candidateSchema.properties)) {
          if (Object.hasOwn(candidate, key)) {
            visit(candidate[key], nested, `${candidatePath}.${key}`);
          }
        }
        if (candidateSchema.additionalProperties === false) {
          for (const key of Object.keys(candidate)) {
            if (!Object.hasOwn(candidateSchema.properties, key)) {
              errors.push(`${candidatePath}.${key}: additional property is not allowed`);
            }
          }
        } else if (isObject(candidateSchema.additionalProperties)) {
          for (const [key, nestedValue] of Object.entries(candidate)) {
            if (!Object.hasOwn(candidateSchema.properties ?? {}, key)) {
              visit(nestedValue, candidateSchema.additionalProperties, `${candidatePath}.${key}`);
            }
          }
        }
      }
    }

    if (candidateSchema.type === "array" && Array.isArray(candidate)) {
      if (Array.isArray(candidateSchema.items)) {
        for (let index = 0; index < candidate.length; index++) {
          const nested = candidateSchema.items[index];
          if (nested) {
            visit(candidate[index], nested, `${candidatePath}[${index}]`);
          }
        }
      } else if (candidateSchema.items) {
        for (let index = 0; index < candidate.length; index++) {
          visit(candidate[index], candidateSchema.items, `${candidatePath}[${index}]`);
        }
      }
    }
  }

  visit(value, schema, path);

  return errors.length === 0
    ? { ok: true, value }
    : {
        ok: false,
        error: new Error(errors.join("\n")),
      };
}

export class EventStream {
  constructor(isComplete, extractResult) {
    this.queue = [];
    this.waiting = [];
    this.done = false;
    this.finalResultPromise = new Promise((resolve) => {
      this.resolveFinalResult = resolve;
    });
    this.isComplete = isComplete;
    this.extractResult = extractResult;
  }

  push(event) {
    if (this.done) {
      return;
    }

    if (this.isComplete(event)) {
      this.done = true;
      this.resolveFinalResult(this.extractResult(event));
    }

    const waiter = this.waiting.shift();
    if (waiter) {
      waiter({ value: event, done: false });
    } else {
      this.queue.push(event);
    }
  }

  end(result) {
    this.done = true;
    if (result !== undefined) {
      this.resolveFinalResult(result);
    }
    while (this.waiting.length > 0) {
      const waiter = this.waiting.shift();
      waiter({ value: undefined, done: true });
    }
  }

  async *[Symbol.asyncIterator]() {
    while (true) {
      if (this.queue.length > 0) {
        yield this.queue.shift();
      } else if (this.done) {
        return;
      } else {
        const result = await new Promise((resolve) => this.waiting.push(resolve));
        if (result.done) {
          return;
        }
        yield result.value;
      }
    }
  }

  result() {
    return this.finalResultPromise;
  }
}

export class AssistantMessageEventStream extends EventStream {
  constructor() {
    super(
      (event) => event.type === "done" || event.type === "error",
      (event) => (event.type === "done" ? event.message : event.error),
    );
  }
}

export function createAssistantMessageEventStream() {
  return new AssistantMessageEventStream();
}

const apiProviders = new Map();

function wrapProviderStream(api, stream) {
  return (model, context, options) => {
    if (model.api !== api) {
      throw new Error(`Mismatched api: ${model.api} expected ${api}`);
    }
    return stream(model, context, options);
  };
}

export function registerApiProvider(provider, sourceId) {
  apiProviders.set(provider.api, {
    provider: {
      api: provider.api,
      stream: wrapProviderStream(provider.api, provider.stream),
      streamSimple: wrapProviderStream(provider.api, provider.streamSimple),
    },
    sourceId,
  });
}

export function getApiProvider(api) {
  return apiProviders.get(api)?.provider;
}

export function unregisterApiProviders(sourceId) {
  for (const [api, entry] of apiProviders.entries()) {
    if (entry.sourceId === sourceId) {
      apiProviders.delete(api);
    }
  }
}

export function stream(model, context, options) {
  const provider = getApiProvider(model.api);
  if (!provider) {
    throw new Error(`No API provider registered for api: ${model.api}`);
  }
  return provider.stream(model, context, options);
}

export async function complete(model, context, options) {
  return stream(model, context, options).result();
}

export function streamSimple(model, context, options) {
  const provider = getApiProvider(model.api);
  if (!provider) {
    throw new Error(`No API provider registered for api: ${model.api}`);
  }
  return provider.streamSimple(model, context, options);
}

export async function completeSimple(model, context, options) {
  return streamSimple(model, context, options).result();
}

export function fauxText(text) {
  return { type: "text", text };
}

export function fauxThinking(thinking) {
  return { type: "thinking", thinking };
}

export function fauxToolCall(name, arguments_, options = {}) {
  return {
    type: "toolCall",
    id: options.id ?? randomId("tool"),
    name,
    arguments: arguments_,
  };
}

export function fauxAssistantMessage(content, options = {}) {
  return toAssistantMessage(content, {
    stopReason: options.stopReason,
    errorMessage: options.errorMessage,
    responseId: options.responseId,
    timestamp: options.timestamp,
  });
}

function normalizeModelDefinitions(models) {
  if (models?.length) {
    return models;
  }
  return [
    {
      id: "faux-1",
      name: "Faux Model",
      reasoning: false,
      input: ["text", "image"],
      cost: {
        input: 0,
        output: 0,
        cacheRead: 0,
        cacheWrite: 0,
      },
      contextWindow: 128000,
      maxTokens: 16384,
    },
  ];
}

export function validateToolArguments(tool, toolCall) {
  const args = clone(toolCall.arguments);
  const schema = tool.parameters ?? {};
  const coerced = coerceWithSchema(args, schema);
  const validation = validateValue(coerced, schema);
  if (!validation.ok) {
    const error = validation.error;
    throw new Error(
      `Validation failed for tool "${toolCall.name}":\n${error.message}\n\nReceived arguments:\n${JSON.stringify(toolCall.arguments, null, 2)}`,
    );
  }
  return coerced;
}

export function validateToolCall(tools, toolCall) {
  const tool = tools.find((candidate) => candidate.name === toolCall.name);
  if (!tool) {
    throw new Error(`Tool "${toolCall.name}" not found`);
  }
  return validateToolArguments(tool, toolCall);
}

export function registerFauxProvider(options = {}) {
  const api = options.api ?? randomId("faux");
  const provider = options.provider ?? "faux";
  const sourceId = randomId("faux-provider");
  const promptCache = new Map();
  const state = { callCount: 0 };
  let pendingResponses = [];
  const modelDefinitions = normalizeModelDefinitions(options.models);
  const models = modelDefinitions.map((definition) => cloneModelDefinition(definition, api, provider));

  const streamFn = (requestModel, context, streamOptions) => {
    const outer = createAssistantMessageEventStream();
    const step = pendingResponses.shift();
    state.callCount += 1;

    queueMicrotask(async () => {
      try {
        if (streamOptions?.signal?.aborted) {
          const aborted = createErrorMessage(new Error("Aborted"), api, provider, requestModel.id);
          aborted.stopReason = "aborted";
          outer.push({ type: "error", reason: "aborted", error: aborted });
          outer.end(aborted);
          return;
        }

        if (!step) {
          let message = createErrorMessage(new Error("No more faux responses queued"), api, provider, requestModel.id);
          message = withUsageEstimate(message, context, streamOptions, promptCache);
          outer.push({ type: "error", reason: "error", error: message });
          outer.end(message);
          return;
        }

        const resolved = typeof step === "function" ? await step(context, streamOptions, state, requestModel) : step;
        let message = cloneAssistantMessage(resolved, api, provider, requestModel.id);
        message = withUsageEstimate(message, context, streamOptions, promptCache);
        outer.push({
          type: "start",
          partial: clone(message),
        });
        if (message.stopReason === "error" || message.stopReason === "aborted") {
          outer.push({ type: "error", reason: message.stopReason, error: message });
          outer.end(message);
          return;
        }
        outer.push({ type: "done", reason: message.stopReason, message });
        outer.end(message);
      } catch (error) {
        const message = createErrorMessage(error, api, provider, requestModel.id);
        outer.push({ type: "error", reason: "error", error: message });
        outer.end(message);
      }
    });

    return outer;
  };

  registerApiProvider({ api, stream: streamFn, streamSimple: streamFn }, sourceId);

  function getModel(requestedModelId) {
    if (requestedModelId === undefined) {
      return models[0];
    }
    return models.find((candidate) => candidate.id === requestedModelId);
  }

  return {
    api,
    models,
    getModel,
    state,
    setResponses(responses) {
      pendingResponses = [...responses];
    },
    appendResponses(responses) {
      pendingResponses.push(...responses);
    },
    getPendingResponseCount() {
      return pendingResponses.length;
    },
    unregister() {
      unregisterApiProviders(sourceId);
    },
  };
}
