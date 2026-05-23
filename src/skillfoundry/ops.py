"""WP12 local operations helpers for internal beta hardening."""

from __future__ import annotations

from collections import Counter
import importlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

from .registry import (
    APPROVAL_APPROVED,
    APPROVAL_REJECTED,
    QUARANTINE_QUARANTINED,
    LocalSkillRegistry,
)
from .schema import JsonValue, ensure_json_compatible, sha256_file, utc_now
from .security import PathSecurityError, assert_under_root
from .workspace import JOB_ID_RE, LOCKED_INPUT_PATHS


OPS_VERSION = "skillfoundry.ops.wp12.v1"
OPS_CLEANUP_REPORT_VERSION = "skillfoundry.ops.cleanup_report.v1"
OPS_HEALTH_REPORT_VERSION = "skillfoundry.ops.health_report.v1"
OPS_OBSERVABILITY_REPORT_VERSION = "skillfoundry.ops.observability_report.v1"

TRANSIENT_FILE_SUFFIXES = (".tmp", ".temp", ".bak", ".swp", ".pyc", ".pyo")
TRANSIENT_DIR_NAMES = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")
TEST_COMMAND = ".venv/bin/python -m pytest -q"


class SkillFoundryOps:
    """Small local operations surface for WP7-WP11 internal beta readiness.

    This helper intentionally stays in-process and filesystem-backed. It does
    not introduce a queue, service dependency, auth platform, database, or
    production scheduler.
    """

    def __init__(self, runs_root: str | Path, *, registry_path: str | Path | None = None) -> None:
        self.runs_root = Path(runs_root).expanduser()
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self._runs_root_resolved = self.runs_root.resolve(strict=True)
        self.registry_path = self._resolve_registry_path(registry_path)

    def cleanup_artifacts(self, *, dry_run: bool = True) -> dict[str, JsonValue]:
        """Remove only known transient artifacts, with dry-run by default."""

        planned: list[dict[str, JsonValue]] = []
        removed: list[dict[str, JsonValue]] = []
        preserved: list[dict[str, JsonValue]] = []
        errors: list[dict[str, JsonValue]] = []
        approved_package_roots = self._approved_package_roots()

        for candidate in self._transient_candidates():
            relative = candidate.relative_to(self._runs_root_resolved).as_posix()
            preserve_reason = self._preserve_reason(candidate, approved_package_roots)
            if preserve_reason is not None:
                preserved.append(
                    {
                        "path": relative,
                        "reason": preserve_reason,
                    }
                )
                continue

            record = {
                "path": relative,
                "kind": "directory" if candidate.is_dir() and not candidate.is_symlink() else "file",
                "reason": self._transient_reason(candidate),
            }
            planned.append(record)
            if dry_run:
                continue
            try:
                if candidate.is_symlink():
                    preserved.append({"path": relative, "reason": "symlink skipped"})
                    continue
                if candidate.is_dir():
                    shutil.rmtree(candidate)
                else:
                    candidate.unlink()
                removed.append(record)
            except Exception as exc:  # pragma: no cover - defensive filesystem boundary
                errors.append(
                    {
                        "path": relative,
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }
                )

        return ensure_json_compatible(
            {
                "schema_version": OPS_CLEANUP_REPORT_VERSION,
                "created_at": utc_now(),
                "runs_root": self._runs_root_resolved.as_posix(),
                "registry_path": self.registry_path.as_posix(),
                "dry_run": dry_run,
                "applied": not dry_run,
                "planned_removals": planned,
                "planned_removal_count": len(planned),
                "removed": removed,
                "removed_count": len(removed),
                "preserved": preserved,
                "preserved_count": len(preserved),
                "errors": errors,
                "error_count": len(errors),
            }
        )  # type: ignore[return-value]

    def observability_report(self) -> dict[str, JsonValue]:
        """Summarize local jobs, gates, registry state, failures, and usage."""

        job_summaries: list[dict[str, JsonValue]] = []
        status_counts: Counter[str] = Counter()
        failure_classes: Counter[str] = Counter()
        failed_jobs: list[dict[str, JsonValue]] = []
        verifier_counts: Counter[str] = Counter()
        qa_counts: Counter[str] = Counter()
        duration_total_ms = 0
        duration_missing_count = 0
        attempt_total = 0
        usage_available_count = 0
        usage_unavailable_count = 0
        usage_unavailable_reasons: Counter[str] = Counter()

        for job_root in self._job_dirs():
            report = _read_json_if_exists(job_root / "final_report.json")
            final_status = _str_or(report.get("final_status") if isinstance(report, Mapping) else None, "workspace")
            status_counts[final_status] += 1

            attempts = self._attempt_observations(job_root)
            attempt_total += len(attempts)
            job_duration_ms = 0
            job_duration_available = False
            for attempt in attempts:
                duration = attempt.get("duration_ms")
                if isinstance(duration, int) and not isinstance(duration, bool):
                    duration_total_ms += duration
                    job_duration_ms += duration
                    job_duration_available = True
                else:
                    duration_missing_count += 1

                usage = attempt.get("usage")
                if isinstance(usage, Mapping) and usage.get("available") is True:
                    usage_available_count += 1
                else:
                    usage_unavailable_count += 1
                    reason = "usage evidence unavailable"
                    if isinstance(usage, Mapping) and isinstance(usage.get("unavailable_reason"), str):
                        reason = str(usage["unavailable_reason"])
                    usage_unavailable_reasons[reason] += 1

                failure_class = attempt.get("failure_class")
                if isinstance(failure_class, str) and failure_class:
                    failure_classes[failure_class] += 1

            verifier_status = self._verifier_status(job_root)
            verifier_counts[verifier_status] += 1
            qa_status = self._qa_status(job_root)
            qa_counts[qa_status] += 1

            report_errors = _report_errors(report)
            for error in report_errors:
                code = error.get("code")
                if isinstance(code, str) and code:
                    failure_classes[code] += 1

            if final_status not in {"registered", "reused", "workspace"} or report_errors:
                failed_job = {
                    "job_id": job_root.name,
                    "final_status": final_status,
                    "failure_classes": sorted(
                        {
                            str(item.get("failure_class"))
                            for item in attempts
                            if isinstance(item.get("failure_class"), str) and item.get("failure_class")
                        }
                        | {str(item.get("code")) for item in report_errors if isinstance(item.get("code"), str)}
                    ),
                    "errors": report_errors,
                }
                failed_jobs.append(ensure_json_compatible(failed_job))  # type: ignore[arg-type]

            job_summaries.append(
                ensure_json_compatible(
                    {
                        "job_id": job_root.name,
                        "path": job_root.as_posix(),
                        "final_status": final_status,
                        "attempt_count": len(attempts),
                        "verifier": verifier_status,
                        "qa": qa_status,
                        "duration_ms": job_duration_ms if job_duration_available else None,
                        "duration_available": job_duration_available,
                    }
                )  # type: ignore[arg-type]
            )

        registry_summary = self._registry_summary()
        feedback_summary = self._feedback_versioning_summary(registry_summary.get("entries", []))
        duration_available = attempt_total > 0 and duration_missing_count < attempt_total
        usage_summary = {
            "attempts_with_usage_available": usage_available_count,
            "attempts_with_usage_unavailable": usage_unavailable_count,
            "unavailable_reasons": dict(sorted(usage_unavailable_reasons.items())),
            "availability": _usage_availability(usage_available_count, usage_unavailable_count),
        }

        return ensure_json_compatible(
            {
                "schema_version": OPS_OBSERVABILITY_REPORT_VERSION,
                "created_at": utc_now(),
                "runs_root": self._runs_root_resolved.as_posix(),
                "registry_path": self.registry_path.as_posix(),
                "jobs": {
                    "count": len(job_summaries),
                    "statuses": dict(sorted(status_counts.items())),
                    "final_status_distribution": dict(sorted(status_counts.items())),
                    "items": sorted(job_summaries, key=lambda item: str(item["job_id"])),
                },
                "failures": {
                    "failed_job_count": len(failed_jobs),
                    "failed_jobs": sorted(failed_jobs, key=lambda item: str(item["job_id"])),
                    "classes": dict(sorted(failure_classes.items())),
                },
                "attempts": {
                    "total": attempt_total,
                    "by_job": {str(item["job_id"]): item["attempt_count"] for item in job_summaries},
                },
                "verifier": {
                    "passed": verifier_counts.get("passed", 0),
                    "failed": verifier_counts.get("failed", 0),
                    "missing": verifier_counts.get("missing", 0),
                    "invalid": verifier_counts.get("invalid", 0),
                },
                "qa": {
                    "passed": qa_counts.get("passed", 0),
                    "failed": qa_counts.get("failed", 0),
                    "missing": qa_counts.get("missing", 0),
                    "invalid": qa_counts.get("invalid", 0),
                },
                "registry": registry_summary,
                "feedback_versioning": feedback_summary,
                "durations": {
                    "available": duration_available,
                    "total_duration_ms": duration_total_ms if duration_available else None,
                    "missing_attempt_count": duration_missing_count,
                    "unavailable_reason": None if duration_available else "no attempt execution reports with duration_ms",
                },
                "usage": usage_summary,
            }
        )  # type: ignore[return-value]

    def health_check(self) -> dict[str, JsonValue]:
        """Return machine-readable health/readiness checks."""

        checks: list[dict[str, JsonValue]] = []
        checks.append(
            _check(
                "runs_root_exists",
                self._runs_root_resolved.exists() and self._runs_root_resolved.is_dir(),
                f"runs root is {self._runs_root_resolved}",
            )
        )
        checks.append(self._writable_check())
        checks.append(self._registry_control_check())
        checks.append(self._registry_parse_check())
        checks.append(self._workspace_path_sanity_check())
        checks.append(self._import_check())
        checks.append(self._cli_check())
        checks.append(
            _check(
                "test_command_documented",
                True,
                f"default verification command: {TEST_COMMAND}",
                severity="info",
                details={"command": TEST_COMMAND},
            )
        )
        ready = all(item["passed"] is True for item in checks if item.get("severity") == "error")
        return ensure_json_compatible(
            {
                "schema_version": OPS_HEALTH_REPORT_VERSION,
                "created_at": utc_now(),
                "ready": ready,
                "runs_root": self._runs_root_resolved.as_posix(),
                "registry_path": self.registry_path.as_posix(),
                "checks": checks,
            }
        )  # type: ignore[return-value]

    def readiness_check(self) -> dict[str, JsonValue]:
        """Alias for ``health_check`` used by operations docs and CLI."""

        return self.health_check()

    def _resolve_registry_path(self, registry_path: str | Path | None) -> Path:
        path = self.runs_root / "registry.json" if registry_path is None else Path(registry_path).expanduser()
        if not path.is_absolute():
            path = self._runs_root_resolved / path
        return path.resolve(strict=False)

    def _job_root(self, job_id: str) -> Path:
        return self._runs_root_resolved / job_id

    def _job_dirs(self) -> list[Path]:
        candidates: list[Path] = []
        for path in sorted(self._runs_root_resolved.iterdir(), key=lambda item: item.name):
            if path.is_symlink() or not path.is_dir():
                continue
            if not JOB_ID_RE.fullmatch(path.name):
                continue
            if any((path / marker).exists() for marker in ("final_report.json", "artifact_manifest.json", "build_contract.yaml")):
                candidates.append(path)
        return candidates

    def _attempt_observations(self, job_root: Path) -> list[dict[str, JsonValue]]:
        attempts_dir = job_root / "attempts"
        if not attempts_dir.is_dir() or attempts_dir.is_symlink():
            return []
        attempts: list[dict[str, JsonValue]] = []
        for attempt_dir in sorted(attempts_dir.iterdir(), key=lambda item: int(item.name) if item.name.isdecimal() else -1):
            if not attempt_dir.is_dir() or not attempt_dir.name.isdecimal():
                continue
            report = _read_json_if_exists(attempt_dir / "execution_report.json")
            input_manifest = _read_json_if_exists(attempt_dir / "input_manifest.json")
            failure_class = _attempt_failure_class(report)
            attempts.append(
                ensure_json_compatible(
                    {
                        "attempt_id": attempt_dir.name,
                        "status": report.get("status") if isinstance(report, Mapping) else None,
                        "exit_status": report.get("exit_status") if isinstance(report, Mapping) else None,
                        "duration_ms": report.get("duration_ms") if isinstance(report, Mapping) else None,
                        "failure_class": failure_class,
                        "usage": _usage_observation(input_manifest),
                    }
                )  # type: ignore[arg-type]
            )
        return attempts

    def _verifier_status(self, job_root: Path) -> str:
        payload = _read_json_if_exists(job_root / "verifier" / "verification_result.json")
        if payload is None:
            return "missing"
        if not isinstance(payload, Mapping):
            return "invalid"
        return "passed" if payload.get("passed") is True else "failed"

    def _qa_status(self, job_root: Path) -> str:
        payload = _read_json_if_exists(job_root / "qa" / "quality_report.json")
        if payload is None:
            return "missing"
        if not isinstance(payload, Mapping):
            return "invalid"
        return "passed" if payload.get("passed") is True or payload.get("hard_gate_passed") is True else "failed"

    def _registry_summary(self) -> dict[str, JsonValue]:
        if not self.registry_path.exists():
            return {
                "parseable": True,
                "exists": False,
                "total": 0,
                "approved": 0,
                "quarantined": 0,
                "rejected": 0,
                "entries": [],
                "error": None,
            }
        try:
            entries = LocalSkillRegistry(self.registry_path).list(status="all", include_quarantined=True)
        except Exception as exc:
            return {
                "parseable": False,
                "exists": True,
                "total": 0,
                "approved": 0,
                "quarantined": 0,
                "rejected": 0,
                "entries": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
        return ensure_json_compatible(
            {
                "parseable": True,
                "exists": True,
                "total": len(entries),
                "approved": len([entry for entry in entries if entry.approval_status == APPROVAL_APPROVED]),
                "quarantined": len([entry for entry in entries if entry.quarantine_status == QUARANTINE_QUARANTINED]),
                "rejected": len([entry for entry in entries if entry.approval_status == APPROVAL_REJECTED]),
                "entries": [entry.to_dict() for entry in entries],
                "sha256": sha256_file(self.registry_path),
                "error": None,
            }
        )  # type: ignore[return-value]

    def _feedback_versioning_summary(self, registry_entries: JsonValue) -> dict[str, JsonValue]:
        feedback_records = list(self._runs_root_resolved.rglob("feedback_record.json"))
        repair_plans = list(self._runs_root_resolved.rglob("feedback_repair_plan.json"))
        version_change_reports = list(self._runs_root_resolved.rglob("versioning/version_change_report.json"))
        rollback_events = list(self._runs_root_resolved.rglob("versioning/rollback_event.json"))
        registry_feedback_events = 0
        if isinstance(registry_entries, list):
            for item in registry_entries:
                if isinstance(item, Mapping):
                    provenance = item.get("provenance")
                    if isinstance(provenance, Mapping) and isinstance(provenance.get("feedback_versioning"), Mapping):
                        registry_feedback_events += 1
        return {
            "feedback_records": len(feedback_records),
            "repair_plans": len(repair_plans),
            "version_change_reports": len(version_change_reports),
            "rollback_events": len(rollback_events),
            "registry_feedback_versioning_events": registry_feedback_events,
        }

    def _writable_check(self) -> dict[str, JsonValue]:
        probe = self._runs_root_resolved / f".skillfoundry-health-{os.getpid()}.tmp"
        try:
            probe.write_text("ok\n", encoding="utf-8")
            probe.unlink()
            return _check("runs_root_writable", True, "runs root accepts temporary writes")
        except Exception as exc:
            return _check("runs_root_writable", False, f"runs root is not writable: {exc}")

    def _registry_control_check(self) -> dict[str, JsonValue]:
        try:
            parent = _existing_parent(self.registry_path)
            parent_resolved = parent.resolve(strict=True)
            runs_parent = self._runs_root_resolved.parent.resolve(strict=True)
            under_control = _is_relative_to(parent_resolved, self._runs_root_resolved) or _is_relative_to(parent_resolved, runs_parent)
            inside_job = any(_is_relative_to(self.registry_path.resolve(strict=False), job_root.resolve(strict=True)) for job_root in self._job_dirs())
        except Exception as exc:
            return _check("registry_path_controlled", False, f"registry path cannot be resolved safely: {exc}")
        if inside_job:
            return _check("registry_path_controlled", False, "registry path must not live inside a job workspace")
        return _check(
            "registry_path_controlled",
            under_control,
            "registry path is under runs root or its owning parent",
            details={"registry_path": self.registry_path.as_posix()},
        )

    def _registry_parse_check(self) -> dict[str, JsonValue]:
        if not self.registry_path.exists():
            return _check(
                "registry_parseable",
                True,
                "registry file is absent and will be created on first approved registration",
                details={"exists": False},
            )
        try:
            entries = LocalSkillRegistry(self.registry_path).list(status="all", include_quarantined=True)
        except Exception as exc:
            return _check("registry_parseable", False, f"registry JSON is not parseable: {type(exc).__name__}: {exc}")
        return _check(
            "registry_parseable",
            True,
            f"registry parsed with {len(entries)} entries",
            details={"entries": len(entries)},
        )

    def _workspace_path_sanity_check(self) -> dict[str, JsonValue]:
        failures: list[str] = []
        for path in self._runs_root_resolved.iterdir():
            if path.is_symlink():
                failures.append(f"{path.name}: symlink under runs root")
                continue
            if not path.is_dir() or path.name.startswith("."):
                continue
            if not JOB_ID_RE.fullmatch(path.name):
                failures.append(f"{path.name}: unsafe job directory name")
                continue
            try:
                assert_under_root(self._runs_root_resolved, path.resolve(strict=True))
            except PathSecurityError as exc:
                failures.append(f"{path.name}: {exc}")
        return _check(
            "workspace_path_sanity",
            not failures,
            "job workspaces use safe names and resolve under runs root" if not failures else "; ".join(failures),
            details={"failures": failures},
        )

    def _import_check(self) -> dict[str, JsonValue]:
        try:
            package = importlib.import_module("skillfoundry")
            exported = getattr(package, "SkillFoundryOps", None)
        except Exception as exc:
            return _check("import_readiness", False, f"skillfoundry import failed: {type(exc).__name__}: {exc}")
        return _check("import_readiness", exported is SkillFoundryOps, "skillfoundry imports and exports SkillFoundryOps")

    def _cli_check(self) -> dict[str, JsonValue]:
        try:
            cli = importlib.import_module("skillfoundry.cli")
            main = getattr(cli, "main", None)
        except Exception as exc:
            return _check("cli_readiness", False, f"skillfoundry.cli import failed: {type(exc).__name__}: {exc}")
        return _check("cli_readiness", callable(main), "skillfoundry CLI entrypoint is importable")

    def _transient_candidates(self) -> list[Path]:
        candidates: list[Path] = []
        for root, dirs, files in os.walk(self._runs_root_resolved):
            root_path = Path(root)
            transient_dirs = [name for name in dirs if name in TRANSIENT_DIR_NAMES]
            for dirname in transient_dirs:
                candidates.append(root_path / dirname)
            dirs[:] = [name for name in dirs if name not in TRANSIENT_DIR_NAMES]
            for filename in files:
                path = root_path / filename
                if _is_transient_file(path):
                    candidates.append(path)
        return sorted(
            candidates,
            key=lambda item: (len(item.relative_to(self._runs_root_resolved).parts), item.as_posix()),
            reverse=True,
        )

    def _approved_package_roots(self) -> list[Path]:
        if not self.registry_path.exists():
            return []
        try:
            entries = LocalSkillRegistry(self.registry_path).list(status=APPROVAL_APPROVED, include_quarantined=False)
        except Exception:
            return []
        roots: list[Path] = []
        for entry in entries:
            try:
                package_root = Path(entry.package_path).resolve(strict=True)
            except Exception:
                continue
            if package_root.is_dir():
                roots.append(package_root)
        return roots

    def _preserve_reason(self, candidate: Path, approved_package_roots: Sequence[Path]) -> str | None:
        if candidate.is_symlink():
            return "symlink skipped"
        resolved = candidate.resolve(strict=False)
        if any(_is_relative_to(resolved, package_root) for package_root in approved_package_roots):
            return "approved package"
        relative = resolved.relative_to(self._runs_root_resolved).as_posix()
        if relative in LOCKED_INPUT_PATHS or relative in _PROVENANCE_CRITICAL_REFS:
            return "provenance-critical artifact"
        if _matches_provenance_pattern(relative):
            return "provenance-critical artifact"
        return None

    def _transient_reason(self, candidate: Path) -> str:
        if candidate.is_dir() and candidate.name in TRANSIENT_DIR_NAMES:
            return f"transient directory {candidate.name}"
        suffix = candidate.suffix
        return f"transient suffix {suffix}" if suffix else "transient file"


_PROVENANCE_CRITICAL_REFS = {
    "artifact_manifest.json",
    "build_contract.yaml",
    "skill_spec.yaml",
    "verification_spec.yaml",
    "worker_input.md",
    "final_report.json",
    "resume_brief.md",
    "verifier/verification_result.json",
    "qa/quality_report.json",
    "feedback_record.json",
    "feedback_repair_plan.json",
    "versioning/version_change_report.json",
    "versioning/rollback_event.json",
}


def _check(
    name: str,
    passed: bool,
    message: str,
    *,
    severity: str = "error",
    details: Mapping[str, Any] | None = None,
) -> dict[str, JsonValue]:
    return ensure_json_compatible(
        {
            "name": name,
            "passed": passed,
            "severity": severity,
            "message": message,
            "details": dict(details or {}),
        }
    )  # type: ignore[return-value]


def _read_json_if_exists(path: Path) -> dict[str, JsonValue] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"_invalid_json": True}
    if not isinstance(payload, dict):
        return {"_invalid_json": True}
    return ensure_json_compatible(payload)  # type: ignore[return-value]


def _report_errors(report: Mapping[str, Any] | None) -> list[dict[str, JsonValue]]:
    if not isinstance(report, Mapping):
        return []
    errors = report.get("errors")
    if not isinstance(errors, list):
        return []
    result: list[dict[str, JsonValue]] = []
    for item in errors:
        if isinstance(item, Mapping):
            result.append(ensure_json_compatible(dict(item)))  # type: ignore[arg-type]
    return result


def _attempt_failure_class(report: Mapping[str, Any] | None) -> str | None:
    if not isinstance(report, Mapping):
        return None
    exit_status = report.get("exit_status")
    status = report.get("status")
    if exit_status == "success" and status == "completed":
        return None
    if isinstance(exit_status, str) and exit_status:
        return exit_status
    if isinstance(status, str) and status:
        return status
    failures = report.get("failures")
    if isinstance(failures, list) and failures:
        return "worker_failure"
    return None


def _usage_observation(input_manifest: Mapping[str, Any] | None) -> dict[str, JsonValue]:
    if not isinstance(input_manifest, Mapping):
        return {"available": False, "unavailable_reason": "missing worker input manifest"}
    worker_type = input_manifest.get("worker_type")
    if isinstance(worker_type, str) and worker_type.startswith("offline:"):
        return {
            "available": False,
            "worker_type": worker_type,
            "unavailable_reason": "Offline deterministic worker does not call model providers.",
        }
    if worker_type == "codex:exec":
        return {
            "available": False,
            "worker_type": worker_type,
            "unavailable_reason": "Codex CLI pilot usage is unavailable at the worker boundary.",
        }
    return {
        "available": False,
        "worker_type": worker_type if isinstance(worker_type, str) else None,
        "unavailable_reason": "Persisted execution reports do not include provider usage counters.",
    }


def _usage_availability(available: int, unavailable: int) -> str:
    if available and unavailable:
        return "partial"
    if available:
        return "available"
    if unavailable:
        return "unavailable"
    return "no_attempts"


def _str_or(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _is_transient_file(path: Path) -> bool:
    return path.name.startswith(".skillfoundry-health-") or path.suffix in TRANSIENT_FILE_SUFFIXES


def _matches_provenance_pattern(relative: str) -> bool:
    parts = relative.split("/")
    if len(parts) == 3 and parts[0] == "attempts" and parts[1].isdecimal():
        return parts[2] in {
            "input_manifest.json",
            "execution_report.json",
            "worker_transcript.log",
            "output_diff.patch",
            "verification_result.json",
        }
    return False


def _existing_parent(path: Path) -> Path:
    current = path if path.exists() and path.is_dir() else path.parent
    while not current.exists():
        if current.parent == current:
            raise FileNotFoundError(f"no existing parent for {path}")
        current = current.parent
    return current


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
