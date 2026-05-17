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
- `POST /jobs`: create one synchronous offline job from JSON or form data.
  JSON fields are `requirement`, optional `job_id`, optional `worker_mode`, and
  optional `attempt_limit`.
- `GET /jobs`: list known job workspaces below `runs_root`.
- `GET /jobs/<job_id>`: return job status and final report when present.
- `GET /jobs/<job_id>/report`: return `final_report.json`.
- `GET /registry`: return approved, non-quarantined registry entries by
  default.
- `GET /jobs/<job_id>/package.zip`: download a zip archive containing only
  `package/` files.

## Safety Gates

`job_id` must be one safe path segment. The API rejects traversal segments,
absolute paths, and unknown artifact routes. Package downloads are allowed only
when the job final report has `final_status == "registered"` and the local
registry still has an approved, non-quarantined, hash-valid entry for that job.
Verifier-failed, rejected, human-review, reused, missing-package, quarantined,
or tampered jobs do not receive download links.
