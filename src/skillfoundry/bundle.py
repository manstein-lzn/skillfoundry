"""Capability bundle manifest schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import (
    JsonValue,
    SchemaModel,
    SchemaValidationError,
    _require_json_mapping,
    _require_non_empty_str,
)
from .security import PathSecurityError, validate_relative_path


BUNDLE_MANIFEST_REF = "package/skillfoundry.bundle.json"
BUNDLE_SCHEMA_VERSION = "skillfoundry.bundle.v1"
BUNDLE_TYPES = frozenset(
    {
        "prompt_only",
        "script_tool",
        "code_runtime",
        "knowledge_runtime",
        "mcp_runtime",
        "service_runtime",
        "full_runtime_bundle",
    }
)
FORBIDDEN_BUNDLE_FIELDS = frozenset(
    {
        "conversation",
        "conversation_turns",
        "messages",
        "prompt",
        "prompts",
        "raw_prompt",
        "model_output",
        "model_outputs",
        "raw_model_output",
        "raw_model_outputs",
        "transcript",
        "raw_transcript",
    }
)


def _require_bundle_type(value: Any, field_name: str) -> None:
    _require_non_empty_str(value, field_name)
    if value not in BUNDLE_TYPES:
        allowed = ", ".join(sorted(BUNDLE_TYPES))
        raise SchemaValidationError(f"{field_name} must be one of: {allowed}")


def _require_package_ref(value: Any, field_name: str) -> None:
    _require_non_empty_str(value, field_name)
    try:
        safe = validate_relative_path(value)
    except PathSecurityError as exc:
        raise SchemaValidationError(f"{field_name} must be a safe package-relative ref: {exc}") from exc
    if safe.parts and safe.parts[0] == "package":
        raise SchemaValidationError(f"{field_name} must be relative to package/, not start with package/")


def _require_package_ref_list(value: Any, field_name: str) -> None:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list of package-relative refs")
    for index, item in enumerate(value):
        _require_package_ref(item, f"{field_name}[{index}]")


def _reject_forbidden_keys(value: Any, field_name: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_BUNDLE_FIELDS:
                raise SchemaValidationError(f"{field_name} contains forbidden raw field: {key}")
            _reject_forbidden_keys(item, f"{field_name}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_forbidden_keys(item, f"{field_name}[{index}]")


def _require_safe_json_mapping(value: Any, field_name: str) -> None:
    _require_json_mapping(value, field_name)
    _reject_forbidden_keys(value, field_name)


@dataclass
class CapabilityBundleManifest(SchemaModel):
    bundle_id: str
    bundle_type: str
    entrypoint: str = "SKILL.md"
    capability_surface: dict[str, JsonValue] = field(default_factory=dict)
    runtime_assets: list[str] = field(default_factory=list)
    data_assets: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    environment: dict[str, JsonValue] = field(default_factory=dict)
    permissions: dict[str, JsonValue] = field(default_factory=dict)
    verification: dict[str, JsonValue] = field(default_factory=dict)
    distribution: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: str = BUNDLE_SCHEMA_VERSION

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.bundle_id, "bundle_id")
        _require_bundle_type(self.bundle_type, "bundle_type")
        _require_package_ref(self.entrypoint, "entrypoint")
        for name in ("runtime_assets", "data_assets", "references"):
            _require_package_ref_list(getattr(self, name), name)
        for name in (
            "capability_surface",
            "environment",
            "permissions",
            "verification",
            "distribution",
        ):
            _require_safe_json_mapping(getattr(self, name), name)


def declared_package_refs(manifest: CapabilityBundleManifest) -> list[str]:
    """Return all package-relative refs declared by a bundle manifest."""

    manifest.validate()
    refs = [
        manifest.entrypoint,
        *manifest.runtime_assets,
        *manifest.data_assets,
        *manifest.references,
    ]
    return list(dict.fromkeys(refs))
