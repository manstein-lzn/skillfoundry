#!/usr/bin/env python3
"""Run a manual FrontDesk ForgeUnit command-boundary scenario eval.

This is operator tooling for repeatability checks. It never invokes live Codex
by default: pass --command for a real command boundary, or --fake-mode happy for
an offline deterministic smoke.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import sys
import time
from typing import Any, Mapping

from forgeunit_skillfoundry.testing import write_fake_codex_exec_command
from skillfoundry.api import SkillFoundryAPI


SUMMARY_SCHEMA_VERSION = "skillfoundry.frontdesk_live_codex_eval.v1"
DEFAULT_EVAL_ID = "frontdesk-live-codex-eval"
DEFAULT_VERSION_PREFIX = "frontdesk-live-codex-eval"
SCENARIO_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")


@dataclass(frozen=True)
class Scenario:
    """One eval scenario that can be routed through FrontDesk."""

    scenario_id: str
    message: str
    version: str | None = None
    semantic_markers: tuple[str, ...] = ()


DEFAULT_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "pytest-failure-analyzer",
        "Build a governed Codex skill for analyzing pasted pytest failures and returning root cause, "
        "minimal fix, and verification steps.",
        semantic_markers=("pytest", "failure"),
    ),
    Scenario(
        "repository-handoff",
        "Build a governed Codex skill for creating concise repository onboarding and handoff briefs "
        "from checked-in project artifacts.",
        semantic_markers=("repository", "handoff"),
    ),
    Scenario(
        "api-docs-summarizer",
        "Build a governed Codex skill for summarizing API documentation into usage constraints, "
        "common workflows, and integration caveats.",
        semantic_markers=("api", "docs"),
    ),
    Scenario(
        "incident-triage",
        "Build a governed Codex skill for triaging incident notes into impact, timeline, likely cause, "
        "next actions, and verification evidence.",
        semantic_markers=("incident", "triage"),
    ),
    Scenario(
        "code-review-checklist",
        "Build a governed Codex skill for reviewing code changes with emphasis on regressions, "
        "security risks, missing tests, and operational follow-up.",
        semantic_markers=("code", "review"),
    ),
)


class EvalError(RuntimeError):
    """Raised when the eval harness cannot proceed."""


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_eval(args)
    except EvalError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    totals = _mapping(summary.get("totals"))
    if totals.get("redaction_failures") != 0:
        return 3
    if totals.get("semantic_fidelity_failed") not in (None, 0):
        return 1
    return 0 if totals.get("registered") == totals.get("total") else 1


def run_eval(args: argparse.Namespace) -> dict[str, Any]:
    scenarios = _load_scenarios(args)
    runs_root = Path(args.runs_root)
    eval_id = _safe_eval_id(args.eval_id)
    eval_root = runs_root / eval_id
    if eval_root.exists():
        if not args.overwrite:
            raise EvalError(f"eval workspace already exists: {eval_root}; rerun with --overwrite to replace it")
        shutil.rmtree(eval_root)
    eval_root.mkdir(parents=True, exist_ok=True)

    command = _resolve_command(args=args, eval_root=eval_root)
    registry_path = Path(args.registry_path)
    api = SkillFoundryAPI(
        eval_root,
        registry_path=registry_path,
        forgeunit_command=command,
    )

    created_at = _optional_non_empty(args.created_at)
    started = time.monotonic()
    scenario_summaries: list[dict[str, Any]] = []
    for scenario in scenarios:
        scenario_summaries.append(
            _run_scenario(
                api=api,
                eval_root=eval_root,
                eval_id=eval_id,
                scenario=scenario,
                version_prefix=args.version_prefix,
                created_at=created_at,
                assess_package=bool(args.command),
            )
        )
    duration_seconds = round(time.monotonic() - started, 3)

    summary = _build_eval_summary(
        eval_id=eval_id,
        eval_root=eval_root,
        mode="fake" if args.fake_mode else "command",
        live_codex_requested=bool(args.command),
        scenario_summaries=scenario_summaries,
        duration_seconds=duration_seconds,
        created_at=created_at or _utc_now(),
    )
    redaction_findings = _redaction_findings(
        summary,
        scenario_messages=[scenario.message for scenario in scenarios],
        command=args.command or "",
        fake_mode=bool(args.fake_mode),
    )
    summary["redaction_findings"] = redaction_findings
    totals = dict(summary["totals"])
    totals["redaction_failures"] = len(redaction_findings)
    summary["totals"] = totals

    (eval_root / "eval_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", default=".local/frontdesk_live_codex_eval_runs")
    parser.add_argument("--eval-id", default=DEFAULT_EVAL_ID, help="Safe eval workspace id under runs-root.")
    parser.add_argument("--registry-path", default=".local_registry/frontdesk_live_codex_eval_registry.json")
    parser.add_argument("--scenario-file", help="JSON file containing a list or {'scenarios': [...]} records.")
    parser.add_argument("--limit", type=int, help="Run only the first N loaded scenarios.")
    parser.add_argument("--version-prefix", default=DEFAULT_VERSION_PREFIX)
    parser.add_argument("--created-at", help="Optional deterministic timestamp for build artifacts.")
    parser.add_argument("--command", help="Explicit ForgeUnit/Codex command boundary for live/manual eval.")
    parser.add_argument("--fake-mode", choices=("happy",), help="Run deterministic offline eval instead of live Codex.")
    parser.add_argument("--overwrite", action="store_true", help="Delete an existing eval workspace first.")
    return parser


def _resolve_command(*, args: argparse.Namespace, eval_root: Path) -> str:
    if args.command and args.fake_mode:
        raise EvalError("--command and --fake-mode are mutually exclusive")
    if args.command:
        command = str(args.command).strip()
        if not command:
            raise EvalError("--command must not be empty")
        return command
    if args.fake_mode == "happy":
        worker_dir = eval_root / ".workers"
        worker_dir.mkdir(parents=True, exist_ok=True)
        script = write_fake_codex_exec_command(
            worker_dir,
            script_name="frontdesk_eval_fake_codex_exec.py",
        ).resolve()
        return f"{shlex.quote(sys.executable)} {shlex.quote(script.as_posix())}"
    raise EvalError("explicit mode required: pass --command for live Codex or --fake-mode happy for offline smoke")


def _load_scenarios(args: argparse.Namespace) -> list[Scenario]:
    if args.scenario_file:
        payload = json.loads(Path(args.scenario_file).read_text(encoding="utf-8"))
        raw_scenarios = payload.get("scenarios") if isinstance(payload, Mapping) else payload
        if not isinstance(raw_scenarios, list):
            raise EvalError("scenario file must be a JSON list or an object with a scenarios list")
        scenarios = [_parse_scenario(item, index=index) for index, item in enumerate(raw_scenarios, start=1)]
    else:
        scenarios = list(DEFAULT_SCENARIOS)
    if args.limit is not None:
        if args.limit <= 0:
            raise EvalError("--limit must be positive")
        scenarios = scenarios[: args.limit]
    if not scenarios:
        raise EvalError("at least one scenario is required")
    seen: set[str] = set()
    for scenario in scenarios:
        if scenario.scenario_id in seen:
            raise EvalError(f"duplicate scenario id: {scenario.scenario_id}")
        seen.add(scenario.scenario_id)
    return scenarios


def _parse_scenario(item: Any, *, index: int) -> Scenario:
    if not isinstance(item, Mapping):
        raise EvalError(f"scenario #{index} must be an object")
    scenario_id = _optional_non_empty(item.get("id") or item.get("scenario_id"))
    message = _optional_non_empty(item.get("message"))
    version = _optional_non_empty(item.get("version"))
    markers = _semantic_markers_from_payload(item.get("semantic_markers"), scenario_id or "")
    if scenario_id is None:
        raise EvalError(f"scenario #{index} is missing id")
    if not SCENARIO_ID_RE.fullmatch(scenario_id):
        raise EvalError(f"scenario id must be lowercase kebab-case: {scenario_id}")
    if message is None:
        raise EvalError(f"scenario {scenario_id} is missing message")
    return Scenario(scenario_id=scenario_id, message=message, version=version, semantic_markers=markers)


def _run_scenario(
    *,
    api: SkillFoundryAPI,
    eval_root: Path,
    eval_id: str,
    scenario: Scenario,
    version_prefix: str,
    created_at: str | None,
    assess_package: bool,
) -> dict[str, Any]:
    job_id = f"{eval_id}-{scenario.scenario_id}"
    version = scenario.version or f"{version_prefix}-{scenario.scenario_id}"
    started = time.monotonic()
    try:
        created = _require_success(
            api.handle("POST", "/frontdesk/jobs", body={"job_id": job_id, "message": scenario.message}),
            f"create FrontDesk job for {scenario.scenario_id}",
        )
        approved = _require_success(
            api.handle(
                "POST",
                f"/frontdesk/jobs/{job_id}/plan-review",
                body={"decision": "approve", "reason": "Manual scenario eval approval."},
            ),
            f"approve FrontDesk plan for {scenario.scenario_id}",
        )
        build_body: dict[str, Any] = {"version": version}
        if created_at:
            build_body["created_at"] = created_at
        build = _require_success(
            api.handle("POST", f"/frontdesk/jobs/{job_id}/build", body=build_body),
            f"build FrontDesk job for {scenario.scenario_id}",
        )
        contextforge = _require_success(
            api.handle("GET", f"/jobs/{job_id}/contextforge"),
            f"read ContextForge status for {scenario.scenario_id}",
        )
        job = _require_success(api.handle("GET", f"/jobs/{job_id}"), f"read job for {scenario.scenario_id}")
        payload = _scenario_success_summary(
            scenario_id=scenario.scenario_id,
            job_id=job_id,
            version=version,
            created=created,
            approved=approved,
            build=build,
            contextforge=contextforge,
            job=job,
        )
        payload["semantic_fidelity"] = _semantic_fidelity_summary(
            eval_root / job_id,
            scenario,
            assess_package=assess_package,
        )
    except EvalError as exc:
        payload = {
            "scenario_id": scenario.scenario_id,
            "job_id": job_id,
            "version": version,
            "status": "failed",
            "failure": _failure_payload(str(exc)),
        }
    payload["duration_seconds"] = round(time.monotonic() - started, 3)
    return payload


def _scenario_success_summary(
    *,
    scenario_id: str,
    job_id: str,
    version: str,
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
        "scenario_id": scenario_id,
        "job_id": job_id,
        "version": version,
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
        "refs": _selected_refs(refs),
        "package_downloadable": job.get("package_downloadable"),
    }


def _build_eval_summary(
    *,
    eval_id: str,
    eval_root: Path,
    mode: str,
    live_codex_requested: bool,
    scenario_summaries: list[dict[str, Any]],
    duration_seconds: float,
    created_at: str,
) -> dict[str, Any]:
    totals = _totals(scenario_summaries, duration_seconds=duration_seconds)
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "eval_id": eval_id,
        "created_at": created_at,
        "mode": mode,
        "live_codex_requested": live_codex_requested,
        "runs_root_ref": eval_root.as_posix(),
        "totals": totals,
        "failure_taxonomy": _failure_taxonomy(scenario_summaries),
        "scenarios": scenario_summaries,
        "trust_boundaries": {
            "command_string_included": False,
            "raw_prompt_included": False,
            "raw_frontdesk_conversation_included": False,
            "raw_worker_input_included": False,
            "raw_transcript_included": False,
            "raw_stdout_included": False,
            "raw_stderr_included": False,
            "package_body_included": False,
        },
        "redaction_findings": [],
    }


def _totals(scenarios: list[dict[str, Any]], *, duration_seconds: float) -> dict[str, Any]:
    total = len(scenarios)
    registered = sum(1 for item in scenarios if item.get("status") == "registered")
    verification_failed = 0
    registry_rejected = 0
    api_failed = 0
    semantic_configured = 0
    semantic_passed = 0
    semantic_failed = 0
    registry_skill_ids: set[str] = set()
    for item in scenarios:
        forgeunit = _mapping(item.get("forgeunit_skillfoundry"))
        skill_id = forgeunit.get("registry_skill_id")
        if isinstance(skill_id, str) and skill_id:
            registry_skill_ids.add(skill_id)
        semantic = _mapping(item.get("semantic_fidelity"))
        if semantic.get("configured") is True:
            semantic_configured += 1
            if semantic.get("passed") is True:
                semantic_passed += 1
            else:
                semantic_failed += 1
        if item.get("status") == "failed":
            api_failed += 1
        elif forgeunit.get("verification_passed") is False:
            verification_failed += 1
        elif forgeunit.get("registry_approved") is False:
            registry_rejected += 1
    return {
        "total": total,
        "registered": registered,
        "failed": total - registered,
        "verification_failed": verification_failed,
        "registry_rejected": registry_rejected,
        "api_failed": api_failed,
        "semantic_fidelity_configured": semantic_configured,
        "semantic_fidelity_passed": semantic_passed,
        "semantic_fidelity_failed": semantic_failed,
        "unique_registry_skill_ids": len(registry_skill_ids),
        "redaction_failures": 0,
        "duration_seconds": duration_seconds,
        "average_duration_seconds": round(
            sum(float(item.get("duration_seconds") or 0.0) for item in scenarios) / total,
            3,
        )
        if total
        else 0.0,
    }


def _failure_taxonomy(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for item in scenarios:
        if item.get("status") == "registered":
            continue
        forgeunit = _mapping(item.get("forgeunit_skillfoundry"))
        failure = _mapping(item.get("failure"))
        if failure:
            stage = str(failure.get("stage") or "api")
            reason = str(failure.get("reason") or "scenario_failed")
        elif forgeunit.get("verification_passed") is False:
            stage = "verifier"
            reason = "verification_failed"
        elif forgeunit.get("registry_approved") is False:
            stage = "registry"
            reason = "registry_rejected"
        elif _mapping(item.get("semantic_fidelity")).get("passed") is False:
            stage = "semantic_fidelity"
            reason = "semantic_fidelity_failed"
        else:
            stage = "unknown"
            reason = "scenario_not_registered"
        failures.append(
            {
                "scenario_id": item.get("scenario_id"),
                "job_id": item.get("job_id"),
                "stage": stage,
                "reason": reason,
            }
        )
    return failures


def _semantic_markers_from_payload(value: Any, scenario_id: str) -> tuple[str, ...]:
    if isinstance(value, list):
        markers = tuple(_normalize_marker(item) for item in value if _normalize_marker(item))
    else:
        markers = tuple(part for part in scenario_id.split("-") if len(part) >= 3)
    return markers[:8]


def _normalize_marker(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _semantic_fidelity_summary(workspace: Path, scenario: Scenario, *, assess_package: bool) -> dict[str, Any]:
    markers = scenario.semantic_markers or _semantic_markers_from_payload(None, scenario.scenario_id)
    source_text = _read_refs_text(
        workspace,
        (
            "frontdesk/core_need_brief.json",
            "frontdesk/draft_skill_spec.yaml",
            "frontdesk/solution_plan.json",
            "skill_spec.yaml",
            "worker_input.md",
        ),
    )
    source_matches = _matched_marker_count(source_text, markers)
    package_matches = 0
    package_hash = None
    if assess_package:
        package_path = workspace / "package" / "SKILL.md"
        if package_path.is_file():
            package_text = package_path.read_text(encoding="utf-8")
            package_hash = hashlib.sha256(package_text.encode("utf-8")).hexdigest()
            package_matches = _matched_marker_count(package_text, markers)
    source_passed = bool(markers) and source_matches == len(markers)
    package_passed = not assess_package or (bool(markers) and package_matches == len(markers))
    return {
        "configured": bool(markers),
        "passed": source_passed and package_passed,
        "source_passed": source_passed,
        "package_checked": assess_package,
        "package_passed": package_passed,
        "required_marker_count": len(markers),
        "source_matched_marker_count": source_matches,
        "package_matched_marker_count": package_matches if assess_package else None,
        "package_sha256": package_hash,
    }


def _read_refs_text(workspace: Path, refs: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for ref in refs:
        path = workspace / ref
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _matched_marker_count(text: str, markers: tuple[str, ...]) -> int:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return sum(1 for marker in markers if marker and marker in normalized)


def _redaction_findings(
    summary: Mapping[str, Any],
    *,
    scenario_messages: list[str],
    command: str,
    fake_mode: bool,
) -> list[dict[str, str]]:
    text = json.dumps(summary, sort_keys=True)
    specs: list[tuple[str, str]] = []
    specs.extend(("raw_frontdesk_message", message) for message in scenario_messages if message)
    if command:
        specs.append(("command_string", command))
        for token in ("codex exec", "--sandbox", "--skip-git-repo-check", "forgeunit_codex_exec_worker.py"):
            if token in command:
                specs.append(("command_token", token))
    if fake_mode:
        specs.append(("worker_script_name", "frontdesk_eval_fake_codex_exec.py"))
        specs.append(("fake_worker_transcript", "deterministic forgeunit skillfoundry transcript pointer"))
    specs.extend(
        [
            ("forgeunit_env", "FORGEUNIT_TASK_DIR"),
            ("forgeunit_env", "FORGEUNIT_WORKER_RESULT"),
            ("package_body_marker", "ForgeUnit SkillFoundry Composition Skill"),
        ]
    )
    findings: list[dict[str, str]] = []
    seen: set[str] = set()
    for label, value in specs:
        if value and value in text and label not in seen:
            findings.append({"kind": label})
            seen.add(label)
    return findings


def _failure_payload(message: str) -> dict[str, str]:
    if "frontdesk_build_failed" in message:
        return {"stage": "build", "reason": "frontdesk_build_failed"}
    if "frontdesk_build_missing_summary" in message:
        return {"stage": "build", "reason": "frontdesk_build_missing_summary"}
    if "frontdesk_build_missing_report" in message:
        return {"stage": "build", "reason": "frontdesk_build_missing_report"}
    return {"stage": "api", "reason": "api_request_failed"}


def _require_success(response: Any, label: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise EvalError(f"{label} failed: response was not JSON") from exc
    if response.status >= 400:
        raise EvalError(f"{label} failed: {json.dumps(payload, sort_keys=True)}")
    return payload


def _selected_refs(refs: Mapping[str, Any]) -> dict[str, str]:
    allowed = (
        "forgeunit_skillfoundry_summary",
        "forgeunit_skillfoundry_product_state",
        "forgeunit_skillfoundry_graph_state",
        "skillfoundry_verification_result",
        "registry_decision",
        "registry_entry",
        "final_report",
    )
    return {key: refs[key] for key in allowed if isinstance(refs.get(key), str)}


def _safe_eval_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}", normalized):
        raise EvalError("eval-id must be a safe path segment")
    return normalized


def _optional_non_empty(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EvalError("expected a string value")
    stripped = value.strip()
    return stripped or None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _utc_now() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
