# WP9 Minimal API/UI

WP9 exposes the existing offline SkillFoundry factory through a small internal
API and server-rendered HTML page. It is intentionally not a production
platform: there is no queue, marketplace, multi-tenant permission model, full
auth system, live Codex dependency, or frontend framework.

## Serve

```bash
skillfoundry serve --runs-root runs --host 127.0.0.1 --port 8765
```

The default registry path is `runs/registry.json`. Keep the service behind an
internal network boundary or local tunnel controlled by the operator.

## Routes

- `GET /`: internal HTML page with a job form, job table, registry summary,
  report links, and package links only for downloadable registered packages.
- `POST /jobs`: legacy compatibility route that creates one synchronous
  offline job from JSON or form data. It is retained for v0 fixtures and
  internal smoke tests; the canonical product build path is the Front Desk
  approved/frozen graph v2 route below.
  JSON fields are `requirement`, optional `job_id`, optional `worker_mode`, and
  optional `attempt_limit`.
- `GET /jobs`: list known job workspaces below `runs_root`.
- `GET /jobs/<job_id>`: return job status and final report when present.
- `GET /jobs/<job_id>/report`: return `final_report.json`.
- `GET /jobs/<job_id>/contextforge`: return refs-only ContextForge, graph v2,
  repair, human-review, cache, worker, verification, and registry evidence
  summaries. It must not inline raw prompts, raw Front Desk conversation,
  worker transcripts, provider payloads, or package content.
- `GET /registry`: return approved, non-quarantined registry entries by
  default.
- `GET /jobs/<job_id>/package.zip`: download a zip archive containing only
  `package/` files.

## Front Desk Trial Routes

WP13-WP17 also expose a thin trial API for the real Front Desk loop. This is
not the old offline builder form: it runs `FrontDeskLoop` through
`RequirementsElicitor`, `SpecAuditor`, and `FrontDeskFreezeGate`.

The Front Desk is product-discovery first. Early rounds should clarify the
user's pain, goal, workflow, audience, usage moment, desired outcome, success
signal, and complaint/failure scenario before asking for implementation details
such as local paths, file formats, API permissions, or exact output directories.
By default it asks one high-leverage question per round. When useful, the
question should offer a few candidate choices plus an option for the user to
describe their own idea. After the pain and workflow are clear, the Front Desk
should synthesize candidate Skill solutions and let the user choose or adjust
the direction before deterministic freeze.

Live provider use is opt-in. Start the server with:

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

If `OPENAI_API_KEY` is not set, the Front Desk trial routes return `503` with
`openai_api_key_missing`. Default automated tests inject scripted clients and
do not call live providers.

## Safety Gates

`job_id` must be one safe path segment. The API rejects traversal segments,
absolute paths, and unknown artifact routes. Package downloads are allowed only
when the job final report has `final_status == "registered"` and the local
registry still has an approved, non-quarantined, hash-valid entry for that job.
Verifier-failed, rejected, human-review, reused, missing-package, quarantined,
or tampered jobs do not receive download links.
