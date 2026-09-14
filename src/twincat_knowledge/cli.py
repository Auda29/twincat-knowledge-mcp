"""Command-line entry point for the package foundation."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Literal
from uuid import uuid4

from . import __version__
from .config import (
    ConfigError,
    ConfigFileExistsError,
    create_default_config,
    diagnose_config,
    load_snapshot_settings,
    render_diagnosis,
)
from .corpus.topic_snapshot import SnapshotReference, SnapshotState


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
    corpus_parser = commands.add_parser("corpus", help="operator corpus commands")
    corpus_commands = corpus_parser.add_subparsers(dest="corpus_command", required=True)
    validate_parser = corpus_commands.add_parser(
        "validate", help="verify a pinned topic package without activating it"
    )
    validate_parser.add_argument("package_dir", type=Path)
    validate_parser.add_argument("--expected-manifest-sha256", required=True)
    validate_parser.add_argument("--cache-dir", required=True, type=Path)
    validate_parser.add_argument("--json", action="store_true")
    for name, help_text in (
        ("activate", "verify and select a topic package snapshot"),
        ("rollback", "restore the stored previous topic package snapshot"),
        ("list", "show the selected snapshot state without package scanning"),
    ):
        snapshot_parser = corpus_commands.add_parser(name, help=help_text)
        if name == "activate":
            snapshot_parser.add_argument("package_dir", type=Path)
            snapshot_parser.add_argument("--expected-manifest-sha256", required=True)
        snapshot_parser.add_argument("--config", type=Path)
        snapshot_parser.add_argument("--state-dir", type=Path)
        snapshot_parser.add_argument("--cache-dir", type=Path)
        snapshot_parser.add_argument("--json", action="store_true")
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
        # Inspection does not create an approved or reusable source snapshot.
        # Per-invocation identities stay internal to this metadata-only command.
        inspection_id = f"inspection-{uuid4().hex}"
        topics = read_infosys(
            source,
            libraries=libraries,
            language=language,
            source_id=inspection_id,
            snapshot_id=inspection_id,
        )
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


def _run_corpus_validate(
    package: Path, fingerprint: str, cache: Path, as_json: bool
) -> int:
    from .corpus.topic_package_load import TopicPackageLoadError, load_topic_package

    try:
        with load_topic_package(
            package, expected_manifest_sha256=fingerprint, cache_dir=cache
        ) as loaded:
            report = {
                "schema_version": "corpus-validation-1",
                "status": "valid",
                "scope": "topic_package",
                "manifest_sha256": fingerprint,
                "topic_count": loaded.summary.topic_count,
                "section_count": loaded.summary.section_count,
                "language_counts": dict(loaded.summary.language_counts),
                "limitations": [
                    "Integrity and topic consistency, "
                    "not source authenticity or rights.",
                    "No package activation or full-product acceptance.",
                ],
            }
    except TopicPackageLoadError:
        message = "Topic package validation failed."
        if as_json:
            print(
                json.dumps(
                    {
                        "schema_version": "corpus-validation-1",
                        "status": "error",
                        "scope": "topic_package",
                        "message": message,
                    }
                )
            )
        else:
            print(message, file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(report, ensure_ascii=True))
    else:
        print(
            f"Topic package valid: {report['topic_count']} topics, "
            f"{report['section_count']} sections."
        )
        print("Integrity and topic consistency, not source authenticity or rights.")
        print("No package activation or full-product acceptance.")
    return 0


_SNAPSHOT_ERROR = (
    "Snapshot operation failed; re-read state before retrying because the "
    "outcome may be ambiguous."
)


def _snapshot_reference_report(
    reference: SnapshotReference | None,
) -> dict[str, str] | None:
    if reference is None:
        return None
    # SnapshotReference is deliberately converted to an allow-listed shape;
    # package_path, rights metadata, and other operator details never escape.
    return {
        "snapshot_id": reference.snapshot_id,
        "manifest_sha256": reference.manifest_sha256,
        "availability": "state_only_unverified",
    }


def _snapshot_report(
    state: SnapshotState, *, operation: str, status: str = "ok"
) -> dict[str, object]:
    return {
        "schema_version": "snapshot-operation-1",
        "status": status,
        "scope": "selected_snapshot_state",
        "operation": operation,
        "format_version": state.format_version,
        "active": _snapshot_reference_report(state.active),
        "previous": _snapshot_reference_report(state.previous),
        "limitations": [
            "State references are selected metadata; package availability is "
            "unverified.",
            "This does not prove source authenticity, rights, or product readiness.",
        ],
    }


def _print_snapshot_error(*, as_json: bool, message: str = _SNAPSHOT_ERROR) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": "snapshot-operation-1",
                    "status": "error",
                    "scope": "selected_snapshot_state",
                    "message": message,
                },
                ensure_ascii=True,
            )
        )
    else:
        print(message, file=sys.stderr)
    return 1


def _print_snapshot_report(report: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return
    print(f"Snapshot state: {report['status']}")
    if "operation" in report:
        print(f"Operation: {report['operation']}")
    print(f"Scope: {report['scope']}")
    for label, reference in (
        ("active", report.get("active")),
        ("previous", report.get("previous")),
    ):
        if reference is None:
            print(f"{label}: none")
        else:
            if isinstance(reference, dict):
                print(
                    f"{label}: {reference['snapshot_id']} "
                    f"(manifest {reference['manifest_sha256']}; state-only/unverified)"
                )
    limitations = report.get("limitations", ())
    if isinstance(limitations, list):
        for limitation in limitations:
            print(f"limitation: {limitation}")


def _run_snapshot_mutation(
    *,
    operation: str,
    config: Path | None,
    state_dir: Path | None,
    cache_dir: Path | None,
    package: Path | None = None,
    fingerprint: str | None = None,
    as_json: bool,
) -> int:
    from .corpus import topic_snapshot

    try:
        settings = load_snapshot_settings(
            config,
            state_dir=state_dir,
            cache_dir=cache_dir,
            require_cache=True,
        )
        if settings.cache_dir is None:
            raise ConfigError("snapshot paths are not configured")
        if operation == "activate":
            if package is None or fingerprint is None:
                raise ConfigError("snapshot arguments are incomplete")
            returned = topic_snapshot.activate_snapshot(
                settings.state_dir,
                package,
                expected_manifest_sha256=fingerprint,
                cache_dir=settings.cache_dir,
            )
        else:
            returned = topic_snapshot.rollback_snapshot(
                settings.state_dir, cache_dir=settings.cache_dir
            )
        # A successful pointer call is not an acknowledgement until the exact
        # state is read back.  Never emit a success report before this check.
        readback = topic_snapshot.read_snapshot_state(settings.state_dir)
        if readback != returned:
            return _print_snapshot_error(as_json=as_json)
        _print_snapshot_report(
            _snapshot_report(readback, operation=operation), as_json=as_json
        )
        return 0
    except Exception:
        return _print_snapshot_error(as_json=as_json)


def _run_snapshot_list(
    *,
    config: Path | None,
    state_dir: Path | None,
    cache_dir: Path | None,
    as_json: bool,
) -> int:
    del cache_dir  # Listing is state-only and must not touch the cache.
    from .corpus import topic_snapshot

    try:
        settings = load_snapshot_settings(
            config, state_dir=state_dir, cache_dir=None, require_cache=False
        )
        try:
            state = topic_snapshot.read_snapshot_state(settings.state_dir)
        except topic_snapshot.SnapshotNotFound:
            report: dict[str, object] = {
                "schema_version": "snapshot-list-1",
                "status": "not_available",
                "scope": "selected_snapshot_state",
                "active": None,
                "previous": None,
                "limitations": [
                    "No active selection is recorded in the selected state directory.",
                    "This command does not scan packages or claim full readiness.",
                ],
            }
        else:
            report = _snapshot_report(state, operation="list", status="not_ready")
            report["schema_version"] = "snapshot-list-1"
        _print_snapshot_report(report, as_json=as_json)
        return 0
    except Exception:
        return _print_snapshot_error(
            as_json=as_json, message="Snapshot state could not be read."
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return _run_init(args.config)
    if args.command == "doctor":
        return _run_doctor(args.config, args.json)
    if args.command == "inspect-infosys":
        return _run_inspect(args.source, args.library, args.language, args.title)
    if args.command == "corpus" and args.corpus_command == "validate":
        return _run_corpus_validate(
            args.package_dir, args.expected_manifest_sha256, args.cache_dir, args.json
        )
    if args.command == "corpus" and args.corpus_command in {"activate", "rollback"}:
        return _run_snapshot_mutation(
            operation=args.corpus_command,
            config=args.config,
            state_dir=args.state_dir,
            cache_dir=args.cache_dir,
            package=getattr(args, "package_dir", None),
            fingerprint=getattr(args, "expected_manifest_sha256", None),
            as_json=args.json,
        )
    if args.command == "corpus" and args.corpus_command == "list":
        return _run_snapshot_list(
            config=args.config,
            state_dir=args.state_dir,
            cache_dir=args.cache_dir,
            as_json=args.json,
        )
    parser.print_help()
    return 0
