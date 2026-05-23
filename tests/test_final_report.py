from __future__ import annotations

import ast
from pathlib import Path

import skillfoundry
import skillfoundry.final_report as final_report
import skillfoundry.offline as offline


def test_final_report_public_and_legacy_aliases_point_to_neutral_module() -> None:
    assert skillfoundry.emit_final_report is final_report.emit_final_report
    assert skillfoundry.read_final_report is final_report.read_final_report
    assert offline.emit_final_report is final_report.emit_final_report
    assert offline.read_final_report is final_report.read_final_report
    assert skillfoundry.OFFLINE_REPORT_VERSION == final_report.OFFLINE_REPORT_VERSION
    assert offline.OFFLINE_REPORT_VERSION == final_report.OFFLINE_REPORT_VERSION


def test_current_paths_do_not_import_final_report_helpers_from_offline() -> None:
    root = Path(__file__).resolve().parents[1]
    current_paths = [
        root / "src/skillfoundry/__init__.py",
        root / "src/skillfoundry/api.py",
        root / "src/skillfoundry/cli.py",
        root / "src/skillfoundry/forgeunit_adapter.py",
        root / "src/skillfoundry/goal_runtime.py",
        root / "src/skillfoundry/graph_v2.py",
    ]
    forbidden = {"emit_final_report", "read_final_report"}

    offenders: list[str] = []
    for path in current_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module != "offline":
                continue
            imported = {alias.name for alias in node.names}
            leaked = sorted(imported & forbidden)
            if leaked:
                offenders.append(f"{path.relative_to(root).as_posix()}: {', '.join(leaked)}")

    assert offenders == []
