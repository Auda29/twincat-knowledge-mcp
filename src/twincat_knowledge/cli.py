"""Command-line entry point for the package foundation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from .config import (
    ConfigFileExistsError,
    create_default_config,
    diagnose_config,
    render_diagnosis,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twincat-knowledge",
        description="Data-source-neutral TwinCAT knowledge package foundation.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"twincat-knowledge {__version__}",
    )
    commands = parser.add_subparsers(dest="command")

    init_parser = commands.add_parser(
        "init", help="create a new local operator configuration"
    )
    init_parser.add_argument("--config", required=True, type=str)

    doctor_parser = commands.add_parser(
        "doctor", help="check local readiness without printing secrets"
    )
    doctor_parser.add_argument("--config", required=True, type=str)
    doctor_parser.add_argument(
        "--json", action="store_true", help="emit a machine-readable report"
    )
    return parser


def _run_init(config_path: str) -> int:
    try:
        create_default_config(config_path)
    except ConfigFileExistsError:
        print(
            "configuration path already exists; refusing to overwrite", file=sys.stderr
        )
        return 2
    except OSError:
        print("configuration could not be created", file=sys.stderr)
        return 1
    print(f"created configuration: {config_path}")
    return 0


def _run_doctor(config_path: str, as_json: bool) -> int:
    report = diagnose_config(config_path)
    if as_json:
        print(render_diagnosis(report), end="")
    else:
        print(f"status: {report['status']}")
        checks = report.get("checks", {})
        if isinstance(checks, dict):
            for name, check in checks.items():
                if isinstance(check, dict):
                    print(f"{name}: {check.get('status', 'unknown')}")
    return 0 if report["status"] == "ok" else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return _run_init(args.config)
    if args.command == "doctor":
        return _run_doctor(args.config, args.json)
    parser.print_help()
    return 0
