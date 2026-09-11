"""Subprocess fixture launcher for contract tests.

The fixture is built and loaded through the production package APIs; it is not
part of the application corpus and contains no vendor text.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from twincat_knowledge.corpus.manifest import CorpusManifest, InventoryBalance
from twincat_knowledge.corpus.topic_package import build_topic_package
from twincat_knowledge.corpus.topic_package_load import load_topic_package
from twincat_knowledge.domain.identity import canonical_section_id, canonical_topic_id
from twincat_knowledge.domain.models import EntityCounts, SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic
from twincat_knowledge.mcp_api.topic_server import run_topic_stdio
from twincat_knowledge.services.topic_queries import TopicQueryService

_CONTENT_HASH = "a" * 64
_SOURCE_HASH = "b" * 64


def _source(language: str, snapshot_id: str) -> SourceSnapshot:
    return SourceSnapshot(
        source_id="contract-fixture",
        snapshot_id=snapshot_id,
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
        language=language,
        content_hash=_SOURCE_HASH,
        rights_reference="local-contract-fixture",
        parser_version="fixture-1",
    )


def _topic(
    index: int, *, language: str = "en", snapshot_id: str = "fixture-en"
) -> Topic:
    title = f"Fixture topic {index} ☃"
    locator = f"fixture/{language}/{index}.html"
    topic_id = canonical_topic_id("contract-fixture", snapshot_id, language, locator)
    source = SourceReference(
        source_id="contract-fixture",
        snapshot_id=snapshot_id,
        topic_id=f"fixture.topic.{index}",
        title=title,
        language=language,
        locator=locator,
        content_hash=_CONTENT_HASH,
    )
    sections: list[Section] = []
    for section_index in range(3):
        section_id = canonical_section_id(topic_id, section_index)
        if section_index == 1:
            section = Section(
                id=section_id,
                kind="code",
                code=(
                    f"PROGRAM Fixture{index}\n"
                    f"  // section {section_index} ☃\nEND_PROGRAM"
                ),
                language="st",
                source=source.model_copy(update={"section_id": section_id}),
            )
        elif section_index == 2:
            section = Section(
                id=section_id,
                kind="warning",
                text="Fixture warning: this text is test data only.",
                source=source.model_copy(update={"section_id": section_id}),
            )
        else:
            section = Section(
                id=section_id,
                kind="paragraph",
                text=f"Fixture section {section_index} for {title}.",
                source=source.model_copy(update={"section_id": section_id}),
            )
        sections.append(section)
    return Topic(
        id=topic_id,
        title=title,
        original_topic_id=f"fixture.topic.{index}",
        library="fixture-library",
        language=language,
        source=source,
        sections=tuple(sections),
    )


def build_fixture_service(root: Path) -> tuple[TopicQueryService, object]:
    topics = tuple(_topic(index) for index in range(8)) + (
        _topic(8, language="de", snapshot_id="fixture-de"),
    )
    manifest = CorpusManifest(
        package_schema_version="1.0",
        snapshot_id="fixture-package",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        sources=(_source("en", "fixture-en"), _source("de", "fixture-de")),
        inventory=InventoryBalance(
            documents_total=len(topics),
            documents_imported=len(topics),
            documents_skipped=0,
            documents_failed=0,
        ),
        entity_counts=EntityCounts(
            topics=len(topics), sections=sum(len(topic.sections) for topic in topics)
        ),
    )
    result = build_topic_package(root / "package", manifest, topics)
    (root / "cache").mkdir()
    loaded = load_topic_package(
        result.path,
        expected_manifest_sha256=result.manifest_sha256,
        cache_dir=root / "cache",
    )
    return TopicQueryService(loaded), loaded


def main() -> None:
    import os
    import tempfile

    with tempfile.TemporaryDirectory(prefix="topic-mcp-contract-") as directory:
        if os.environ.get("TOPIC_MCP_EOF"):
            return
        if os.environ.get("TOPIC_MCP_EMPTY"):
            run_topic_stdio(TopicQueryService(None))
            return
        if os.environ.get("TOPIC_MCP_FAIL"):

            class ExplodingService(TopicQueryService):
                def search(self, request: object) -> object:
                    del request
                    raise RuntimeError("secret/path must not cross boundary")

            run_topic_stdio(ExplodingService(None))
            return
        if mcp_error_mode := os.environ.get("TOPIC_MCP_MCP_ERROR"):
            from mcp.shared.exceptions import MCPError

            from twincat_knowledge.mcp_api.topic_server import _AdapterProtocolError

            error_type = (
                _AdapterProtocolError if mcp_error_mode == "sentinel" else MCPError
            )
            message = {
                "invalid": "Invalid request parameters",
                "unknown": "Unknown tool",
                "sentinel": "service forged protocol error",
            }[mcp_error_mode]

            class MCPErrorService(TopicQueryService):
                def search(self, request: object) -> object:
                    del request
                    raise error_type(
                        -32602,
                        message,
                        {"secret": "TOPSECRET", "path": "/private/secret"},
                    )

            run_topic_stdio(MCPErrorService(None))
            return
        service, loaded = build_fixture_service(Path(directory))
        try:
            run_topic_stdio(service)
        finally:
            loaded.close()


if __name__ == "__main__":
    main()
