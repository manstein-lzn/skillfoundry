import pytest

from skillfoundry.bundle import (
    BUNDLE_MANIFEST_REF,
    BUNDLE_SCHEMA_VERSION,
    BUNDLE_TYPES,
    CapabilityBundleManifest,
    FORBIDDEN_BUNDLE_FIELDS,
    declared_package_refs,
)
from skillfoundry.schema import SchemaValidationError


def sample_manifest() -> CapabilityBundleManifest:
    return CapabilityBundleManifest(
        bundle_id="demo-bundle",
        bundle_type="code_runtime",
        entrypoint="SKILL.md",
        capability_surface={"commands": ["summarize"]},
        runtime_assets=["runtime/cli.py"],
        data_assets=["data/fixtures.jsonl"],
        references=["references/guide.md"],
        environment={"python": ">=3.11"},
        permissions={"network": False},
        verification={"commands": ["python runtime/cli.py --help"]},
        distribution={"target": "codex_skill"},
    )


def test_bundle_manifest_constants_are_stable():
    assert BUNDLE_MANIFEST_REF == "package/skillfoundry.bundle.json"
    assert BUNDLE_SCHEMA_VERSION == "skillfoundry.bundle.v1"
    assert "prompt_only" in BUNDLE_TYPES
    assert "full_runtime_bundle" in BUNDLE_TYPES


def test_bundle_manifest_json_round_trip():
    manifest = sample_manifest()

    loaded = CapabilityBundleManifest.from_json(manifest.to_json())

    assert loaded.to_dict() == manifest.to_dict()


def test_bundle_manifest_unknown_fields_fail():
    payload = sample_manifest().to_dict()
    payload["unexpected"] = True

    with pytest.raises(SchemaValidationError):
        CapabilityBundleManifest.from_dict(payload)


@pytest.mark.parametrize("bundle_type", ["", "unknown", "runtime"])
def test_bundle_manifest_invalid_bundle_type_fails(bundle_type):
    manifest = sample_manifest()
    manifest.bundle_type = bundle_type

    with pytest.raises(SchemaValidationError):
        manifest.to_dict()


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("entrypoint", "../SKILL.md"),
        ("entrypoint", "/tmp/SKILL.md"),
        ("entrypoint", "package/SKILL.md"),
        ("runtime_assets", ["runtime/../secret.py"]),
        ("data_assets", ["data//kb.jsonl"]),
        ("references", ["C:\\secret\\guide.md"]),
    ],
)
def test_bundle_manifest_rejects_unsafe_refs(field_name, value):
    payload = sample_manifest().to_dict()
    payload[field_name] = value

    with pytest.raises(SchemaValidationError):
        CapabilityBundleManifest.from_dict(payload)


def test_bundle_manifest_rejects_non_json_structured_fields():
    manifest = sample_manifest()
    manifest.capability_surface = {"bad": {object()}}  # type: ignore[dict-item]

    with pytest.raises(SchemaValidationError):
        manifest.to_dict()


@pytest.mark.parametrize(
    "field_name",
    ["capability_surface", "environment", "permissions", "verification", "distribution"],
)
def test_bundle_manifest_rejects_forbidden_raw_fields(field_name):
    payload = sample_manifest().to_dict()
    payload[field_name] = {"nested": {"raw_prompt": "do not persist raw prompt bodies"}}

    with pytest.raises(SchemaValidationError):
        CapabilityBundleManifest.from_dict(payload)


def test_forbidden_bundle_fields_cover_raw_context_boundaries():
    assert {"messages", "raw_prompt", "raw_transcript", "raw_model_output"}.issubset(FORBIDDEN_BUNDLE_FIELDS)


def test_declared_package_refs_are_deduped_in_order():
    manifest = CapabilityBundleManifest(
        bundle_id="demo-bundle",
        bundle_type="prompt_only",
        entrypoint="SKILL.md",
        references=["SKILL.md", "references/guide.md"],
    )

    assert declared_package_refs(manifest) == ["SKILL.md", "references/guide.md"]
