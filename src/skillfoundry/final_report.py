"""Final-report helpers for SkillFoundry job workspaces.

The report schema name is preserved for compatibility with existing
``final_report.json`` artifacts, but this module is not tied to the legacy
offline builder path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .registry import APPROVAL_APPROVED, LocalSkillRegistry
from .schema import (
    ArtifactManifest,
    ExecutionReport,
    JsonValue,
    RegistryEntry,
    VerificationResult,
    ensure_json_compatible,
    sha256_file,
    sha256_json,
    utc_now,
)
from .security import validate_relative_path
from .workspace import JobWorkspace


FINAL_REPORT_VERSION = "skillfoundry.offline.final_report.v1"
OFFLINE_REPORT_VERSION = FINAL_REPORT_VERSION

_LEGACY_ROUTE_VALUES = {
    "build_new",
    "reuse_existing",
    "reject_unsafe",
    "ask_clarifying_question",
}
_TERMINAL_FINAL_STATUSES = {
    "registered",
    "reused",
    "rejected",
    "human_review_required",
    "fail_closed",
}


def load_final_report_workspace(job: str | Path) -> JobWorkspace:
    """Load a job workspace by reading stable workspace refs."""

    root = Path(job)
    manifest = ArtifactManifest.read_json_file(root / "artifact_manifest.json")
    workspace = JobWorkspace(root=root, job_id=manifest.job_id)
    workspace.check_locked_inputs()
    return workspace


def emit_final_report(
    job: str | Path,
    *,
    final_status: Any | None = None,
    route: Any | None = None,
    registry_path: str | Path | None = None,
    registry_entry: RegistryEntry | None = None,
    errors: list[dict[str, JsonValue]] | None = None,
    human_review: Mapping[str, Any] | None = None,
) -> dict[str, JsonValue]:
    """Write and return the machine-readable final report for a job."""

    workspace = load_final_report_workspace(job)
    status_value = _status_value(final_status) if final_status is not None else _infer_final_status(workspace)
    route_value = _route_value(route) if route is not None else None
    report = _build_final_report(
        workspace,
        final_status=status_value,
        route=route_value,
        registry_path=Path(registry_path) if registry_path is not None else None,
        registry_entry=registry_entry,
        errors=errors or [],
        human_review=dict(human_review or {}),
    )
    _write_json(workspace.resolve_path("final_report.json"), report)
    return report


def read_final_report(job: str | Path) -> dict[str, JsonValue]:
    """Read ``final_report.json`` from a job workspace."""

    path = Path(job) / "final_report.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("final_report.json must be a JSON object")
    return ensure_json_compatible(payload)  # type: ignore[return-value]


def _build_final_report(
    workspace: JobWorkspace,
    *,
    final_status: str,
    route: str | None,
    registry_path: Path | None,
    registry_entry: RegistryEntry | None,
    errors: list[dict[str, JsonValue]],
    human_review: dict[str, Any],
) -> dict[str, JsonValue]:
    verification_result = _read_verification_result(workspace)
    registry_entry = registry_entry or _find_registry_entry_for_workspace(workspace, registry_path)
    attempts = _attempt_summaries(workspace)
    latest_execution = _latest_execution_report_ref(workspace)
    artifact_manifest = _file_ref(workspace, "artifact_manifest.json")
    package_hash = _package_hash_for_report(workspace, verification_result, registry_entry)
    registry_payload = _registry_report_payload(registry_path, registry_entry)

    report = {
        "schema_version": OFFLINE_REPORT_VERSION,
        "job_id": workspace.job_id,
        "route": route,
        "final_status": final_status,
        "created_at": utc_now(),
        "refs": {
            "build_contract": _file_ref(workspace, "build_contract.yaml"),
            "skill_spec": _file_ref(workspace, "skill_spec.yaml"),
            "worker_input": _file_ref(workspace, "worker_input.md"),
            "attempts": attempts,
            "latest_execution_report": latest_execution,
            "verifier_result": _verification_result_payload(workspace, verification_result),
            "registry_entry": registry_payload,
            "artifact_manifest": artifact_manifest,
            "package": {
                "ref": "package",
                "sha256": package_hash,
            },
        },
        "hashes": {
            "build_contract": _sha_if_exists(workspace, "build_contract.yaml"),
            "skill_spec": _sha_if_exists(workspace, "skill_spec.yaml"),
            "worker_input": _sha_if_exists(workspace, "worker_input.md"),
            "artifact_manifest": artifact_manifest.get("sha256") if artifact_manifest else None,
            "package": package_hash,
            "latest_execution_report": latest_execution.get("sha256") if latest_execution else None,
            "verifier_result": (
                sha256_file(workspace.resolve_path("verifier/verification_result.json", must_exist=True))
                if verification_result is not None
                else None
            ),
            "registry_entry": registry_payload.get("entry_hash") if registry_payload else None,
        },
        "package_hash": package_hash,
        "human_review": ensure_json_compatible(human_review),
        "errors": errors,
    }
    return ensure_json_compatible(report)  # type: ignore[return-value]


def _attempt_summaries(workspace: JobWorkspace) -> list[dict[str, JsonValue]]:
    attempts_dir = workspace.resolve_path("attempts", must_exist=True)
    attempts: list[dict[str, JsonValue]] = []
    for child in sorted(attempts_dir.iterdir(), key=lambda path: int(path.name) if path.name.isdecimal() else -1):
        if not child.is_dir() or not child.name.isdecimal():
            continue
        attempt_id = child.name
        report = _read_execution_report(workspace, f"attempts/{attempt_id}/execution_report.json")
        attempts.append(
            ensure_json_compatible(
                {
                    "attempt_id": attempt_id,
                    "input_manifest": _file_ref(workspace, f"attempts/{attempt_id}/input_manifest.json"),
                    "execution_report": _file_ref(workspace, f"attempts/{attempt_id}/execution_report.json"),
                    "worker_transcript": _file_ref(workspace, f"attempts/{attempt_id}/worker_transcript.log"),
                    "output_diff": _file_ref(workspace, f"attempts/{attempt_id}/output_diff.patch"),
                    "verification_result": _file_ref(workspace, f"attempts/{attempt_id}/verification_result.json"),
                    "status": report.status if report is not None else None,
                    "exit_status": report.exit_status if report is not None else None,
                    "failures": report.failures if report is not None else [],
                }
            )  # type: ignore[arg-type]
        )
    return attempts


def _file_ref(workspace: JobWorkspace, ref: str) -> dict[str, JsonValue] | None:
    try:
        path = workspace.resolve_path(ref, must_exist=True)
    except Exception:
        return None
    if not path.is_file():
        return None
    return {"ref": ref, "sha256": sha256_file(path)}


def _verification_result_payload(
    workspace: JobWorkspace,
    result: VerificationResult | None,
) -> dict[str, JsonValue] | None:
    if result is None:
        return None
    ref_payload = _file_ref(workspace, "verifier/verification_result.json")
    payload = {
        "ref": "verifier/verification_result.json",
        "sha256": ref_payload.get("sha256") if ref_payload else None,
        "result_id": result.result_id,
        "passed": result.passed,
        "package_hash": result.package_hash,
        "verification_spec_hash": result.verification_spec_hash,
        "verifier_version": result.verifier_version,
        "evidence_refs": result.evidence_refs,
    }
    return ensure_json_compatible(payload)  # type: ignore[return-value]


def _registry_report_payload(
    registry_path: Path | None,
    entry: RegistryEntry | None,
) -> dict[str, JsonValue] | None:
    if entry is None:
        return None
    payload: dict[str, Any] = {
        "skill_id": entry.skill_id,
        "version": entry.version,
        "approval_status": entry.approval_status,
        "quarantine_status": entry.quarantine_status,
        "build_job_id": entry.build_job_id,
        "package_hash": entry.package_hash,
        "entry_hash": sha256_json(entry.to_dict()),
        "entry": entry.to_dict(),
    }
    if registry_path is not None:
        payload["registry_path"] = registry_path.as_posix()
        payload["registry_hash"] = sha256_file(registry_path) if registry_path.exists() else None
    return ensure_json_compatible(payload)  # type: ignore[return-value]


def _find_registry_entry_for_workspace(
    workspace: JobWorkspace,
    registry_path: Path | None,
) -> RegistryEntry | None:
    if registry_path is None or not registry_path.exists():
        return None
    try:
        entries = LocalSkillRegistry(registry_path).list(status="all", include_quarantined=True)
    except Exception:
        return None
    approved = [
        entry
        for entry in entries
        if entry.build_job_id == workspace.job_id and entry.approval_status == APPROVAL_APPROVED
    ]
    return approved[0] if approved else None


def _latest_execution_report_ref(workspace: JobWorkspace) -> dict[str, JsonValue] | None:
    attempts = _attempt_summaries(workspace)
    for attempt in reversed(attempts):
        report = attempt.get("execution_report")
        if isinstance(report, dict) and report.get("ref"):
            return report  # type: ignore[return-value]
    return None


def _read_execution_report(workspace: JobWorkspace, ref: str) -> ExecutionReport | None:
    try:
        return ExecutionReport.read_json_file(workspace.resolve_path(ref, must_exist=True))
    except Exception:
        return None


def _read_verification_result(workspace: JobWorkspace) -> VerificationResult | None:
    try:
        return VerificationResult.read_json_file(workspace.resolve_path("verifier/verification_result.json", must_exist=True))
    except Exception:
        return None


def _package_hash_for_report(
    workspace: JobWorkspace,
    verification_result: VerificationResult | None,
    registry_entry: RegistryEntry | None,
) -> str | None:
    if registry_entry is not None:
        return registry_entry.package_hash
    if verification_result is not None:
        return verification_result.package_hash
    try:
        return _hash_package_dir(workspace.resolve_path("package", must_exist=True))
    except Exception:
        return None


def _hash_package_dir(package_dir: Path) -> str:
    entries: list[dict[str, JsonValue]] = []
    root = package_dir.resolve(strict=True)
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            relative = path.relative_to(root).as_posix()
            entries.append({"path": relative, "kind": "symlink", "target": str(path.readlink())})
        elif path.is_file():
            relative = path.relative_to(root).as_posix()
            validate_relative_path(relative)
            entries.append({"path": relative, "kind": "file", "sha256": sha256_file(path), "size": path.stat().st_size})
        elif path.is_dir():
            relative = path.relative_to(root).as_posix()
            if relative != ".":
                validate_relative_path(relative)
                entries.append({"path": relative, "kind": "dir"})
    return sha256_json(entries)


def _sha_if_exists(workspace: JobWorkspace, ref: str) -> str | None:
    payload = _file_ref(workspace, ref)
    if payload is None:
        return None
    value = payload.get("sha256")
    return str(value) if value is not None else None


def _infer_final_status(workspace: JobWorkspace) -> str:
    existing = workspace.root / "final_report.json"
    if existing.exists():
        try:
            payload = json.loads(existing.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if isinstance(payload, dict) and payload.get("final_status") in _TERMINAL_FINAL_STATUSES:
            return str(payload["final_status"])
    result = _read_verification_result(workspace)
    if result is not None and result.passed:
        return "verified"
    return "fail_closed"


def _status_value(status: Any) -> str:
    value = getattr(status, "value", status)
    return str(value)


def _route_value(route: Any) -> str:
    value = getattr(route, "value", route)
    route_value = str(value)
    if route_value not in _LEGACY_ROUTE_VALUES:
        raise ValueError(f"unknown route: {route_value}")
    return route_value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    compatible = ensure_json_compatible(dict(payload))
    path.write_text(
        json.dumps(compatible, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
