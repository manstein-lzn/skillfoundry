import sys
from pathlib import Path

import pytest

from skillfoundry import (
    PRODUCT_RUNTIME_CHECK_PLAN_REF,
    PRODUCT_RUNTIME_CHECK_RESULT_REF,
    ProductRuntimeCheckResult,
    ProductRuntimeCheckRunner,
    RuntimeCheckCommand,
    RuntimeCheckPlan,
    SchemaValidationError,
    initialize_job_workspace,
)


def make_workspace(tmp_path: Path, job_id: str = "runtime-checks-001"):
    workspace = initialize_job_workspace(tmp_path / "runs", job_id)
    workspace.resolve_path("package/scripts").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("package/scripts/runtime_check.py").write_text(
        """
import sys

mode = sys.argv[1]
if mode == "conflict":
    print("conflict")
    raise SystemExit(3)
if mode == "fail":
    print("fail")
    raise SystemExit(2)
print("ok")
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    return workspace


def command(check_id: str, item_id: str, mode: str, expected_exit_code: int = 0) -> RuntimeCheckCommand:
    return RuntimeCheckCommand(
        check_id=check_id,
        item_id=item_id,
        command=[sys.executable, "scripts/runtime_check.py", mode],
        expected_exit_code=expected_exit_code,
        cwd="package",
    )


def test_runtime_check_runner_fails_closed_when_required_plan_is_missing(tmp_path: Path):
    workspace = make_workspace(tmp_path)

    result = ProductRuntimeCheckRunner().run(
        workspace,
        required_item_ids=["PG-RUNTIME-SAME-PLAN-DUPLICATE-PATH"],
    )

    assert result.passed is False
    assert result.plan_present is False
    assert result.missing_item_ids == ["PG-RUNTIME-SAME-PLAN-DUPLICATE-PATH"]
    assert "runtime_check_plan" in result.failures[0]
    assert workspace.resolve_path(PRODUCT_RUNTIME_CHECK_RESULT_REF, must_exist=True).is_file()


def test_runtime_check_runner_executes_declared_commands_and_exit_codes(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    RuntimeCheckPlan(
        commands=[
            command("runtime-ok", "PG-RUNTIME-CLI-OK-EXIT-CODE", "ok", 0),
            command("runtime-conflict", "PG-RUNTIME-CLI-CONFLICT-EXIT-CODE", "conflict", 3),
        ]
    ).write_json_file(workspace.resolve_path(PRODUCT_RUNTIME_CHECK_PLAN_REF))

    result = ProductRuntimeCheckRunner().run(
        workspace,
        required_item_ids=[
            "PG-RUNTIME-CLI-OK-EXIT-CODE",
            "PG-RUNTIME-CLI-CONFLICT-EXIT-CODE",
        ],
    )

    assert result.passed is True
    assert result.plan_present is True
    assert result.missing_item_ids == []
    assert [check.actual_exit_code for check in result.checks] == [0, 3]
    assert all(check.stdout_ref for check in result.checks)
    loaded = ProductRuntimeCheckResult.read_json_file(
        workspace.resolve_path(PRODUCT_RUNTIME_CHECK_RESULT_REF, must_exist=True)
    )
    assert loaded.to_dict() == result.to_dict()


def test_runtime_check_runner_reports_failed_command(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    RuntimeCheckPlan(
        commands=[
            command("runtime-fail", "PG-RUNTIME-PATH-TRAVERSAL-REJECTED", "fail", 0),
        ]
    ).write_json_file(workspace.resolve_path(PRODUCT_RUNTIME_CHECK_PLAN_REF))

    result = ProductRuntimeCheckRunner().run(
        workspace,
        required_item_ids=["PG-RUNTIME-PATH-TRAVERSAL-REJECTED"],
    )

    assert result.passed is False
    assert result.checks[0].actual_exit_code == 2
    assert "expected exit code 0, got 2" in result.failures[0]


def test_runtime_check_plan_rejects_unknown_fields_and_shell_strings():
    payload = RuntimeCheckPlan(
        commands=[command("runtime-ok", "PG-RUNTIME-CLI-OK-EXIT-CODE", "ok")]
    ).to_dict()
    payload["unexpected"] = True

    with pytest.raises(SchemaValidationError):
        RuntimeCheckPlan.from_dict(payload)

    with pytest.raises(SchemaValidationError):
        RuntimeCheckCommand(
            check_id="bad",
            item_id="PG-RUNTIME-CLI-OK-EXIT-CODE",
            command="python script.py",  # type: ignore[arg-type]
        ).to_dict()
