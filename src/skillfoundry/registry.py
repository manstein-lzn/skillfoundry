"""WP6 local registry for independently verified Skill packages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from contextlib import contextmanager
import os
import json
from pathlib import Path
import re
import threading
from typing import Any, Mapping

import fcntl

from .schema import (
    ArtifactManifest,
    ExecutionReport,
    JsonValue,
    RegistryEntry,
    SchemaValidationError,
    SkillSpec,
    VerificationResult,
    ensure_json_compatible,
    sha256_file,
    sha256_json,
    utc_now,
)
from .security import PathSecurityError, assert_under_root, resolve_under_root, validate_relative_path
from .workspace import JobWorkspace


REGISTRY_STORE_VERSION = "skillfoundry.local_registry.v1"
REGISTRY_PROVENANCE_VERSION = "skillfoundry.registry_provenance.v1"
DEFAULT_REGISTRY_VERSION = "0.1.0"

APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
QUARANTINE_NONE = "none"
QUARANTINE_QUARANTINED = "quarantined"

_EXECUTION_REPORT_RE = re.compile(r"^attempts/(?P<attempt_id>[0-9]+)/execution_report\.json$")
_REGISTRY_THREAD_LOCKS: dict[Path, threading.RLock] = {}
_REGISTRY_THREAD_LOCKS_GUARD = threading.Lock()
_REGISTRY_LOCK_STATE = threading.local()


class DuplicatePolicy(StrEnum):
    """Duplicate skill/version handling for local registry writes."""

    REJECT = "reject"
    IDEMPOTENT = "idempotent"


class RegistryError(ValueError):
    """Base class for registry failures."""


class RegistryGateError(RegistryError):
    """Raised when a workspace fails the registry approval gate."""

    def __init__(self, failures: list[str]) -> None:
        self.failures = failures
        super().__init__("registry gate failed: " + "; ".join(failures))


class RegistryDuplicateError(RegistryError):
    """Raised when a duplicate skill/version violates the registry policy."""


class RegistryEntryNotFound(RegistryError):
    """Raised when a requested registry entry does not exist."""


@dataclass(frozen=True)
class RegistryVerificationReport:
    """Integrity report for a persisted registry entry."""

    skill_id: str
    version: str
    valid: bool
    failures: list[str]
    checked_at: str

    def __bool__(self) -> bool:
        return self.valid

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_json_compatible(
            {
                "skill_id": self.skill_id,
                "version": self.version,
                "valid": self.valid,
                "failures": self.failures,
                "checked_at": self.checked_at,
            }
        )  # type: ignore[return-value]


class LocalSkillRegistry:
    """Deterministic JSON-backed registry for verifier-approved packages."""

    def __init__(
        self,
        path: str | Path,
        *,
        duplicate_policy: DuplicatePolicy | str = DuplicatePolicy.REJECT,
    ) -> None:
        self.path = Path(path)
        self.duplicate_policy = DuplicatePolicy(duplicate_policy)

    def add_verified(
        self,
        workspace: JobWorkspace,
        *,
        skill_id: str | None = None,
        version: str = DEFAULT_REGISTRY_VERSION,
        review_status: str = "not_reviewed",
    ) -> RegistryEntry:
        """Register a package only after the independent verifier and hash gates pass."""

        entry = _build_verified_entry(
            workspace,
            skill_id=skill_id,
            version=version,
            review_status=review_status,
        )
        report = self.verify_entry(entry)
        if not report.valid:
            raise RegistryGateError(report.failures)

        with self._locked_store():
            entries = self._load_entries()
            existing = _find_entry(entries, entry.skill_id, entry.version)
            if existing is not None:
                if self.duplicate_policy is DuplicatePolicy.IDEMPOTENT and _same_registered_asset(existing, entry):
                    return existing
                raise RegistryDuplicateError(
                    f"duplicate registry entry for {entry.skill_id!r} version {entry.version!r} "
                    f"violates duplicate_policy={self.duplicate_policy.value!r}"
                )

            entries.append(entry)
            self._write_entries(entries)
        return entry

    def get(self, skill_id: str, version: str) -> RegistryEntry:
        """Return one registry entry by skill id and version."""

        entry = _find_entry(self._load_entries(), skill_id, version)
        if entry is None:
            raise RegistryEntryNotFound(f"registry entry not found: {skill_id}@{version}")
        return entry

    def list(
        self,
        *,
        status: str | None = APPROVAL_APPROVED,
        include_quarantined: bool = False,
    ) -> list[RegistryEntry]:
        """List entries, defaulting to approved and non-quarantined reuse candidates."""

        entries = self._load_entries()
        if status is None or status == "all":
            result = entries
        elif status == QUARANTINE_QUARANTINED:
            result = [entry for entry in entries if entry.quarantine_status == QUARANTINE_QUARANTINED]
        else:
            result = [entry for entry in entries if entry.approval_status == status]

        if not include_quarantined and status != QUARANTINE_QUARANTINED:
            result = [entry for entry in result if entry.quarantine_status != QUARANTINE_QUARANTINED]
        return sorted(result, key=_entry_sort_key)

    def reuse_candidates(self) -> list[RegistryEntry]:
        """Return approved entries eligible for default reuse."""

        return self.list(status=APPROVAL_APPROVED, include_quarantined=False)

    def verify(self, skill_id: str, version: str) -> RegistryVerificationReport:
        """Verify a stored entry against current package and evidence files."""

        return self.verify_entry(self.get(skill_id, version))

    def verify_entry(self, entry: RegistryEntry) -> RegistryVerificationReport:
        """Check that an entry still matches current package, verifier, and provenance files."""

        failures: list[str] = []
        try:
            entry.validate()
        except Exception as exc:
            failures.append(f"registry_entry: invalid RegistryEntry: {exc}")

        workspace_root = _workspace_root_for_entry(entry, failures)
        package_dir = _package_dir_for_entry(entry, workspace_root, failures)
        if package_dir is not None:
            package_hash, package_failures = _hash_package_dir(package_dir)
            failures.extend(f"package: {failure}" for failure in package_failures)
            if package_hash != entry.package_hash:
                failures.append(f"package_hash: expected {entry.package_hash}, got {package_hash}")

        result: VerificationResult | None = None
        result_path = _artifact_path_from_entry(entry, workspace_root, ("verification_result", "ref"), failures)
        if result_path is not None:
            result_hash = _hash_file_or_failure(result_path, "verification_result_hash", failures)
            if result_hash is not None and result_hash != entry.verification_result_hash:
                failures.append(
                    f"verification_result_hash: expected {entry.verification_result_hash}, got {result_hash}"
                )
            try:
                result = VerificationResult.read_json_file(result_path)
            except Exception as exc:
                failures.append(f"verification_result: missing or invalid: {exc}")

        if result is not None:
            _check_result_against_entry(result, entry, failures)

        spec_path = _artifact_path_from_entry(entry, workspace_root, ("verification_spec", "ref"), failures)
        if spec_path is not None:
            spec_hash = _hash_file_or_failure(spec_path, "verification_spec_hash", failures)
            if spec_hash is not None and spec_hash != entry.verification_spec_hash:
                failures.append(f"verification_spec_hash: expected {entry.verification_spec_hash}, got {spec_hash}")

        manifest_path = _artifact_path_from_entry(entry, workspace_root, ("artifact_manifest", "ref"), failures)
        if manifest_path is not None:
            manifest_hash = _hash_file_or_failure(manifest_path, "artifact_manifest_hash", failures)
            if manifest_hash is not None and manifest_hash != entry.artifact_manifest_hash:
                failures.append(f"artifact_manifest_hash: expected {entry.artifact_manifest_hash}, got {manifest_hash}")
            try:
                manifest = ArtifactManifest.read_json_file(manifest_path)
            except Exception as exc:
                failures.append(f"artifact_manifest: missing or invalid: {exc}")
            else:
                _check_manifest_against_entry(manifest, entry, workspace_root, failures)

        report_path = _artifact_path_from_entry(entry, workspace_root, ("execution_report", "ref"), failures)
        if report_path is not None:
            try:
                report = ExecutionReport.read_json_file(report_path)
            except Exception as exc:
                failures.append(f"execution_report: missing or invalid: {exc}")
            else:
                _check_execution_report_against_entry(report, entry, failures)
                _check_input_manifest_against_entry(entry, workspace_root, report, failures)

        return RegistryVerificationReport(
            skill_id=entry.skill_id,
            version=entry.version,
            valid=not failures,
            failures=failures,
            checked_at=utc_now(),
        )

    def quarantine(self, skill_id: str, version: str, reason: str) -> RegistryEntry:
        """Mark an entry quarantined without mutating its package."""

        _require_non_empty(reason, "reason")
        return self._update_entry_status(
            skill_id,
            version,
            approval_status=None,
            quarantine_status=QUARANTINE_QUARANTINED,
            event_name="quarantine",
            reason=reason,
        )

    def reject(self, skill_id: str, version: str, reason: str) -> RegistryEntry:
        """Mark an existing entry rejected without approving new verifier-failed output."""

        _require_non_empty(reason, "reason")
        return self._update_entry_status(
            skill_id,
            version,
            approval_status=APPROVAL_REJECTED,
            quarantine_status=None,
            event_name="rejection",
            reason=reason,
        )

    def _update_entry_status(
        self,
        skill_id: str,
        version: str,
        *,
        approval_status: str | None,
        quarantine_status: str | None,
        event_name: str,
        reason: str,
    ) -> RegistryEntry:
        with self._locked_store():
            entries = self._load_entries()
            index, existing = _find_entry_with_index(entries, skill_id, version)
            if existing is None or index is None:
                raise RegistryEntryNotFound(f"registry entry not found: {skill_id}@{version}")

            provenance = dict(existing.provenance)
            events = list(provenance.get("registry_events", [])) if isinstance(provenance.get("registry_events"), list) else []
            events.append(
                ensure_json_compatible(
                    {
                        "event": event_name,
                        "reason": reason,
                        "created_at": utc_now(),
                    }
                )
            )
            provenance["registry_events"] = events

            updated = RegistryEntry(
                skill_id=existing.skill_id,
                version=existing.version,
                package_path=existing.package_path,
                package_hash=existing.package_hash,
                build_job_id=existing.build_job_id,
                worker_invocation_id=existing.worker_invocation_id,
                verification_spec_hash=existing.verification_spec_hash,
                verification_result_hash=existing.verification_result_hash,
                artifact_manifest_hash=existing.artifact_manifest_hash,
                verifier_version=existing.verifier_version,
                approval_status=approval_status or existing.approval_status,
                review_status=existing.review_status,
                created_at=existing.created_at,
                provenance=ensure_json_compatible(provenance),  # type: ignore[arg-type]
                quarantine_status=quarantine_status or existing.quarantine_status,
            )
            updated.validate()
            entries[index] = updated
            self._write_entries(entries)
            return updated

    def _load_entries(self) -> list[RegistryEntry]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RegistryError(f"registry store is invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise RegistryError("registry store must be a JSON object")
        entries_payload = payload.get("entries", [])
        if not isinstance(entries_payload, list):
            raise RegistryError("registry store entries must be a list")
        entries: list[RegistryEntry] = []
        for index, item in enumerate(entries_payload):
            try:
                entries.append(RegistryEntry.from_dict(item))
            except SchemaValidationError as exc:
                raise RegistryError(f"registry store entry {index} is invalid: {exc}") from exc
        return sorted(entries, key=_entry_sort_key)

    def _write_entries(self, entries: list[RegistryEntry]) -> None:
        if not self._lock_held():
            with self._locked_store():
                self._write_entries(entries)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sorted_entries = sorted(entries, key=_entry_sort_key)
        payload = {
            "schema_version": REGISTRY_STORE_VERSION,
            "duplicate_policy": self.duplicate_policy.value,
            "entries": [entry.to_dict() for entry in sorted_entries],
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        tmp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(self.path)

    @contextmanager
    def _locked_store(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        resolved_lock_path = lock_path.resolve(strict=False)
        thread_lock = _registry_thread_lock(lock_path)
        with thread_lock:
            with lock_path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                _mark_registry_lock_held(resolved_lock_path)
                try:
                    yield
                finally:
                    _unmark_registry_lock_held(resolved_lock_path)
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _lock_held(self) -> bool:
        lock_path = self.path.with_name(f".{self.path.name}.lock").resolve(strict=False)
        return lock_path in _current_registry_locks()


def _build_verified_entry(
    workspace: JobWorkspace,
    *,
    skill_id: str | None,
    version: str,
    review_status: str,
) -> RegistryEntry:
    failures: list[str] = []
    _require_non_empty(version, "version")
    _require_non_empty(review_status, "review_status")

    resolved_skill_id = skill_id
    if resolved_skill_id is None:
        try:
            resolved_skill_id = SkillSpec.read_yaml_file(
                workspace.resolve_path("skill_spec.yaml", must_exist=True)
            ).skill_id
        except Exception as exc:
            failures.append(f"skill_spec: cannot derive skill_id: {exc}")
    if resolved_skill_id is not None:
        try:
            _require_non_empty(resolved_skill_id, "skill_id")
        except RegistryGateError as exc:
            failures.extend(exc.failures)

    result = _read_verification_result_for_registration(workspace, failures)
    package_hash = _package_hash_for_registration(workspace, result, failures)
    verification_spec_hash = _verification_spec_hash_for_registration(workspace, result, failures)
    artifact_manifest_hash = _artifact_manifest_hash_for_registration(workspace, failures)
    execution_report, execution_report_ref = _execution_report_for_registration(workspace, result, failures)
    worker_invocation = _worker_invocation_for_registration(workspace, execution_report, failures)

    if failures:
        raise RegistryGateError(failures)

    assert resolved_skill_id is not None
    assert result is not None
    assert package_hash is not None
    assert verification_spec_hash is not None
    assert artifact_manifest_hash is not None
    assert execution_report is not None
    assert execution_report_ref is not None
    assert worker_invocation is not None

    verification_result_ref = "verifier/verification_result.json"
    verification_result_hash = sha256_file(workspace.resolve_path(verification_result_ref, must_exist=True))
    artifact_manifest_ref = "artifact_manifest.json"
    verification_spec_ref = "verification_spec.yaml"
    input_manifest_ref = f"attempts/{execution_report.attempt_id}/input_manifest.json"
    input_manifest_path = workspace.resolve_path(input_manifest_ref, must_exist=True)
    execution_report_hash = sha256_file(workspace.resolve_path(execution_report_ref, must_exist=True))

    provenance = ensure_json_compatible(
        {
            "schema_version": REGISTRY_PROVENANCE_VERSION,
            "workspace_root": workspace.root.resolve(strict=True).as_posix(),
            "build_job_id": workspace.job_id,
            "package": {
                "ref": "package",
                "path": workspace.resolve_path("package", must_exist=True).as_posix(),
                "sha256": package_hash,
            },
            "artifact_manifest": {
                "ref": artifact_manifest_ref,
                "sha256": artifact_manifest_hash,
            },
            "verification_spec": {
                "ref": verification_spec_ref,
                "sha256": verification_spec_hash,
            },
            "verification_result": {
                "ref": verification_result_ref,
                "result_id": result.result_id,
                "sha256": verification_result_hash,
                "passed": result.passed,
            },
            "execution_report": {
                "ref": execution_report_ref,
                "report_id": execution_report.report_id,
                "attempt_id": execution_report.attempt_id,
                "status": execution_report.status,
                "exit_status": execution_report.exit_status,
                "sha256": execution_report_hash,
            },
            "worker_invocation": {
                "invocation_id": execution_report.invocation_id,
                "attempt_id": execution_report.attempt_id,
                "input_manifest_ref": input_manifest_ref,
                "input_manifest_hash": sha256_file(input_manifest_path),
                **worker_invocation,
            },
            "verifier": {
                "version": result.verifier_version,
            },
        }
    )

    entry = RegistryEntry(
        skill_id=resolved_skill_id,
        version=version,
        package_path=workspace.resolve_path("package", must_exist=True).as_posix(),
        package_hash=package_hash,
        build_job_id=workspace.job_id,
        worker_invocation_id=execution_report.invocation_id,
        verification_spec_hash=verification_spec_hash,
        verification_result_hash=verification_result_hash,
        artifact_manifest_hash=artifact_manifest_hash,
        verifier_version=result.verifier_version,
        approval_status=APPROVAL_APPROVED,
        review_status=review_status,
        created_at=utc_now(),
        provenance=provenance,  # type: ignore[arg-type]
        quarantine_status=QUARANTINE_NONE,
    )
    entry.validate()
    return entry


def _registry_thread_lock(lock_path: Path) -> threading.RLock:
    resolved = lock_path.resolve(strict=False)
    with _REGISTRY_THREAD_LOCKS_GUARD:
        lock = _REGISTRY_THREAD_LOCKS.get(resolved)
        if lock is None:
            lock = threading.RLock()
            _REGISTRY_THREAD_LOCKS[resolved] = lock
        return lock


def _current_registry_locks() -> set[Path]:
    held = getattr(_REGISTRY_LOCK_STATE, "held", None)
    if not isinstance(held, set):
        held = set()
        _REGISTRY_LOCK_STATE.held = held
    return held


def _mark_registry_lock_held(lock_path: Path) -> None:
    _current_registry_locks().add(lock_path)


def _unmark_registry_lock_held(lock_path: Path) -> None:
    _current_registry_locks().discard(lock_path)


def _read_verification_result_for_registration(
    workspace: JobWorkspace,
    failures: list[str],
) -> VerificationResult | None:
    result_ref = "verifier/verification_result.json"
    try:
        result = VerificationResult.read_json_file(workspace.resolve_path(result_ref, must_exist=True))
    except Exception as exc:
        failures.append(f"verification_result: missing or invalid: {exc}")
        return None

    if result.job_id != workspace.job_id:
        failures.append(f"verification_result.job_id: expected {workspace.job_id}, got {result.job_id}")
    if not result.passed:
        failures.append("verification_result.passed: verifier did not pass")
    if result.passed and result.failures:
        failures.append("verification_result.failures: passed result contains verifier failures")
    for index, check in enumerate(result.checks):
        if check.get("severity") == "error" and check.get("passed") is False:
            failures.append(f"verification_result.checks[{index}]: passed result contains a failed error check")
            break
    for required_ref in ("artifact_manifest.json", "verification_spec.yaml", "package"):
        if required_ref not in result.evidence_refs:
            failures.append(f"verification_result.evidence_refs: missing required ref {required_ref!r}")
    return result


def _package_hash_for_registration(
    workspace: JobWorkspace,
    result: VerificationResult | None,
    failures: list[str],
) -> str | None:
    try:
        package_dir = workspace.resolve_path("package", must_exist=True)
    except Exception as exc:
        failures.append(f"package: missing or unsafe: {exc}")
        return None
    package_hash, package_failures = _hash_package_dir(package_dir)
    failures.extend(f"package: {failure}" for failure in package_failures)
    if result is not None and result.package_hash != package_hash:
        failures.append(f"package_hash: verifier recorded {result.package_hash}, current package is {package_hash}")
    return package_hash


def _verification_spec_hash_for_registration(
    workspace: JobWorkspace,
    result: VerificationResult | None,
    failures: list[str],
) -> str | None:
    try:
        verification_spec_hash = sha256_file(workspace.resolve_path("verification_spec.yaml", must_exist=True))
    except Exception as exc:
        failures.append(f"verification_spec: missing or unsafe: {exc}")
        return None
    if result is not None and result.verification_spec_hash != verification_spec_hash:
        failures.append(
            f"verification_spec_hash: verifier recorded {result.verification_spec_hash}, "
            f"current spec is {verification_spec_hash}"
        )
    return verification_spec_hash


def _artifact_manifest_hash_for_registration(workspace: JobWorkspace, failures: list[str]) -> str | None:
    try:
        manifest_path = workspace.resolve_path("artifact_manifest.json", must_exist=True)
        manifest = ArtifactManifest.read_json_file(manifest_path)
    except Exception as exc:
        failures.append(f"artifact_manifest: missing or invalid: {exc}")
        return None
    _check_manifest_against_workspace(manifest, workspace, failures)
    return sha256_file(manifest_path)


def _execution_report_for_registration(
    workspace: JobWorkspace,
    result: VerificationResult | None,
    failures: list[str],
) -> tuple[ExecutionReport | None, str | None]:
    report_ref = _execution_report_ref_from_result(result) if result is not None else None
    if result is not None and report_ref is None:
        failures.append("verification_result.evidence_refs: missing attempt execution report ref")
        return None, None
    if result is None:
        report_ref = _latest_execution_report_ref(workspace)
    if report_ref is None:
        failures.append("execution_report: cannot derive latest execution report")
        return None, None
    try:
        report = ExecutionReport.read_json_file(workspace.resolve_path(report_ref, must_exist=True))
    except Exception as exc:
        failures.append(f"execution_report: missing or invalid: {exc}")
        return None, report_ref

    if report.job_id != workspace.job_id:
        failures.append(f"execution_report.job_id: expected {workspace.job_id}, got {report.job_id}")
    if report.status != "completed" or report.exit_status != "success":
        failures.append(
            f"execution_report_success: expected completed/success, got {report.status}/{report.exit_status}"
        )
    if not report.invocation_id.strip():
        failures.append("execution_report.invocation_id: missing worker invocation id")
    return report, report_ref


def _worker_invocation_for_registration(
    workspace: JobWorkspace,
    report: ExecutionReport | None,
    failures: list[str],
) -> dict[str, JsonValue] | None:
    if report is None:
        return None
    input_manifest_ref = f"attempts/{report.attempt_id}/input_manifest.json"
    try:
        input_manifest_path = workspace.resolve_path(input_manifest_ref, must_exist=True)
        payload = json.loads(input_manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append(f"worker_input_manifest: missing or invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        failures.append("worker_input_manifest: expected JSON object")
        return None

    invocation_id = payload.get("invocation_id")
    if invocation_id != report.invocation_id:
        failures.append(
            f"worker_input_manifest.invocation_id: expected {report.invocation_id}, got {invocation_id!r}"
        )
    if payload.get("job_id") != report.job_id:
        failures.append(f"worker_input_manifest.job_id: expected {report.job_id}, got {payload.get('job_id')!r}")
    if payload.get("attempt_id") != report.attempt_id:
        failures.append(
            f"worker_input_manifest.attempt_id: expected {report.attempt_id}, got {payload.get('attempt_id')!r}"
        )

    return ensure_json_compatible(
        {
            "worker_type": payload.get("worker_type"),
            "adapter_version": payload.get("adapter_version"),
            "build_contract_ref": payload.get("build_contract_ref"),
            "worker_input_ref": payload.get("worker_input_ref"),
        }
    )  # type: ignore[return-value]


def _workspace_root_for_entry(entry: RegistryEntry, failures: list[str]) -> Path | None:
    root_value = entry.provenance.get("workspace_root")
    if isinstance(root_value, str) and root_value.strip():
        root = Path(root_value)
    else:
        package_path = Path(entry.package_path)
        if package_path.is_absolute() and package_path.name == "package":
            root = package_path.parent
        else:
            failures.append("provenance.workspace_root: missing and package_path is not an absolute package path")
            return None
    try:
        return root.resolve(strict=True)
    except Exception as exc:
        failures.append(f"workspace_root: missing or inaccessible: {exc}")
        return None


def _package_dir_for_entry(
    entry: RegistryEntry,
    workspace_root: Path | None,
    failures: list[str],
) -> Path | None:
    package_path = Path(entry.package_path)
    if not package_path.is_absolute():
        if workspace_root is None:
            failures.append("package_path: relative path cannot be resolved without workspace_root")
            return None
        package_path = workspace_root / package_path
    try:
        resolved = package_path.resolve(strict=True)
    except Exception as exc:
        failures.append(f"package_path: missing or inaccessible: {exc}")
        return None
    if workspace_root is not None:
        try:
            assert_under_root(workspace_root, resolved)
        except PathSecurityError as exc:
            failures.append(f"package_path: {exc}")
            return None
    if not resolved.is_dir():
        failures.append("package_path: expected a directory")
        return None
    return resolved


def _artifact_path_from_entry(
    entry: RegistryEntry,
    workspace_root: Path | None,
    provenance_path: tuple[str, str],
    failures: list[str],
) -> Path | None:
    if workspace_root is None:
        failures.append(f"{provenance_path[0]}: cannot resolve without workspace_root")
        return None
    ref = _nested_str(entry.provenance, provenance_path)
    if ref is None:
        ref = _default_ref_for_provenance(provenance_path[0])
    try:
        return resolve_under_root(workspace_root, ref, must_exist=True)
    except Exception as exc:
        failures.append(f"{provenance_path[0]}: missing or unsafe ref {ref!r}: {exc}")
        return None


def _default_ref_for_provenance(name: str) -> str:
    defaults = {
        "artifact_manifest": "artifact_manifest.json",
        "verification_result": "verifier/verification_result.json",
        "verification_spec": "verification_spec.yaml",
        "execution_report": "",
    }
    value = defaults.get(name)
    if value is None or not value:
        raise RegistryError(f"provenance.{name}.ref is required")
    return value


def _hash_file_or_failure(path: Path, field_name: str, failures: list[str]) -> str | None:
    try:
        if not path.is_file():
            failures.append(f"{field_name}: expected a file")
            return None
        return sha256_file(path)
    except Exception as exc:
        failures.append(f"{field_name}: cannot hash file: {exc}")
        return None


def _check_result_against_entry(
    result: VerificationResult,
    entry: RegistryEntry,
    failures: list[str],
) -> None:
    if not result.passed:
        failures.append("verification_result.passed: verifier did not pass")
    if result.job_id != entry.build_job_id:
        failures.append(f"verification_result.job_id: expected {entry.build_job_id}, got {result.job_id}")
    if result.package_hash != entry.package_hash:
        failures.append(f"verification_result.package_hash: expected {entry.package_hash}, got {result.package_hash}")
    if result.verification_spec_hash != entry.verification_spec_hash:
        failures.append(
            f"verification_result.verification_spec_hash: expected {entry.verification_spec_hash}, "
            f"got {result.verification_spec_hash}"
        )
    if result.verifier_version != entry.verifier_version:
        failures.append(f"verification_result.verifier_version: expected {entry.verifier_version}, got {result.verifier_version}")
    if result.passed and result.failures:
        failures.append("verification_result.failures: passed result contains failures")
    for index, check in enumerate(result.checks):
        if check.get("severity") == "error" and check.get("passed") is False:
            failures.append(f"verification_result.checks[{index}]: passed result contains a failed error check")
            break


def _check_manifest_against_entry(
    manifest: ArtifactManifest,
    entry: RegistryEntry,
    workspace_root: Path | None,
    failures: list[str],
) -> None:
    if manifest.job_id != entry.build_job_id:
        failures.append(f"artifact_manifest.job_id: expected {entry.build_job_id}, got {manifest.job_id}")
    if workspace_root is None:
        return
    _check_manifest_records(manifest, workspace_root, failures)


def _check_manifest_against_workspace(
    manifest: ArtifactManifest,
    workspace: JobWorkspace,
    failures: list[str],
) -> None:
    if manifest.job_id != workspace.job_id:
        failures.append(f"artifact_manifest.job_id: expected {workspace.job_id}, got {manifest.job_id}")
    _check_manifest_records(manifest, workspace.root.resolve(), failures)


def _check_manifest_records(manifest: ArtifactManifest, workspace_root: Path, failures: list[str]) -> None:
    seen_paths: set[str] = set()
    for record in manifest.artifacts:
        if record.path in seen_paths:
            failures.append(f"artifact_manifest: duplicate path {record.path}")
            continue
        seen_paths.add(record.path)
        try:
            artifact_path = resolve_under_root(workspace_root, record.path, must_exist=True)
        except Exception as exc:
            failures.append(f"artifact_manifest.{record.path}: missing or unsafe: {exc}")
            continue
        if not artifact_path.is_file():
            failures.append(f"artifact_manifest.{record.path}: expected a file")
            continue
        actual_hash = sha256_file(artifact_path)
        if actual_hash != record.sha256:
            failures.append(f"artifact_manifest.{record.path}: expected {record.sha256}, got {actual_hash}")


def _check_execution_report_against_entry(
    report: ExecutionReport,
    entry: RegistryEntry,
    failures: list[str],
) -> None:
    if report.job_id != entry.build_job_id:
        failures.append(f"execution_report.job_id: expected {entry.build_job_id}, got {report.job_id}")
    if report.invocation_id != entry.worker_invocation_id:
        failures.append(
            f"execution_report.invocation_id: expected {entry.worker_invocation_id}, got {report.invocation_id}"
        )
    if report.status != "completed" or report.exit_status != "success":
        failures.append(f"execution_report_success: expected completed/success, got {report.status}/{report.exit_status}")
    expected_report_id = _nested_str(entry.provenance, ("execution_report", "report_id"))
    if expected_report_id is not None and report.report_id != expected_report_id:
        failures.append(f"execution_report.report_id: expected {expected_report_id}, got {report.report_id}")


def _check_input_manifest_against_entry(
    entry: RegistryEntry,
    workspace_root: Path | None,
    report: ExecutionReport,
    failures: list[str],
) -> None:
    if workspace_root is None:
        return
    ref = _nested_str(entry.provenance, ("worker_invocation", "input_manifest_ref"))
    if ref is None:
        ref = f"attempts/{report.attempt_id}/input_manifest.json"
    try:
        path = resolve_under_root(workspace_root, ref, must_exist=True)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append(f"worker_input_manifest: missing or invalid: {exc}")
        return
    if not isinstance(payload, dict):
        failures.append("worker_input_manifest: expected JSON object")
        return
    if payload.get("invocation_id") != entry.worker_invocation_id:
        failures.append(
            f"worker_input_manifest.invocation_id: expected {entry.worker_invocation_id}, "
            f"got {payload.get('invocation_id')!r}"
        )
    input_manifest_hash = _nested_str(entry.provenance, ("worker_invocation", "input_manifest_hash"))
    if input_manifest_hash is not None:
        actual_hash = sha256_file(path)
        if actual_hash != input_manifest_hash:
            failures.append(f"worker_input_manifest_hash: expected {input_manifest_hash}, got {actual_hash}")


def _hash_package_dir(package_dir: Path) -> tuple[str, list[str]]:
    entries: list[dict[str, JsonValue]] = []
    failures: list[str] = []
    try:
        package_root = package_dir.resolve(strict=True)
    except Exception as exc:
        return sha256_json({"package": "missing", "error": str(exc)}), [str(exc)]

    for path in sorted(package_root.rglob("*")):
        try:
            relative = path.relative_to(package_root).as_posix()
            validate_relative_path(relative)
        except Exception as exc:
            failures.append(f"{path}: {exc}")
            continue

        if path.is_symlink():
            entries.append({"path": relative, "kind": "symlink", "target": str(path.readlink())})
            failures.append(f"{relative}: symlink components are not allowed")
        elif path.is_file():
            entries.append({"path": relative, "kind": "file", "sha256": sha256_file(path), "size": path.stat().st_size})
        elif path.is_dir():
            entries.append({"path": relative, "kind": "dir"})
        else:
            entries.append({"path": relative, "kind": "other"})
            failures.append(f"{relative}: unsupported package path type")
    return sha256_json(entries), failures


def _execution_report_ref_from_result(result: VerificationResult | None) -> str | None:
    if result is None:
        return None
    for ref in result.evidence_refs:
        if _EXECUTION_REPORT_RE.fullmatch(ref):
            return ref
    return None


def _latest_execution_report_ref(workspace: JobWorkspace) -> str | None:
    try:
        attempts_dir = workspace.resolve_path("attempts", must_exist=True)
    except Exception:
        return None
    candidates: list[tuple[int, str]] = []
    for child in attempts_dir.iterdir():
        if not child.is_dir() or not child.name.isdecimal():
            continue
        report = child / "execution_report.json"
        if report.exists():
            candidates.append((int(child.name), f"attempts/{child.name}/execution_report.json"))
    if not candidates:
        return None
    return sorted(candidates)[-1][1]


def _nested_str(payload: Mapping[str, Any], path: tuple[str, str]) -> str | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    if isinstance(current, str) and current.strip():
        return current
    return None


def _find_entry(entries: list[RegistryEntry], skill_id: str, version: str) -> RegistryEntry | None:
    _, entry = _find_entry_with_index(entries, skill_id, version)
    return entry


def _find_entry_with_index(
    entries: list[RegistryEntry],
    skill_id: str,
    version: str,
) -> tuple[int | None, RegistryEntry | None]:
    for index, entry in enumerate(entries):
        if entry.skill_id == skill_id and entry.version == version:
            return index, entry
    return None, None


def _same_registered_asset(left: RegistryEntry, right: RegistryEntry) -> bool:
    return (
        left.skill_id == right.skill_id
        and left.version == right.version
        and left.package_hash == right.package_hash
        and left.build_job_id == right.build_job_id
        and left.worker_invocation_id == right.worker_invocation_id
        and left.verification_spec_hash == right.verification_spec_hash
        and left.verification_result_hash == right.verification_result_hash
        and left.artifact_manifest_hash == right.artifact_manifest_hash
        and left.verifier_version == right.verifier_version
    )


def _entry_sort_key(entry: RegistryEntry) -> tuple[str, str]:
    return (entry.skill_id, entry.version)


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RegistryGateError([f"{field_name}: must be a non-empty string"])


__all__ = [
    "APPROVAL_APPROVED",
    "APPROVAL_REJECTED",
    "DEFAULT_REGISTRY_VERSION",
    "DuplicatePolicy",
    "LocalSkillRegistry",
    "QUARANTINE_NONE",
    "QUARANTINE_QUARANTINED",
    "REGISTRY_PROVENANCE_VERSION",
    "REGISTRY_STORE_VERSION",
    "RegistryDuplicateError",
    "RegistryEntryNotFound",
    "RegistryError",
    "RegistryGateError",
    "RegistryVerificationReport",
]
