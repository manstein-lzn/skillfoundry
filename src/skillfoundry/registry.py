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

from contextforge import VerificationResult as ContextForgeVerificationResult

from .acceptance import ACCEPTANCE_COVERAGE_RESULT_REF, MANUAL_ACCEPTANCE_RECORD_REF
from .product_contract import PRODUCT_GRADE_REPORT_REF, PRODUCT_REPAIR_PACKET_REF, ProductGradeReport
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
from .verification_bridge import (
    CONTEXTFORGE_VERIFICATION_RESULT_REF,
    SKILLFOUNDRY_VERIFICATION_RESULT_REF,
    VERIFICATION_BRIDGE_VERSION,
)
from .workspace import JobWorkspace


REGISTRY_STORE_VERSION = "skillfoundry.local_registry.v1"
REGISTRY_PROVENANCE_VERSION = "skillfoundry.registry_provenance.v1"
DEFAULT_REGISTRY_VERSION = "0.1.0"

APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
QUARANTINE_NONE = "none"
QUARANTINE_QUARANTINED = "quarantined"
REGISTRY_STATUS_REGISTERED = "registered"
REGISTRY_STATUS_GENERATED = "generated"
REGISTRY_STATUS_VERIFIED = "verified"
REGISTRY_STATUS_CANDIDATE_REGISTERED = "candidate_registered"
REGISTRY_STATUS_PRODUCT_GRADE_REGISTERED = "product_grade_registered"
REGISTRY_STATUS_PUBLISHED = "published"
REGISTRY_STATUS_DEPRECATED = "deprecated"
REGISTRY_STATUSES = frozenset(
    {
        REGISTRY_STATUS_REGISTERED,
        REGISTRY_STATUS_GENERATED,
        REGISTRY_STATUS_VERIFIED,
        REGISTRY_STATUS_CANDIDATE_REGISTERED,
        REGISTRY_STATUS_PRODUCT_GRADE_REGISTERED,
        REGISTRY_STATUS_PUBLISHED,
        REGISTRY_STATUS_DEPRECATED,
        QUARANTINE_QUARANTINED,
    }
)

_EXECUTION_REPORT_RE = re.compile(r"^attempts/(?P<attempt_id>[0-9]+)/execution_report\.json$")
_REGISTRY_THREAD_LOCKS: dict[Path, threading.RLock] = {}
_REGISTRY_THREAD_LOCKS_GUARD = threading.Lock()
_REGISTRY_LOCK_STATE = threading.local()
_SHA256_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED_CONTEXTFORGE_BRIDGE_VALIDATORS = (
    "skillfoundry_verification_result_present",
    "acceptance_coverage_result_present",
    "verification_gate_hash_self_consistent",
    "verification_gate_hash_current",
    "verification_gate_required_evidence_present",
    "skillfoundry_verifier_passed",
    "skillfoundry_verifier_fresh_for_workspace",
    "acceptance_coverage_passed",
    "acceptance_coverage_fresh",
    "worker_self_report_not_acceptance",
    "contextforge_gate_metric_gates_supported",
    "contextforge_gate_runner_completed",
)


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
        require_contextforge_verification: bool = False,
    ) -> RegistryEntry:
        """Register a verifier-approved package as a candidate delivery."""

        entry = _build_verified_entry(
            workspace,
            skill_id=skill_id,
            version=version,
            review_status=review_status,
            require_contextforge_verification=require_contextforge_verification,
            require_product_grade=False,
        )
        return self._add_entry(entry)

    def add_candidate(
        self,
        workspace: JobWorkspace,
        *,
        skill_id: str | None = None,
        version: str = DEFAULT_REGISTRY_VERSION,
        review_status: str = "not_reviewed",
        require_contextforge_verification: bool = False,
    ) -> RegistryEntry:
        """Explicit alias for candidate registration."""

        return self.add_verified(
            workspace,
            skill_id=skill_id,
            version=version,
            review_status=review_status,
            require_contextforge_verification=require_contextforge_verification,
        )

    def add_product_grade(
        self,
        workspace: JobWorkspace,
        *,
        skill_id: str | None = None,
        version: str = DEFAULT_REGISTRY_VERSION,
        review_status: str = "product_grade_reviewed",
        require_contextforge_verification: bool = False,
    ) -> RegistryEntry:
        """Register only after verifier gates and ProductGradeGate have passed."""

        entry = _build_verified_entry(
            workspace,
            skill_id=skill_id,
            version=version,
            review_status=review_status,
            require_contextforge_verification=require_contextforge_verification,
            require_product_grade=True,
        )
        return self._add_entry(entry)

    def _add_entry(self, entry: RegistryEntry) -> RegistryEntry:
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
        registry_status: str | None = None,
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

        if registry_status is not None and registry_status != "all":
            result = [entry for entry in result if _entry_registry_status(entry) == registry_status]

        if not include_quarantined and status != QUARANTINE_QUARANTINED:
            result = [entry for entry in result if entry.quarantine_status != QUARANTINE_QUARANTINED]
        return sorted(result, key=_entry_sort_key)

    def product_grade_entries(self, *, include_quarantined: bool = False) -> list[RegistryEntry]:
        """Return approved product-grade entries."""

        return self.list(
            status=APPROVAL_APPROVED,
            registry_status=REGISTRY_STATUS_PRODUCT_GRADE_REGISTERED,
            include_quarantined=include_quarantined,
        )

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
        registry_status = _entry_registry_status(entry)
        if registry_status not in REGISTRY_STATUSES:
            allowed = ", ".join(sorted(REGISTRY_STATUSES))
            failures.append(f"registry_status: expected one of {allowed}, got {registry_status!r}")

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

        _check_acceptance_coverage_against_entry(entry, workspace_root, failures)
        _check_contextforge_verification_against_entry(entry, workspace_root, failures)
        _check_product_grade_against_entry(entry, workspace_root, failures)

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
    require_contextforge_verification: bool,
    require_product_grade: bool,
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
    acceptance_coverage = _acceptance_coverage_for_registration(workspace, failures)
    contextforge_verification = _contextforge_verification_for_registration(
        workspace,
        result,
        package_hash,
        acceptance_coverage,
        failures,
        required=require_contextforge_verification,
    )
    product_grade_report = _product_grade_for_registration(
        workspace,
        package_hash,
        failures,
        required=require_product_grade,
    )

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
            "registry_status": REGISTRY_STATUS_PRODUCT_GRADE_REGISTERED
            if require_product_grade
            else REGISTRY_STATUS_CANDIDATE_REGISTERED,
            "product_grade_required": require_product_grade,
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
    if acceptance_coverage is not None:
        provenance["acceptance_coverage_result"] = acceptance_coverage
    if contextforge_verification is not None:
        provenance["contextforge_verification_result"] = contextforge_verification
    if product_grade_report is not None:
        provenance["product_grade_report"] = product_grade_report

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
            "task_contract_ref": payload.get("task_contract_ref"),
        }
    )  # type: ignore[return-value]


def _acceptance_coverage_for_registration(
    workspace: JobWorkspace,
    failures: list[str],
) -> dict[str, JsonValue] | None:
    if not _workspace_has_root_acceptance_criteria(workspace):
        return None

    ref = ACCEPTANCE_COVERAGE_RESULT_REF
    try:
        path = workspace.resolve_path(ref, must_exist=True)
    except Exception as exc:
        failures.append(f"acceptance_coverage_result: missing or unsafe: {exc}")
        return None

    digest = sha256_file(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append(f"acceptance_coverage_result: invalid JSON: {exc}")
        return None
    if not isinstance(payload, dict):
        failures.append("acceptance_coverage_result: expected JSON object")
        return None

    if payload.get("passed") is not True:
        failures.append("acceptance_coverage_result.passed: acceptance coverage did not pass")
    result_id = payload.get("result_id")
    if not isinstance(result_id, str) or not result_id.strip():
        failures.append("acceptance_coverage_result.result_id: missing")
        result_id = None

    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}

    return ensure_json_compatible(
        {
            "ref": ref,
            "result_id": result_id,
            "sha256": digest,
            "passed": payload.get("passed") is True,
            "provenance": _acceptance_coverage_provenance_refs(provenance),
        }
    )  # type: ignore[return-value]


def _contextforge_verification_for_registration(
    workspace: JobWorkspace,
    skillfoundry_result: VerificationResult | None,
    package_hash: str | None,
    acceptance_coverage: Mapping[str, JsonValue] | None,
    failures: list[str],
    *,
    required: bool,
) -> dict[str, JsonValue] | None:
    ref = CONTEXTFORGE_VERIFICATION_RESULT_REF
    try:
        path = workspace.resolve_path(ref, must_exist=True)
    except Exception as exc:
        if required:
            failures.append(f"contextforge_verification_result: missing or unsafe: {exc}")
        return None

    digest = sha256_file(path)
    try:
        result = ContextForgeVerificationResult.from_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        if required:
            failures.append(f"contextforge_verification_result: missing or invalid: {exc}")
        return None

    contextforge_failures: list[str] = []
    _check_contextforge_result_for_registration(
        result,
        workspace,
        skillfoundry_result,
        package_hash,
        acceptance_coverage,
        contextforge_failures,
    )
    if contextforge_failures:
        if required:
            failures.extend(contextforge_failures)
        return None

    return ensure_json_compatible(
        {
            "ref": ref,
            "verification_result_id": result.verification_result_id,
            "verification_gate_id": result.verification_gate_id,
            "goal_id": result.goal_id,
            "goal_run_id": result.goal_run_id,
            "status": result.status,
            "passed": result.passed,
            "sha256": digest,
            "verification_gate_hash": _json_str(result.metadata.get("verification_gate_hash")),
            "skillfoundry_verification_result_hash": _json_str(
                result.metadata.get("skillfoundry_verification_result_hash")
            ),
            "acceptance_coverage_result_hash": _json_str(result.metadata.get("acceptance_coverage_result_hash")),
            "current_package_hash": _json_str(result.metadata.get("current_package_hash")),
        }
    )  # type: ignore[return-value]


def _product_grade_for_registration(
    workspace: JobWorkspace,
    package_hash: str | None,
    failures: list[str],
    *,
    required: bool,
) -> dict[str, JsonValue] | None:
    ref = PRODUCT_GRADE_REPORT_REF
    try:
        path = workspace.resolve_path(ref, must_exist=True)
    except Exception as exc:
        if required:
            failures.append(f"product_grade_report: missing or unsafe: {exc}")
        return None

    local_failures: list[str] = []
    digest = sha256_file(path)
    try:
        report = ProductGradeReport.read_json_file(path)
    except Exception as exc:
        if required:
            failures.append(f"product_grade_report: missing or invalid: {exc}")
        return None

    if report.job_id != workspace.job_id:
        local_failures.append(f"product_grade_report.job_id: expected {workspace.job_id}, got {report.job_id}")
    if package_hash is not None and report.package_hash != package_hash:
        local_failures.append(
            f"product_grade_report.package_hash: expected {package_hash}, got {report.package_hash}"
        )
    if required and report.product_grade is not True:
        local_failures.append("product_grade_report.product_grade: ProductGradeGate did not pass")

    if local_failures:
        if required:
            failures.extend(local_failures)
        return None

    repair_packet = _product_repair_packet_for_registration(workspace)
    payload: dict[str, JsonValue] = {
        "ref": ref,
        "sha256": digest,
        "product_grade": report.product_grade,
        "gate_version": report.gate_version,
        "checked_item_ids": list(report.checked_item_ids),
        "finding_ids": [finding.finding_id for finding in report.findings],
    }
    if repair_packet is not None:
        payload["repair_packet"] = repair_packet
    return ensure_json_compatible(payload)  # type: ignore[return-value]


def _product_repair_packet_for_registration(workspace: JobWorkspace) -> dict[str, JsonValue] | None:
    ref = PRODUCT_REPAIR_PACKET_REF
    try:
        path = workspace.resolve_path(ref, must_exist=True)
    except Exception:
        return None
    return ensure_json_compatible(
        {
            "ref": ref,
            "sha256": sha256_file(path),
        }
    )  # type: ignore[return-value]


def _check_contextforge_result_for_registration(
    result: ContextForgeVerificationResult,
    workspace: JobWorkspace,
    skillfoundry_result: VerificationResult | None,
    package_hash: str | None,
    acceptance_coverage: Mapping[str, JsonValue] | None,
    failures: list[str],
) -> None:
    _check_contextforge_result_semantics(result, failures)
    if result.status != "passed" or not result.passed:
        failures.append(f"contextforge_verification_result.status: expected passed, got {result.status}")
    if result.metadata.get("job_id") != workspace.job_id:
        failures.append(
            f"contextforge_verification_result.metadata.job_id: expected {workspace.job_id}, "
            f"got {result.metadata.get('job_id')!r}"
        )
    if result.metadata.get("skillfoundry_verification_result_ref") not in {
        SKILLFOUNDRY_VERIFICATION_RESULT_REF,
    }:
        failures.append("contextforge_verification_result.metadata.skillfoundry_verification_result_ref: mismatch")

    expected_verifier_hash = _hash_workspace_ref_or_none(workspace, SKILLFOUNDRY_VERIFICATION_RESULT_REF)
    recorded_verifier_hash = result.metadata.get("skillfoundry_verification_result_hash")
    if expected_verifier_hash is not None and recorded_verifier_hash != expected_verifier_hash:
        failures.append(
            "contextforge_verification_result.skillfoundry_verification_result_hash: "
            f"expected {expected_verifier_hash}, got {recorded_verifier_hash!r}"
        )
    recorded_package_hash = result.metadata.get("current_package_hash")
    if package_hash is not None and recorded_package_hash != package_hash:
        failures.append(
            f"contextforge_verification_result.current_package_hash: expected {package_hash}, "
            f"got {recorded_package_hash!r}"
        )

    coverage_hash = _json_str(acceptance_coverage.get("sha256")) if acceptance_coverage is not None else None
    recorded_coverage_hash = result.metadata.get("acceptance_coverage_result_hash")
    if coverage_hash is not None and recorded_coverage_hash != coverage_hash:
        failures.append(
            "contextforge_verification_result.acceptance_coverage_result_hash: "
            f"expected {coverage_hash}, got {recorded_coverage_hash!r}"
        )


def _check_contextforge_result_semantics(
    result: ContextForgeVerificationResult,
    failures: list[str],
) -> None:
    if result.metadata.get("bridge") != VERIFICATION_BRIDGE_VERSION:
        failures.append(
            "contextforge_verification_result.metadata.bridge: "
            f"expected {VERIFICATION_BRIDGE_VERSION}, got {result.metadata.get('bridge')!r}"
        )
    gate_hash = _json_str(result.metadata.get("verification_gate_hash"))
    if gate_hash is None or not _SHA256_REF_RE.fullmatch(gate_hash):
        failures.append("contextforge_verification_result.verification_gate_hash: missing or invalid")

    for validator_id in _REQUIRED_CONTEXTFORGE_BRIDGE_VALIDATORS:
        if not _contextforge_validator_passed(result, validator_id):
            failures.append(
                "contextforge_verification_result.validator_results: "
                f"missing passed bridge validator {validator_id!r}"
            )

    runner_result = _contextforge_validator(result, "contextforge_gate_runner_completed")
    if runner_result is not None:
        if runner_result.evidence.get("status") != "passed" or runner_result.evidence.get("passed") is not True:
            failures.append(
                "contextforge_verification_result.contextforge_gate_runner_completed: "
                "runner evidence did not record passed status"
            )

    for index, validator in enumerate(result.validator_results):
        if validator.severity == "blocking" and not validator.passed:
            failures.append(
                "contextforge_verification_result.validator_results"
                f"[{index}]: blocking validator {validator.validator_id!r} did not pass"
            )
            break


def _contextforge_validator(
    result: ContextForgeVerificationResult,
    validator_id: str,
):
    return next((item for item in result.validator_results if item.validator_id == validator_id), None)


def _contextforge_validator_passed(result: ContextForgeVerificationResult, validator_id: str) -> bool:
    return any(item.validator_id == validator_id and item.passed for item in result.validator_results)


def _workspace_has_root_acceptance_criteria(workspace: JobWorkspace) -> bool:
    try:
        return workspace.resolve_path("acceptance_criteria.yaml").is_file()
    except Exception:
        return False


def _workspace_root_has_acceptance_criteria(workspace_root: Path | None) -> bool:
    if workspace_root is None:
        return False
    try:
        criteria_path = resolve_under_root(workspace_root, "acceptance_criteria.yaml", must_exist=False)
    except Exception:
        return False
    return criteria_path.is_file()


def _acceptance_coverage_provenance_refs(provenance: Mapping[str, Any]) -> dict[str, JsonValue]:
    refs: dict[str, JsonValue] = {}
    for key in (
        "acceptance_criteria",
        "coverage_plan",
        "qa_report",
        "verification_result",
        "manual_acceptance_record",
        "package",
    ):
        value = provenance.get(key)
        if not isinstance(value, Mapping):
            continue
        refs[key] = ensure_json_compatible(
            {
                "ref": value.get("ref") if isinstance(value.get("ref"), str) else None,
                "sha256": value.get("sha256") if isinstance(value.get("sha256"), str) else None,
                "result_id": value.get("result_id") if isinstance(value.get("result_id"), str) else None,
                "plan_id": value.get("plan_id") if isinstance(value.get("plan_id"), str) else None,
                "passed": value.get("passed") if isinstance(value.get("passed"), bool) else None,
                "present": value.get("present") if isinstance(value.get("present"), bool) else None,
            }
        )  # type: ignore[assignment]
    return refs


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


def _check_acceptance_coverage_against_entry(
    entry: RegistryEntry,
    workspace_root: Path | None,
    failures: list[str],
) -> None:
    coverage_value = entry.provenance.get("acceptance_coverage_result")
    has_root_acceptance = _workspace_root_has_acceptance_criteria(workspace_root)
    if not has_root_acceptance and coverage_value is None:
        return
    if has_root_acceptance and not isinstance(coverage_value, Mapping):
        failures.append("acceptance_coverage_result: required when acceptance_criteria.yaml exists")
        return
    if not isinstance(coverage_value, Mapping):
        failures.append("acceptance_coverage_result: provenance must be a JSON object")
        return
    if workspace_root is None:
        failures.append("acceptance_coverage_result: cannot resolve without workspace_root")
        return

    ref = _nested_str(entry.provenance, ("acceptance_coverage_result", "ref")) or ACCEPTANCE_COVERAGE_RESULT_REF
    try:
        path = resolve_under_root(workspace_root, ref, must_exist=True)
    except Exception as exc:
        failures.append(f"acceptance_coverage_result: missing or unsafe ref {ref!r}: {exc}")
        return

    expected_hash = _nested_str(entry.provenance, ("acceptance_coverage_result", "sha256"))
    if expected_hash is None:
        failures.append("acceptance_coverage_result.sha256: missing from provenance")
    actual_hash = _hash_file_or_failure(path, "acceptance_coverage_result_hash", failures)
    if expected_hash is not None and actual_hash is not None and actual_hash != expected_hash:
        failures.append(f"acceptance_coverage_result_hash: expected {expected_hash}, got {actual_hash}")

    expected_passed = coverage_value.get("passed")
    if expected_passed is not True:
        failures.append("acceptance_coverage_result.passed: registry provenance does not record passed=true")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append(f"acceptance_coverage_result: invalid JSON: {exc}")
        return
    if not isinstance(payload, dict):
        failures.append("acceptance_coverage_result: expected JSON object")
        return
    if payload.get("passed") is not True:
        failures.append("acceptance_coverage_result.passed: acceptance coverage did not pass")
    expected_result_id = _nested_str(entry.provenance, ("acceptance_coverage_result", "result_id"))
    actual_result_id = payload.get("result_id")
    if expected_result_id is not None and actual_result_id != expected_result_id:
        failures.append(f"acceptance_coverage_result.result_id: expected {expected_result_id}, got {actual_result_id!r}")
    _check_manual_acceptance_record_against_coverage(entry, workspace_root, payload, failures)


def _check_contextforge_verification_against_entry(
    entry: RegistryEntry,
    workspace_root: Path | None,
    failures: list[str],
) -> None:
    contextforge_value = entry.provenance.get("contextforge_verification_result")
    if contextforge_value is None:
        return
    if not isinstance(contextforge_value, Mapping):
        failures.append("contextforge_verification_result: provenance must be a JSON object")
        return
    if workspace_root is None:
        failures.append("contextforge_verification_result: cannot resolve without workspace_root")
        return

    ref = _nested_str(entry.provenance, ("contextforge_verification_result", "ref"))
    if ref is None:
        failures.append("contextforge_verification_result.ref: missing from provenance")
        return
    try:
        path = resolve_under_root(workspace_root, ref, must_exist=True)
    except Exception as exc:
        failures.append(f"contextforge_verification_result: missing or unsafe ref {ref!r}: {exc}")
        return

    expected_hash = _nested_str(entry.provenance, ("contextforge_verification_result", "sha256"))
    if expected_hash is None:
        failures.append("contextforge_verification_result.sha256: missing from provenance")
    actual_hash = _hash_file_or_failure(path, "contextforge_verification_result_hash", failures)
    if expected_hash is not None and actual_hash is not None and actual_hash != expected_hash:
        failures.append(f"contextforge_verification_result_hash: expected {expected_hash}, got {actual_hash}")

    try:
        result = ContextForgeVerificationResult.from_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append(f"contextforge_verification_result: missing or invalid: {exc}")
        return

    _check_contextforge_result_semantics(result, failures)

    expected_result_id = _nested_str(
        entry.provenance,
        ("contextforge_verification_result", "verification_result_id"),
    )
    if expected_result_id is not None and result.verification_result_id != expected_result_id:
        failures.append(
            "contextforge_verification_result.verification_result_id: "
            f"expected {expected_result_id}, got {result.verification_result_id}"
        )
    if result.status != "passed" or not result.passed:
        failures.append(f"contextforge_verification_result.status: expected passed, got {result.status}")
    if result.metadata.get("skillfoundry_verification_result_ref") != SKILLFOUNDRY_VERIFICATION_RESULT_REF:
        failures.append("contextforge_verification_result.metadata.skillfoundry_verification_result_ref: mismatch")

    metadata_job_id = result.metadata.get("job_id")
    if metadata_job_id != entry.build_job_id:
        failures.append(
            f"contextforge_verification_result.metadata.job_id: expected {entry.build_job_id}, got {metadata_job_id!r}"
        )
    verifier_hash = result.metadata.get("skillfoundry_verification_result_hash")
    if verifier_hash != entry.verification_result_hash:
        failures.append(
            "contextforge_verification_result.skillfoundry_verification_result_hash: "
            f"expected {entry.verification_result_hash}, got {verifier_hash!r}"
        )
    package_hash = result.metadata.get("current_package_hash")
    if package_hash != entry.package_hash:
        failures.append(
            f"contextforge_verification_result.current_package_hash: expected {entry.package_hash}, "
            f"got {package_hash!r}"
        )

    expected_coverage_hash = _nested_str(entry.provenance, ("acceptance_coverage_result", "sha256"))
    recorded_coverage_hash = result.metadata.get("acceptance_coverage_result_hash")
    if expected_coverage_hash is not None and recorded_coverage_hash != expected_coverage_hash:
        failures.append(
            "contextforge_verification_result.acceptance_coverage_result_hash: "
            f"expected {expected_coverage_hash}, got {recorded_coverage_hash!r}"
        )


def _check_product_grade_against_entry(
    entry: RegistryEntry,
    workspace_root: Path | None,
    failures: list[str],
) -> None:
    registry_status = _entry_registry_status(entry)
    product_grade_value = entry.provenance.get("product_grade_report")
    if product_grade_value is None:
        if registry_status == REGISTRY_STATUS_PRODUCT_GRADE_REGISTERED:
            failures.append("product_grade_report: required for product_grade_registered entries")
        return
    if not isinstance(product_grade_value, Mapping):
        failures.append("product_grade_report: provenance must be a JSON object")
        return
    if workspace_root is None:
        failures.append("product_grade_report: cannot resolve without workspace_root")
        return

    ref = _nested_str(entry.provenance, ("product_grade_report", "ref")) or PRODUCT_GRADE_REPORT_REF
    try:
        path = resolve_under_root(workspace_root, ref, must_exist=True)
    except Exception as exc:
        failures.append(f"product_grade_report: missing or unsafe ref {ref!r}: {exc}")
        return

    expected_hash = _nested_str(entry.provenance, ("product_grade_report", "sha256"))
    if expected_hash is None:
        failures.append("product_grade_report.sha256: missing from provenance")
    actual_hash = _hash_file_or_failure(path, "product_grade_report_hash", failures)
    if expected_hash is not None and actual_hash is not None and actual_hash != expected_hash:
        failures.append(f"product_grade_report_hash: expected {expected_hash}, got {actual_hash}")

    try:
        report = ProductGradeReport.read_json_file(path)
    except Exception as exc:
        failures.append(f"product_grade_report: missing or invalid: {exc}")
        return

    if report.job_id != entry.build_job_id:
        failures.append(f"product_grade_report.job_id: expected {entry.build_job_id}, got {report.job_id}")
    if report.package_hash != entry.package_hash:
        failures.append(f"product_grade_report.package_hash: expected {entry.package_hash}, got {report.package_hash}")

    recorded_product_grade = product_grade_value.get("product_grade")
    if recorded_product_grade is not report.product_grade:
        failures.append(
            f"product_grade_report.product_grade: expected provenance {recorded_product_grade!r}, "
            f"got {report.product_grade}"
        )
    if registry_status == REGISTRY_STATUS_PRODUCT_GRADE_REGISTERED and report.product_grade is not True:
        failures.append("product_grade_report.product_grade: product_grade_registered requires product_grade=true")

    _check_product_repair_packet_against_entry(entry, workspace_root, product_grade_value, failures)


def _check_product_repair_packet_against_entry(
    entry: RegistryEntry,
    workspace_root: Path,
    product_grade_value: Mapping[str, Any],
    failures: list[str],
) -> None:
    repair_packet = product_grade_value.get("repair_packet")
    if repair_packet is None:
        return
    if not isinstance(repair_packet, Mapping):
        failures.append("product_grade_report.repair_packet: provenance must be a JSON object")
        return
    ref = repair_packet.get("ref")
    if not isinstance(ref, str) or not ref.strip():
        failures.append("product_grade_report.repair_packet.ref: missing")
        return
    try:
        path = resolve_under_root(workspace_root, ref, must_exist=True)
    except Exception as exc:
        failures.append(f"product_grade_report.repair_packet: missing or unsafe ref {ref!r}: {exc}")
        return
    expected_hash = repair_packet.get("sha256")
    if not isinstance(expected_hash, str) or not expected_hash.strip():
        failures.append("product_grade_report.repair_packet.sha256: missing")
        return
    actual_hash = _hash_file_or_failure(path, "product_repair_packet_hash", failures)
    if actual_hash is not None and actual_hash != expected_hash:
        failures.append(f"product_repair_packet_hash: expected {expected_hash}, got {actual_hash}")


def _check_manual_acceptance_record_against_coverage(
    entry: RegistryEntry,
    workspace_root: Path,
    coverage_payload: Mapping[str, Any],
    failures: list[str],
) -> None:
    items = coverage_payload.get("items")
    if not isinstance(items, list):
        return
    manual_items = [
        item
        for item in items
        if isinstance(item, Mapping)
        and item.get("priority") == "must"
        and item.get("status") == "manual_only"
    ]
    if not manual_items:
        return

    provenance_ref = _nested_str(
        entry.provenance,
        ("acceptance_coverage_result", "provenance", "manual_acceptance_record", "ref"),
    )
    ref = provenance_ref or MANUAL_ACCEPTANCE_RECORD_REF
    try:
        path = resolve_under_root(workspace_root, ref, must_exist=True)
    except Exception as exc:
        failures.append(f"manual_acceptance_record: missing or unsafe ref {ref!r}: {exc}")
        return

    expected_hash = _nested_str(
        entry.provenance,
        ("acceptance_coverage_result", "provenance", "manual_acceptance_record", "sha256"),
    )
    if expected_hash is None:
        failures.append("manual_acceptance_record.sha256: missing from acceptance coverage provenance")
    actual_hash = _hash_file_or_failure(path, "manual_acceptance_record_hash", failures)
    if expected_hash is not None and actual_hash is not None and actual_hash != expected_hash:
        failures.append(f"manual_acceptance_record_hash: expected {expected_hash}, got {actual_hash}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append(f"manual_acceptance_record: invalid JSON: {exc}")
        return
    if not isinstance(payload, Mapping):
        failures.append("manual_acceptance_record: expected JSON object")
        return
    if payload.get("decision") != "approved":
        failures.append("manual_acceptance_record.decision: expected approved")
    covered = payload.get("covered_criterion_ids")
    covered_ids = {str(item) for item in covered} if isinstance(covered, list) else set()
    for item in manual_items:
        criterion_id = item.get("criterion_id")
        if isinstance(criterion_id, str) and criterion_id not in covered_ids:
            failures.append(f"manual_acceptance_record.covered_criterion_ids: missing {criterion_id}")


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


def _nested_str(payload: Mapping[str, Any], path: tuple[str, ...]) -> str | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    if isinstance(current, str) and current.strip():
        return current
    return None


def _json_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _hash_workspace_ref_or_none(workspace: JobWorkspace, ref: str) -> str | None:
    try:
        return sha256_file(workspace.resolve_path(ref, must_exist=True))
    except Exception:
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
        and _entry_registry_status(left) == _entry_registry_status(right)
        and _nested_str(left.provenance, ("product_grade_report", "sha256"))
        == _nested_str(right.provenance, ("product_grade_report", "sha256"))
    )


def _entry_registry_status(entry: RegistryEntry) -> str:
    status = entry.provenance.get("registry_status")
    if isinstance(status, str) and status.strip():
        return status
    return REGISTRY_STATUS_REGISTERED


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
    "REGISTRY_STATUS_CANDIDATE_REGISTERED",
    "REGISTRY_STATUS_DEPRECATED",
    "REGISTRY_STATUS_GENERATED",
    "REGISTRY_STATUS_PRODUCT_GRADE_REGISTERED",
    "REGISTRY_STATUS_PUBLISHED",
    "REGISTRY_STATUS_REGISTERED",
    "REGISTRY_STATUS_VERIFIED",
    "REGISTRY_STATUSES",
    "RegistryDuplicateError",
    "RegistryEntryNotFound",
    "RegistryError",
    "RegistryGateError",
    "RegistryVerificationReport",
]
