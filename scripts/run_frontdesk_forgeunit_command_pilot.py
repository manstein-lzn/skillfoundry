#!/usr/bin/env python3
"""Run a local FrontDesk API ForgeUnit command-boundary pilot.

The default command is a deterministic local subprocess worker. It does not
invoke live Codex. Operators can pass --command explicitly for a manual real
command pilot after the local smoke succeeds.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import shutil
import sys
from typing import Any, Mapping

from forgeunit_skillfoundry.testing import VALID_CODEX_SKILL
from skillfoundry.api import SkillFoundryAPI


DEFAULT_JOB_ID = "frontdesk-local-command-pilot-001"
DEFAULT_MESSAGE = "Build a governed Codex skill for analyzing pasted pytest failures."
DEFAULT_VERSION = "frontdesk-command-pilot"
SUMMARY_SCHEMA_VERSION = "skillfoundry.frontdesk_forgeunit_command_pilot.v1"


class PilotError(RuntimeError):
    """Raised when the local pilot cannot complete."""


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    runs_root = Path(args.runs_root)
    registry_path = Path(args.registry_path)
    job_root = runs_root / args.job_id

    if job_root.exists():
        if not args.overwrite:
            print(
                f"workspace already exists: {job_root}; rerun with --overwrite to replace this pilot workspace",
                file=sys.stderr,
            )
            return 2
        shutil.rmtree(job_root)

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    command = args.command
    if command is None:
        worker_script = _write_default_success_worker(Path(args.worker_dir))
        command = f"{shlex.quote(sys.executable)} {shlex.quote(worker_script.as_posix())}"
    repair_command = args.repair_command

    api = SkillFoundryAPI(
        runs_root,
        registry_path=registry_path,
        forgeunit_command=command,
        forgeunit_repair_command=repair_command,
    )

    try:
        created = _require_success(
            api.handle(
                "POST",
                "/frontdesk/jobs",
                body={"job_id": args.job_id, "message": args.message},
            ),
            "create FrontDesk job",
        )
        approved = _require_success(
            api.handle(
                "POST",
                f"/frontdesk/jobs/{args.job_id}/plan-review",
                body={"decision": "approve", "reason": "Local command pilot approval."},
            ),
            "approve FrontDesk plan",
        )
        build_body: dict[str, Any] = {"version": args.version}
        if args.created_at:
            build_body["created_at"] = args.created_at
        build = _require_success(
            api.handle("POST", f"/frontdesk/jobs/{args.job_id}/build", body=build_body),
            "build FrontDesk job",
        )
        contextforge = _require_success(
            api.handle("GET", f"/jobs/{args.job_id}/contextforge"),
            "read ContextForge status",
        )
        job = _require_success(api.handle("GET", f"/jobs/{args.job_id}"), "read job")
    except PilotError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    summary = _pilot_summary(
        job_id=args.job_id,
        created=created,
        approved=approved,
        build=build,
        contextforge=contextforge,
        job=job,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("status") == "registered" else 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", default="runs", help="SkillFoundry runs root.")
    parser.add_argument("--job-id", default=DEFAULT_JOB_ID, help="Safe pilot job id.")
    parser.add_argument("--registry-path", default=".local/frontdesk_forgeunit_command_pilot_registry.json")
    parser.add_argument("--worker-dir", default=".local/frontdesk_forgeunit_command_pilot")
    parser.add_argument("--message", default=DEFAULT_MESSAGE, help="FrontDesk user message for the pilot.")
    parser.add_argument("--version", default=DEFAULT_VERSION, help="Registry version for the pilot package.")
    parser.add_argument("--created-at", help="Optional deterministic timestamp for build artifacts.")
    parser.add_argument("--command", help="Explicit ForgeUnit/Codex command boundary. Defaults to local fake worker.")
    parser.add_argument("--repair-command", help="Optional explicit repair command boundary.")
    parser.add_argument("--overwrite", action="store_true", help="Delete an existing pilot workspace first.")
    return parser


def _write_default_success_worker(worker_dir: Path) -> Path:
    worker_dir.mkdir(parents=True, exist_ok=True)
    script = worker_dir / "frontdesk_local_success_worker.py"
    script.write_text(
        f"""
from pathlib import Path
import json
import os
import sys

_ = sys.stdin.read()
task_dir = Path(os.environ["FORGEUNIT_TASK_DIR"])
worker_result = Path(os.environ["FORGEUNIT_WORKER_RESULT"])
unit_id = os.environ["FORGEUNIT_UNIT"]

(task_dir / "package").mkdir(exist_ok=True)
(task_dir / "evidence").mkdir(exist_ok=True)
(task_dir / "package" / "SKILL.md").write_text({VALID_CODEX_SKILL!r}, encoding="utf-8")
(task_dir / "evidence" / "transcript.md").write_text(
    "local frontdesk command pilot transcript pointer\\n",
    encoding="utf-8",
)
(task_dir / "evidence" / "manifest.json").write_text(json.dumps({{
    "schema": "forgeunit.worker_evidence_manifest",
    "version": "0.6",
    "unit_id": unit_id,
    "status": "completed",
    "output_artifacts": [
        {{"path": "package/SKILL.md", "kind": "codex_skill", "summary": "local pilot skill package"}}
    ],
    "evidence_artifacts": [
        {{"path": "evidence/transcript.md", "kind": "transcript", "summary": "local pilot transcript"}}
    ],
    "changed_files": ["package/SKILL.md", "evidence/transcript.md", "evidence/manifest.json"],
    "commands": [{{"command": "local pilot worker", "exit_code": 0, "summary": "local pilot worker passed"}}],
    "usage": None,
    "usage_unavailable_reason": "external_worker_no_provider_telemetry"
}}, indent=2), encoding="utf-8")
worker_result.write_text(json.dumps({{
    "status": "completed",
    "output_artifacts": [
        {{"path": "package/SKILL.md", "kind": "codex_skill", "summary": "local pilot skill package"}}
    ],
    "boundary_evidence": [
        {{"path": "evidence/transcript.md", "kind": "transcript", "summary": "local pilot transcript"}},
        {{"path": "evidence/manifest.json", "kind": "worker_evidence_manifest", "summary": "manifest"}}
    ],
    "changed_files": ["package/SKILL.md", "evidence/transcript.md", "evidence/manifest.json"],
    "usage": None,
    "usage_unavailable_reason": "external_worker_no_provider_telemetry"
}}, indent=2), encoding="utf-8")
""".strip(),
        encoding="utf-8",
    )
    return script.resolve()


def _require_success(response: Any, label: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise PilotError(f"{label} failed: response was not JSON") from exc
    if response.status >= 400:
        raise PilotError(f"{label} failed: {json.dumps(payload, sort_keys=True)}")
    return payload


def _pilot_summary(
    *,
    job_id: str,
    created: Mapping[str, Any],
    approved: Mapping[str, Any],
    build: Mapping[str, Any],
    contextforge: Mapping[str, Any],
    job: Mapping[str, Any],
) -> dict[str, Any]:
    forgeunit_summary = _mapping(build.get("forgeunit_skillfoundry_summary"))
    verification = _mapping(forgeunit_summary.get("verification"))
    registry = _mapping(forgeunit_summary.get("registry"))
    trust = _mapping(forgeunit_summary.get("trust_boundaries"))
    refs = _mapping(forgeunit_summary.get("refs"))
    contextforge_status = _mapping(contextforge.get("status"))
    forgeunit_status = _mapping(contextforge_status.get("forgeunit_skillfoundry"))
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "job_id": job_id,
        "frontdesk": {
            "create_status": created.get("status"),
            "plan_review_status": approved.get("status"),
        },
        "status": build.get("status"),
        "build_path": {
            "mode": _mapping(build.get("build_path")).get("mode"),
            "canonical": _mapping(build.get("build_path")).get("canonical"),
        },
        "forgeunit_skillfoundry": {
            "mode": forgeunit_summary.get("mode"),
            "stage": forgeunit_summary.get("stage"),
            "status": forgeunit_summary.get("status"),
            "verification_status": verification.get("status"),
            "verification_passed": verification.get("passed"),
            "registry_approved": registry.get("approved"),
            "registry_skill_id": registry.get("skill_id"),
            "registry_version": registry.get("version"),
            "command_string_included": trust.get("command_string_included"),
            "raw_prompt_included": trust.get("raw_prompt_included"),
            "raw_transcript_included": trust.get("raw_transcript_included"),
            "raw_worker_input_included": trust.get("raw_worker_input_included"),
        },
        "contextforge_status": {
            "verification_status": forgeunit_status.get("verification_status"),
            "verification_passed": forgeunit_status.get("verification_passed"),
            "registry_approved": forgeunit_status.get("registry_approved"),
        },
        "refs": {
            key: refs.get(key)
            for key in (
                "forgeunit_skillfoundry_summary",
                "forgeunit_skillfoundry_product_state",
                "forgeunit_skillfoundry_graph_state",
                "skillfoundry_verification_result",
                "registry_decision",
                "registry_entry",
                "final_report",
            )
            if refs.get(key)
        },
        "package_downloadable": job.get("package_downloadable"),
        "links": {
            "job": _mapping(build.get("links")).get("job"),
            "contextforge": _mapping(build.get("links")).get("contextforge"),
            "package": _mapping(build.get("links")).get("package"),
        },
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


if __name__ == "__main__":
    raise SystemExit(main())
