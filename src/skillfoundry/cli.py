"""Minimal WP7 offline command line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .offline import (
    OfflineWorkerMode,
    build_offline,
    emit_final_report,
    read_final_report,
    register_offline,
    verify_offline,
)
from .schema import ensure_json_compatible


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "build":
        result = build_offline(
            requirement_path=args.requirement,
            output=args.output,
            registry_path=args.registry,
            route=args.route,
            worker_mode=args.worker_mode,
            attempt_limit=args.attempt_limit,
            timeout_seconds=args.timeout_seconds,
            version=args.version,
            resume=args.resume,
            overwrite=args.overwrite,
        )
        _print_json(result.final_report)
        return 0 if result.final_report.get("final_status") in {"registered", "reused"} else 2

    if args.command == "verify":
        result = verify_offline(args.job, attempt_id=args.attempt_id)
        _print_json(result.to_dict())
        return 0 if result.passed else 2

    if args.command == "registry":
        if args.registry_command == "add":
            entry = register_offline(
                args.job,
                registry_path=args.registry,
                version=args.version,
            )
            report = emit_final_report(
                args.job,
                final_status="registered",
                route=args.route,
                registry_path=args.registry,
                registry_entry=entry,
            )
            _print_json(report)
            return 0
        parser.error("registry subcommand is required")

    if args.command == "report":
        if args.refresh:
            report = emit_final_report(args.job, registry_path=args.registry)
        else:
            report_path = Path(args.job) / "final_report.json"
            report = read_final_report(args.job) if report_path.exists() else emit_final_report(args.job, registry_path=args.registry)
        _print_json(report)
        return 0

    if args.command == "serve":
        from .api import serve_http

        serve_http(
            args.runs_root,
            registry_path=args.registry,
            host=args.host,
            port=args.port,
        )
        return 0

    parser.error("command is required")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skillfoundry")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="run the offline build/verify/register/report flow")
    build.add_argument("--requirement", type=Path, required=False)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--registry", type=Path, required=False)
    build.add_argument("--route", choices=["build_new", "reuse_existing", "reject_unsafe", "ask_clarifying_question"])
    build.add_argument("--worker-mode", choices=[mode.value for mode in OfflineWorkerMode])
    build.add_argument("--attempt-limit", type=int, default=2)
    build.add_argument("--timeout-seconds", type=int, default=300)
    build.add_argument("--version", default="0.1.0")
    build.add_argument("--resume", action="store_true")
    build.add_argument("--overwrite", action="store_true")

    verify = subparsers.add_parser("verify", help="run verifier for a job workspace")
    verify.add_argument("--job", type=Path, required=True)
    verify.add_argument("--attempt-id")

    registry = subparsers.add_parser("registry", help="registry operations")
    registry_subparsers = registry.add_subparsers(dest="registry_command", required=True)
    add = registry_subparsers.add_parser("add", help="add a verified job package to a registry")
    add.add_argument("--job", type=Path, required=True)
    add.add_argument("--registry", type=Path, required=True)
    add.add_argument("--version", default="0.1.0")
    add.add_argument("--route", default="build_new")

    report = subparsers.add_parser("report", help="print or refresh final_report.json")
    report.add_argument("--job", type=Path, required=True)
    report.add_argument("--registry", type=Path, required=False)
    report.add_argument("--refresh", action="store_true")

    serve = subparsers.add_parser("serve", help="serve the minimal WP9 internal API/UI")
    serve.add_argument("--runs-root", type=Path, default=Path("runs"))
    serve.add_argument("--registry", type=Path, required=False)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    return parser


def _print_json(payload: object) -> None:
    compatible = ensure_json_compatible(payload)
    print(json.dumps(compatible, sort_keys=True, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
