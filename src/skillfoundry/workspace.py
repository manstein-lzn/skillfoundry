"""Job workspace initialization, artifact manifests, and locked input checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .schema import (
    ArtifactManifest,
    ArtifactRecord,
    BuildContract,
    SkillSpec,
    VerificationSpec,
    sha256_file,
    utc_now,
)
from .security import PathSecurityError, resolve_under_root


LOCKED_INPUT_PATHS = (
    "build_contract.yaml",
    "skill_spec.yaml",
    "verification_spec.yaml",
    "worker_input.md",
)

JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class LockedInputTamperError(ValueError):
    """Raised when a locked workspace input is missing or hash-mismatched."""

    def __init__(self, failures: list[str]) -> None:
        self.failures = failures
        super().__init__("locked input tamper detected: " + "; ".join(failures))


def _validate_job_id(job_id: str) -> None:
    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        raise ValueError("job_id must be a non-empty safe path segment")


def _default_skill_spec(job_id: str) -> SkillSpec:
    return SkillSpec(
        skill_id=f"{job_id}-skill",
        title="SkillFoundry WP1 placeholder skill",
        description="Minimal SkillSpec used to initialize a WP1 job workspace.",
        trigger_scenarios=["A later workflow decides to build a Codex Skill."],
        non_trigger_scenarios=["Requests outside this job workspace."],
        required_inputs=["Natural language requirement summary."],
        expected_outputs=["A Codex Skill package after later work packages run."],
        constraints=["WP1 initializes contracts only and does not execute workers."],
        acceptance_criteria=["Workspace contracts and locked input hashes are valid."],
        reference_materials=[],
        security_notes=["Workspace path references must remain relative and confined."],
    )


def _default_verification_spec(job_id: str) -> VerificationSpec:
    return VerificationSpec(
        spec_id=f"{job_id}-verification",
        job_id=job_id,
        required_checks=[
            "schema_round_trip",
            "locked_input_hash_match",
            "path_confinement",
        ],
        artifact_requirements=list(LOCKED_INPUT_PATHS) + ["artifact_manifest.json"],
        path_policies=[
            "reject_absolute_paths",
            "reject_parent_traversal",
            "ban_symlink_components",
        ],
        acceptance_criteria=["All locked inputs match the artifact manifest hashes."],
        verifier_version="wp1-schema-only",
    )


def _write_worker_input(path: Path, text: str | None) -> None:
    content = text or (
        "# Worker Input\n\n"
        "This WP1 workspace is initialized for later SkillFoundry work packages.\n"
        "No worker execution is performed by WP1.\n"
    )
    path.write_text(content, encoding="utf-8")


def _record_for_file(job_root: Path, job_id: str, relative_path: str, *, locked: bool) -> ArtifactRecord:
    path = resolve_under_root(job_root, relative_path, must_exist=True)
    safe_id = relative_path.replace("/", ":")
    return ArtifactRecord(
        artifact_id=f"{job_id}:{safe_id}",
        path=relative_path,
        kind="locked_input" if locked else "artifact",
        sha256=sha256_file(path),
        created_by="skillfoundry.workspace",
        created_at=utc_now(),
        job_id=job_id,
        attempt_id=None,
        locked=locked,
    )


def verify_locked_inputs(job_root: str | Path, manifest: ArtifactManifest) -> None:
    """Fail if any locked manifest record is missing or has a different hash."""

    root = Path(job_root)
    failures: list[str] = []
    locked_paths = [record.path for record in manifest.locked_records()]
    locked_path_set = set(locked_paths)
    for required_path in LOCKED_INPUT_PATHS:
        if required_path not in locked_path_set:
            failures.append(f"{required_path}: missing locked manifest record")
    duplicate_paths = sorted({path for path in locked_paths if locked_paths.count(path) > 1})
    for duplicate_path in duplicate_paths:
        failures.append(f"{duplicate_path}: duplicate locked manifest record")

    for record in manifest.locked_records():
        try:
            artifact_path = resolve_under_root(root, record.path, must_exist=True)
            actual_hash = sha256_file(artifact_path)
        except (OSError, PathSecurityError) as exc:
            failures.append(f"{record.path}: {exc}")
            continue
        if actual_hash != record.sha256:
            failures.append(f"{record.path}: expected {record.sha256}, got {actual_hash}")
    if failures:
        raise LockedInputTamperError(failures)


@dataclass
class JobWorkspace:
    """A confined SkillFoundry job workspace."""

    root: Path
    job_id: str

    @property
    def manifest_path(self) -> Path:
        return self.resolve_path("artifact_manifest.json", must_exist=True)

    def resolve_path(self, relative_path: str, *, must_exist: bool = False) -> Path:
        return resolve_under_root(self.root, relative_path, must_exist=must_exist)

    def read_manifest(self) -> ArtifactManifest:
        return ArtifactManifest.read_json_file(self.manifest_path)

    def write_manifest(self, manifest: ArtifactManifest) -> None:
        manifest.write_json_file(self.resolve_path("artifact_manifest.json"))

    def check_locked_inputs(self) -> None:
        verify_locked_inputs(self.root, self.read_manifest())

    def record_artifact(self, relative_path: str, *, locked: bool = False) -> ArtifactRecord:
        return _record_for_file(self.root, self.job_id, relative_path, locked=locked)


def initialize_job_workspace(
    runs_root: str | Path,
    job_id: str,
    *,
    skill_spec: SkillSpec | None = None,
    verification_spec: VerificationSpec | None = None,
    build_contract: BuildContract | None = None,
    worker_input: str | None = None,
    overwrite: bool = False,
) -> JobWorkspace:
    """Create the standard ``runs/<job_id>/`` WP1 workspace layout."""

    _validate_job_id(job_id)
    runs_path = Path(runs_root)
    job_root = runs_path / job_id
    if job_root.exists() and any(job_root.iterdir()) and not overwrite:
        raise FileExistsError(f"workspace already exists: {job_root}")

    for relative_dir in (
        "attempts",
        "package",
        "package/references",
        "package/scripts",
        "package/tests",
        "verifier",
    ):
        (job_root / relative_dir).mkdir(parents=True, exist_ok=True)

    skill_spec = skill_spec or _default_skill_spec(job_id)
    verification_spec = verification_spec or _default_verification_spec(job_id)
    skill_spec.write_yaml_file(job_root / "skill_spec.yaml")
    verification_spec.write_yaml_file(job_root / "verification_spec.yaml")
    _write_worker_input(job_root / "worker_input.md", worker_input)

    locked_hashes = {
        "skill_spec.yaml": sha256_file(job_root / "skill_spec.yaml"),
        "verification_spec.yaml": sha256_file(job_root / "verification_spec.yaml"),
        "worker_input.md": sha256_file(job_root / "worker_input.md"),
    }
    if build_contract is None:
        build_contract = BuildContract(
            job_id=job_id,
            skill_spec_ref="skill_spec.yaml",
            verification_spec_ref="verification_spec.yaml",
            workspace_root=str(job_root),
            allowed_write_paths=["package", "attempts"],
            blocked_paths=[".."],
            timeout_seconds=300,
            attempt_limit=1,
            required_artifacts=list(LOCKED_INPUT_PATHS),
            locked_input_hashes=locked_hashes,
        )
    build_contract.write_yaml_file(job_root / "build_contract.yaml")

    manifest = ArtifactManifest(
        job_id=job_id,
        artifacts=[
            _record_for_file(job_root, job_id, relative_path, locked=True)
            for relative_path in LOCKED_INPUT_PATHS
        ],
        created_at=utc_now(),
    )
    manifest.write_json_file(job_root / "artifact_manifest.json")

    (job_root / "resume_brief.md").write_text(
        "\n".join(
            [
                f"# Resume Brief: {job_id}",
                "",
                "WP1 initialized this workspace and locked the input files listed in artifact_manifest.json.",
                "No worker transcript, verifier business result, registry approval, or ContextForge record exists yet.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    workspace = JobWorkspace(root=job_root, job_id=job_id)
    workspace.check_locked_inputs()
    return workspace
