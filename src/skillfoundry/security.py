"""Path confinement utilities for SkillFoundry workspaces."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath


class PathSecurityError(ValueError):
    """Raised when a path attempts to escape a workspace boundary."""


def _is_windows_absolute_or_drive(path_text: str) -> bool:
    windows_path = PureWindowsPath(path_text)
    return bool(windows_path.drive) or windows_path.is_absolute()


def validate_relative_path(path: str | os.PathLike[str]) -> PurePosixPath:
    """Validate a persisted workspace path as a safe relative path."""

    path_text = os.fspath(path)
    if not isinstance(path_text, str) or not path_text:
        raise PathSecurityError("path must be a non-empty relative string")
    if "\x00" in path_text:
        raise PathSecurityError("path must not contain NUL bytes")
    if os.path.isabs(path_text) or _is_windows_absolute_or_drive(path_text):
        raise PathSecurityError(f"absolute paths are not allowed: {path_text}")

    normalized = path_text.replace("\\", "/")
    raw_parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in raw_parts):
        raise PathSecurityError(f"path contains an unsafe segment: {path_text}")
    return PurePosixPath(*raw_parts)


def assert_under_root(root: str | Path, candidate: str | Path) -> Path:
    """Return candidate if its resolved path is under root, otherwise fail."""

    root_path = Path(root).resolve(strict=True)
    candidate_path = Path(candidate).resolve(strict=False)
    try:
        candidate_path.relative_to(root_path)
    except ValueError as exc:
        raise PathSecurityError(f"path escapes workspace root: {candidate}") from exc
    return candidate_path


def _check_existing_components_for_symlinks(root: Path, parts: tuple[str, ...]) -> None:
    current = root
    for part in parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink():
                raise PathSecurityError(f"symlink components are not allowed: {current}")
            assert_under_root(root, current)


def resolve_under_root(
    root: str | Path,
    relative_path: str | os.PathLike[str],
    *,
    must_exist: bool = False,
    parent_must_exist: bool = True,
) -> Path:
    """Resolve a safe relative path under root while banning symlink components."""

    root_path = Path(root).resolve(strict=True)
    safe_relative = validate_relative_path(relative_path)
    target = root_path.joinpath(*safe_relative.parts)

    _check_existing_components_for_symlinks(root_path, safe_relative.parts)

    if parent_must_exist and not target.parent.exists():
        raise PathSecurityError(f"parent directory does not exist under workspace: {relative_path}")
    if must_exist and not target.exists():
        raise PathSecurityError(f"path does not exist under workspace: {relative_path}")

    if target.exists():
        resolved_target = target.resolve(strict=True)
    else:
        resolved_target = target.parent.resolve(strict=True) / target.name
    return assert_under_root(root_path, resolved_target)
