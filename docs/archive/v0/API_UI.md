# SkillFoundry API/UI Contract

Historical note: this document originally tracked the v0/WP API and
server-rendered HTML contract. It is archived and no longer defines the current
API surface. Use the root `README.md`, `HANDOFF.md`, and current tests as the
source of truth.

The canonical product route is:

```text
Front Desk job
  -> user plan review
  -> deterministic freeze
  -> /frontdesk/jobs/{job_id}/build
  -> graph v2 / ContextForge Goal Harness / Verifier / Registry
```

Legacy offline `POST /jobs` creation has since been retired from the current
API/UI product surface.

## Serve

```bash
skillfoundry serve --runs-root runs --host 127.0.0.1 --port 8765
```

The default registry path is `runs/registry.json`. Keep the service behind an
internal network boundary or local tunnel controlled by the operator.

Legacy offline `POST /jobs` creation is not available in the current API/UI.
For deterministic fixture migration or local smoke tests, use explicit CLI/dev
fixtures instead of the server route.

## Routes

- `GET /`: internal HTML page with the Front Desk job form, Front Desk job
  table, registry summary, build record table, report links, and package links
  only for downloadable registered packages.
- `POST /jobs`: retired legacy creation route. The current API returns
  `410 legacy_offline_jobs_retired`; the canonical product build path is the
  Front Desk approved/frozen graph v2 route below.
- `GET /jobs`: list known job workspaces below `runs_root`.
- `GET /jobs/<job_id>`: return job status and final report when present. With
  `Accept: text/html`, render a refs-only job evidence page showing build path,
  graph v2 status, verification, registry, repair, human-review, cache, worker,
  usage, and artifact ref summaries without inlining raw prompts, provider
  payloads, conversations, transcripts, replay bundles, or package content.
- `GET /jobs/<job_id>/report`: return `final_report.json`.
- `GET /jobs/<job_id>/contextforge`: return refs-only ContextForge, graph v2,
  repair, human-review, cache, worker, verification, and registry evidence
  summaries. It must not inline raw prompts, raw Front Desk conversation,
  worker transcripts, provider payloads, or package content.
- `GET /jobs/<job_id>/human-review`: return the governed human-review request
  and decision refs for one graph v2 job without inlining raw evidence.
- `POST /jobs/<job_id>/human-review`: record a human operator decision
  (`approve`, `reject`, `request_repair`, or `redesign`). When an approved
  manual acceptance body includes `covered_criterion_ids`, the API writes
  `qa/manual_acceptance_record.json` for later verifier / acceptance coverage /
  registry checks. This endpoint records authority; it does not bypass the
  verifier, acceptance coverage, ContextForge verification, or registry gate.
- `GET /registry`: return approved, non-quarantined registry entries by
  default.
- `GET /jobs/<job_id>/package.zip`: download a zip archive containing only
  `package/` files.

## Front Desk Routes

The Front Desk API is the default product-discovery route. It is not the old
offline builder form: it runs `FrontDeskLoop` through governed Core Need,
Solution Planner, Spec Auditor, user plan review, and `FrontDeskFreezeGate`
artifacts before an approved/frozen job can enter graph v2 build.

The Front Desk is product-discovery first. Early rounds should clarify the
user's pain, goal, workflow, audience, usage moment, desired outcome, success
signal, and complaint/failure scenario before asking for implementation details
such as local paths, file formats, API permissions, or exact output directories.
By default it asks one high-leverage question per round. When useful, the
question should offer a few candidate choices plus an option for the user to
describe their own idea. After the pain and workflow are clear, the Front Desk
should synthesize candidate Skill solutions and let the user choose or adjust
the direction before deterministic freeze.

Default Front Desk operation does not require `OPENAI_API_KEY`. When no live
Front Desk client factory is configured, the API uses the deterministic offline
Front Desk / Goal Harness path and remains suitable for local tests and no-key
internal demos.

Live provider use is opt-in. Configure it explicitly through the server/client
integration layer and provider environment, for example:

```bash
export OPENAI_API_KEY=...
export SKILLFOUNDRY_FRONTDESK_MODEL=gpt-5.5
skillfoundry serve --runs-root runs --host 127.0.0.1 --port 8765
```

Routes:

- `POST /frontdesk/jobs`: create a Front Desk clarification job and run one
  round. JSON fields are `message` or `requirement`, plus optional `job_id`.
- `POST /frontdesk/jobs/<job_id>/messages`: append a user answer/message and
  run the next clarification round.
- `GET /frontdesk/jobs/<job_id>`: return refs-only state, latest questions,
  latest elicitation report, latest audit report, and artifact refs.
- `POST /frontdesk/jobs/<job_id>/build`: canonical product build route. It only
  accepts approved/frozen Front Desk jobs and runs graph v2 through ContextForge
  Goal Harness, SkillFoundry verifier, acceptance coverage, ContextForge
  verification bridge, repair/human-review routing, and registry evidence gate.

Example:

```bash
curl -s -X POST http://127.0.0.1:8765/frontdesk/jobs \
  -H 'Content-Type: application/json' \
  -d '{"job_id":"frontdesk-demo","message":"构建一个帮助分析 pytest 失败日志的 Codex Skill。"}'
```

If no live provider is configured, these routes still run through the offline
deterministic Front Desk path. Default automated tests do not call live
providers.

## Safety Gates

`job_id` must be one safe path segment. The API rejects traversal segments,
absolute paths, and unknown artifact routes. Package downloads are allowed only
when the job final report has `final_status == "registered"` and the local
registry still has an approved, non-quarantined, hash-valid entry for that job.
Verifier-failed, rejected, human-review, reused, missing-package, quarantined,
or tampered jobs do not receive download links.
