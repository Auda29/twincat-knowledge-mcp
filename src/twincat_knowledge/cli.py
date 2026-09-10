"""Command-line entry point for the package foundation."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

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
    inspect_parser = commands.add_parser(
        "inspect-infosys", help="read selected InfoSys XHTML and emit metadata only"
    )
    inspect_parser.add_argument("--source", required=True, type=Path)
    inspect_parser.add_argument("--library", required=True, action="append")
    inspect_parser.add_argument("--language", required=True, choices=("de", "en"))
    inspect_parser.add_argument(
        "--title", help="optional exact title, case-insensitive"
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


def _run_inspect(
    source: Path, libraries: list[str], language: Literal["en", "de"], title: str | None
) -> int:
    from .ingest.infosys import InfoSysError, read_infosys

    try:
        topics = read_infosys(source, libraries=libraries, language=language)
        if title is not None:
            topics = tuple(
                topic for topic in topics if topic.title.casefold() == title.casefold()
            )
    except (InfoSysError, OSError, ValueError):
        print(
            "InfoSys inspection failed: source unreadable, unsupported or over limits",
            file=sys.stderr,
        )
        return 1
    report = {
        "schema_version": "infosys-inspection-1",
        "status": "ok" if topics else "not_found",
        "libraries": libraries,
        "language": language,
        "total": len(topics),
        "truncated": len(topics) > 20,
        "topics": [
            {
                "title": topic.title,
                "library": topic.library,
                "language": topic.language,
                "locator": topic.source.locator,
                "content_hash": topic.source.content_hash,
                "section_counts": dict(
                    Counter(section.kind for section in topic.sections)
                ),
                "help_link_count": len(topic.help_ids),
            }
            for topic in topics[:20]
        ],
        "limitations": [
            "Read-only inspection, not a validated corpus import.",
            "No active-package manifest verification or Help-ID resolution.",
            "Metadata does not prove software-build applicability.",
        ],
    }
    print(json.dumps(report, ensure_ascii=True))
    return 0 if topics else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return _run_init(args.config)
    if args.command == "doctor":
        return _run_doctor(args.config, args.json)
    if args.command == "inspect-infosys":
        return _run_inspect(args.source, args.library, args.language, args.title)
    parser.print_help()
    return 0
