# PiWorker MVP

## Goal

PiWorker is an owned worker-runtime backend for SkillFoundry. The MVP inserts a
Pi-based runtime behind the existing work-unit boundary so it can be compared
against the current CodexWorker path while keeping the rest of the system
unchanged.

The controlled variable is the worker runtime:

```text
same workspace / same contract / same verifier
  -> CodexWorker
  -> PiWorker
```

## Non-Goals

- Do not replace LangGraph, ContextForge, ForgeUnit, adaptive steering, or
  SkillFoundry verifiers.
- Do not make PiWorker the default backend before deterministic and live A/B
  evidence exists.
- Do not vendor the full Pi coding-agent/TUI stack in the MVP.
- Do not claim PiWorker removes the need for model providers.

## Architecture

```text
Python SkillFoundry
  -> PiWorker adapter
      writes pi_worker_input.json
      invokes Node sidecar
      reads pi_worker_output.json
  -> AdaptiveWorkUnitResult
  -> ObservationReport
  -> existing verifier / state correction
```

The Python adapter owns the stable SkillFoundry boundary. The Node sidecar owns
the Pi runtime implementation detail.

FrontDesk freeze now also writes a canonical
`frontdesk/task_contract.json`. `build_contract.yaml` points to it with
`task_contract_ref`, and adaptive work-unit contracts expose it as a visible ref
when present. Workers should treat `NextStepContract` as the current bounded
step and `frontdesk/task_contract.json` as the frozen product-intent contract.

## Runtime Slice

The current sidecar runs the real Pi `Agent` loop from the sibling `../pi`
source tree through a minimal local `@earendil-works/pi-ai` compatibility shim.
It deliberately uses the deterministic `faux` provider so the runtime loop,
event stream, tool execution, session output, and metrics can be tested offline.

PiWorker also has an explicit opt-in live provider mode for OpenAI-compatible
`/v1/responses` endpoints. The default remains `faux`; live mode is selected
with `PI_WORKER_PROVIDER=live` or `runtime.model_provider = "live"`.

Live mode is configured with runtime environment variables:

- `PI_WORKER_API_KEY` or `OPENAI_API_KEY` for the provider secret
- `PI_WORKER_BASE_URL`
- `PI_WORKER_MODEL`
- `PI_WORKER_REASONING_EFFORT`
- `PI_WORKER_THINKING_LEVEL`
- `PI_WORKER_REASONING_WITH_TOOLS`
- `PI_WORKER_PROMPT_CACHE_KEY`

`PI_WORKER_BASE_URL` may be either the provider root or an already-versioned
`/v1` base URL.

API keys are intentionally not accepted through `runtime.metadata`, because the
adapter writes runtime metadata into `pi_worker_input.json`.

Two provider-compatibility defaults are deliberate:

- The first tool-writing turn does not send `reasoning.effort`; some compatible
  gateways return usage but no tool-call output when reasoning is combined with
  custom tools. Set `PI_WORKER_REASONING_WITH_TOOLS=true` only for gateways that
  support both together.
- `prompt_cache_key` is opt-in through `PI_WORKER_PROMPT_CACHE_KEY` or
  `runtime.metadata.prompt_cache_key`; some gateways route cached requests
  through a non-tool output path. Cache telemetry is still recorded whenever the
  provider reports cached tokens in `usage`.

The MVP tool surface is scoped to the work-unit contract:

- `list_workspace_refs`: exposes `visible_refs`, `allowed_scope`, and
  `expected_outputs`.
- `read_workspace_ref`: reads only refs listed in `visible_refs`.
- `write_workspace_artifact`: writes only refs under `allowed_scope`.

An empty `allowed_scope` fails closed: no workspace writes are allowed unless the
contract delegates an explicit scope.

This is not the full Pi coding-agent tool stack. It is the smallest owned tool
surface needed to compare a Pi-backed worker with the existing worker backends.

## Input Artifact

The adapter writes:

```text
adaptive/attempts/<iteration>/pi_worker_input.json
```

Required top-level fields:

- `schema_version`: `skillfoundry.pi_worker_input.v1`
- `job_id`
- `iteration`
- `workspace_root`
- `attempt_dir_ref`
- `output_ref`
- `session_ref`
- `events_ref`
- `metrics_ref`
- `contract`: normalized next-step contract fields
- `runtime`: command/model/runtime configuration metadata

For FrontDesk-originated jobs, `contract.visible_refs` includes
`frontdesk/task_contract.json`, and `contract.metadata.frontdesk_task_contract_ref`
points to the same artifact.

## Output Artifact

The sidecar writes:

```text
adaptive/attempts/<iteration>/pi_worker_output.json
```

Required top-level fields:

- `schema_version`: `skillfoundry.pi_worker_output.v1`
- `job_id`
- `iteration`
- `status`: `completed`, `failed`, `blocked`, or `cancelled`
- `produced_artifacts`
- `changed_refs`
- `commands_run`
- `tests_run`
- `failures`
- `worker_claims`
- `verifier_evidence`
- `new_unknowns`
- `recommended_next_steps`
- `verification_status`: `passed`, `failed`, `not_run`, or `review_required`
- `session_ref`
- `events_ref`
- `metrics_ref`
- `metrics`

The sidecar may write additional Pi-native files, but the Python adapter only
trusts the normalized output artifact.

## MVP Acceptance

- PiWorker can be called as a ForgeUnit adaptive worker without changing the
  adaptive graph.
- PiWorker validation runs through the route-plan steering loop: the
  `NextStepContract` passed to PiWorker includes `route_plan_ref`, the matching
  route plan is present in `visible_refs`, and closure is decided through
  observation and state correction rather than worker claims.
- A deterministic Pi Agent sidecar using `faux` provider can produce
  `package/SKILL.md`.
- Frozen FrontDesk jobs include `frontdesk/task_contract.json`, and the
  PiWorker next-step input can observe that contract without reading raw
  conversation.
- The adapter maps sidecar output into `AdaptiveWorkUnitResult`.
- The adapter records `pi_worker_input.json`, `pi_worker_output.json`,
  `pi_session.jsonl`, `pi_events.jsonl`, and `pi_metrics.json` refs.
- The sidecar streams Pi Agent lifecycle/tool events to `pi_events.jsonl` while
  the work unit is still running, then writes normalized session and model/tool
  metrics at completion.
- Opt-in live provider mode can call an OpenAI-compatible `/v1/responses`
  endpoint, execute a model-emitted `write_workspace_artifact` call, and record
  provider-reported token and cached-token telemetry.
- The sidecar stays task-generic: product specificity must come from visible
  FrontDesk/SkillFoundry contracts, not hard-coded scenario branches.
- Nonzero sidecar exit or missing output is reported as worker failure, not as
  verifier acceptance.

## Steering Test Contract

The current PiWorker smoke path intentionally uses SkillFoundry's latest
Kalman-style adaptive steering substrate:

```text
CapabilityStateEstimate
  -> RoutePlan
  -> NextStepContract
  -> PiWorker
  -> ObservationReport
  -> StateCorrection
  -> revised RoutePlan / closure
```

The PiWorker sidecar is therefore tested as a worker inside the control loop,
not as a standalone artifact writer. The test asserts that `pi_worker_input.json`
contains the active `route_plan_ref`, that Pi runtime events and metrics are
recorded for each work unit, and that the final route reaches `closure` only
after independent bundle verification evidence is observed.

## Later Work

- Add A/B benchmark reports for PiWorker versus CodexWorker.
- Add broader live provider compatibility coverage, including provider-specific
  cache-key behavior and reasoning/tool-call combinations.
- Replace the local `pi-ai` compatibility shim with built package dependencies
  once the Pi source packaging path is stable in this environment.
