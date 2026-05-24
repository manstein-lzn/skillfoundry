"""Deterministic verifier for SkillFoundry capability bundle manifests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bundle import BUNDLE_MANIFEST_REF, CapabilityBundleManifest, declared_package_refs
from .schema import (
    JsonValue,
    SchemaModel,
    SchemaValidationError,
    _require_bool,
    _require_json_mapping,
    _require_str_list,
    sha256_file,
    sha256_json,
    utc_now,
)
from .security import PathSecurityError, validate_relative_path
from .workspace import JobWorkspace


BUNDLE_VERIFIER_VERSION = "skillfoundry.bundle_verifier.v1"
BUNDLE_VERIFICATION_RESULT_REF = "verifier/bundle_verification_result.json"


@dataclass(frozen=True)
class BundleVerifierCheck:
    name: str
    passed: bool
    severity: str
    message: str
    evidence_ref: str

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "passed": self.passed,
            "severity": self.severity,
            "message": self.message,
            "evidence_ref": self.evidence_ref,
        }


@dataclass
class BundleVerificationResult(SchemaModel):
    job_id: str
    manifest_present: bool
    passed: bool
    checks: list[dict[str, JsonValue]]
    failures: list[str]
    evidence_refs: list[str]
    package_hash: str
    verifier_version: str = BUNDLE_VERIFIER_VERSION
    created_at: str = ""
    schema_version: str = "skillfoundry.bundle_verification_result.v1"

    def validate(self) -> None:
        super().validate()
        if not self.created_at:
            self.created_at = utc_now()
        _require_bool(self.manifest_present, "manifest_present")
        _require_bool(self.passed, "passed")
        _require_str_list(self.failures, "failures")
        _require_str_list(self.evidence_refs, "evidence_refs")
        _require_json_mapping({"checks": self.checks}, "checks")
        _require_json_mapping({"package_hash": self.package_hash}, "package_hash")


class BundleVerifier:
    """Verify optional Capability Bundle manifests without executing package code."""

    def __init__(self, *, require_manifest: bool = False, verifier_version: str = BUNDLE_VERIFIER_VERSION) -> None:
        self.require_manifest = require_manifest
        self.verifier_version = verifier_version

    def verify(self, workspace: JobWorkspace) -> BundleVerificationResult:
        verifier_dir = workspace.resolve_path("verifier")
        verifier_dir.mkdir(parents=True, exist_ok=True)
        checks: list[BundleVerifierCheck] = []
        manifest = self._load_manifest(workspace, checks)
        package_hash = hash_package_tree(workspace)

        if manifest is not None:
            self._check_manifest_entrypoint(workspace, manifest, checks)
            self._check_declared_assets(workspace, manifest, checks)
            self._check_profile(workspace, manifest, checks)
        failed = [check for check in checks if check.severity == "error" and not check.passed]
        failures = [f"{check.name}: {check.message}" for check in failed]
        result = BundleVerificationResult(
            job_id=workspace.job_id,
            manifest_present=manifest is not None,
            passed=not failed,
            checks=[check.to_dict() for check in checks],
            failures=failures,
            evidence_refs=_dedupe_refs([BUNDLE_MANIFEST_REF if manifest is not None else None, *[check.evidence_ref for check in checks]]),
            package_hash=package_hash,
            verifier_version=self.verifier_version,
            created_at=utc_now(),
        )
        result.validate()
        result.write_json_file(workspace.resolve_path(BUNDLE_VERIFICATION_RESULT_REF))
        return result

    def _load_manifest(self, workspace: JobWorkspace, checks: list[BundleVerifierCheck]) -> CapabilityBundleManifest | None:
        manifest_path = workspace.resolve_path(BUNDLE_MANIFEST_REF)
        if not manifest_path.exists():
            checks.append(
                _check(
                    "bundle_manifest_present",
                    not self.require_manifest,
                    "bundle manifest is optional and not present"
                    if not self.require_manifest
                    else "bundle manifest is required but not present",
                    BUNDLE_MANIFEST_REF,
                    severity="warning" if not self.require_manifest else "error",
                )
            )
            return None
        try:
            manifest = CapabilityBundleManifest.read_json_file(manifest_path)
        except Exception as exc:
            checks.append(_check("bundle_manifest_valid", False, f"bundle manifest is invalid: {exc}", BUNDLE_MANIFEST_REF))
            return None
        checks.append(_check("bundle_manifest_present", True, "bundle manifest is present", BUNDLE_MANIFEST_REF))
        checks.append(_check("bundle_manifest_valid", True, "bundle manifest validates", BUNDLE_MANIFEST_REF))
        return manifest

    def _check_manifest_entrypoint(
        self,
        workspace: JobWorkspace,
        manifest: CapabilityBundleManifest,
        checks: list[BundleVerifierCheck],
    ) -> None:
        package_ref = _package_ref(manifest.entrypoint)
        exists = _package_file_exists(workspace, package_ref)
        checks.append(
            _check(
                "bundle_entrypoint_exists",
                exists,
                f"bundle entrypoint {package_ref} exists" if exists else f"bundle entrypoint {package_ref} is missing",
                package_ref,
            )
        )

    def _check_declared_assets(
        self,
        workspace: JobWorkspace,
        manifest: CapabilityBundleManifest,
        checks: list[BundleVerifierCheck],
    ) -> None:
        for ref in declared_package_refs(manifest):
            try:
                package_ref = _package_ref(ref)
            except SchemaValidationError as exc:
                checks.append(_check("bundle_declared_ref_safe", False, str(exc), BUNDLE_MANIFEST_REF))
                continue
            exists = _package_file_exists(workspace, package_ref)
            checks.append(
                _check(
                    "bundle_declared_ref_exists",
                    exists,
                    f"declared ref {package_ref} exists" if exists else f"declared ref {package_ref} is missing",
                    package_ref,
                )
            )

    def _check_profile(
        self,
        workspace: JobWorkspace,
        manifest: CapabilityBundleManifest,
        checks: list[BundleVerifierCheck],
    ) -> None:
        if manifest.bundle_type == "prompt_only":
            exists = _package_file_exists(workspace, "package/SKILL.md")
            checks.append(
                _check(
                    "bundle_prompt_only_skill_md",
                    exists,
                    "prompt_only bundle has package/SKILL.md"
                    if exists
                    else "prompt_only bundle requires package/SKILL.md",
                    "package/SKILL.md",
                )
            )
        if manifest.bundle_type == "code_runtime":
            commands = manifest.verification.get("commands")
            command_list_ok = commands is None or (
                isinstance(commands, list) and all(isinstance(item, str) and item.strip() for item in commands)
            )
            checks.append(
                _check(
                    "bundle_code_runtime_verification_commands_declared",
                    command_list_ok,
                    "code_runtime verification commands are recorded as required evidence, not executed"
                    if command_list_ok
                    else "code_runtime verification.commands must be a list of non-empty strings",
                    BUNDLE_MANIFEST_REF,
                    severity="info" if command_list_ok else "error",
                )
            )


def hash_package_tree(workspace: JobWorkspace) -> str:
    """Return a deterministic hash covering all regular files below package/."""

    package_root = workspace.resolve_path("package")
    if not package_root.exists():
        return sha256_json({"package": "missing"})
    records: dict[str, str] = {}
    for path in sorted(package_root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(package_root).as_posix()
            records[relative] = sha256_file(path)
    return sha256_json(records)


def _package_ref(package_relative_ref: str) -> str:
    try:
        validate_relative_path(package_relative_ref)
    except PathSecurityError as exc:
        raise SchemaValidationError(f"declared bundle ref is unsafe: {exc}") from exc
    return f"package/{package_relative_ref}"


def _package_file_exists(workspace: JobWorkspace, package_ref: str) -> bool:
    try:
        safe = validate_relative_path(package_ref)
    except PathSecurityError:
        return False
    candidate = workspace.root.joinpath(*safe.parts)
    if not candidate.exists():
        return False
    try:
        return workspace.resolve_path(package_ref, must_exist=True).is_file()
    except PathSecurityError:
        return False


def _check(
    name: str,
    passed: bool,
    message: str,
    evidence_ref: str,
    *,
    severity: str = "error",
) -> BundleVerifierCheck:
    return BundleVerifierCheck(
        name=name,
        passed=passed,
        severity=severity,
        message=message,
        evidence_ref=evidence_ref,
    )


def _dedupe_refs(refs: list[str | None]) -> list[str]:
    result: list[str] = []
    for ref in refs:
        if ref and ref not in result:
            result.append(ref)
    return result
