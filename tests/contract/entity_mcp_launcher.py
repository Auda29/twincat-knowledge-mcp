"""Dedicated synthetic typed-entity stdio fixture."""

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from topic_mcp_launcher import _source, _topic

from twincat_knowledge.corpus.manifest import CorpusManifest, InventoryBalance
from twincat_knowledge.corpus.topic_package import build_topic_package
from twincat_knowledge.corpus.topic_package_load import load_topic_package
from twincat_knowledge.domain.identity import canonical_section_id
from twincat_knowledge.domain.models import EntityCounts
from twincat_knowledge.domain.topics import Section, TopicMetadata
from twincat_knowledge.mcp_api.topic_server import run_topic_stdio
from twincat_knowledge.services.topic_queries import TopicQueryService


def main():
    topics = []
    for number in range(2):
        base = _topic(number)
        source = base.source.model_copy(update={"title": "Run"})
        sid = canonical_section_id(base.id, 0)
        declaration = Section(
            id=sid,
            kind="code",
            code="FUNCTION Run : BOOL\nEND_FUNCTION",
            language="ST",
            source=source.model_copy(update={"section_id": sid}),
        )
        tid = canonical_section_id(base.id, 1)
        table = Section(
            id=tid,
            kind="table",
            rows=(
                ("Error code", "Description", "Error domain"),
                ("0x10", "Fault", f"Domain{number}"),
            ),
            source=source.model_copy(update={"section_id": tid}),
        )
        topics.append(
            base.model_copy(
                update={
                    "title": "Run",
                    "source": source,
                    "sections": (declaration, table),
                    "metadata": (
                        TopicMetadata(name="Library", content=f"Lib{number}"),
                        TopicMetadata(name="Namespace", content=f"NS{number}"),
                    ),
                }
            )
        )
    topics = tuple(topics)
    manifest = CorpusManifest(
        package_schema_version="1.0",
        snapshot_id="entity-fixture",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        sources=(_source("en", "fixture-en"),),
        inventory=InventoryBalance(
            documents_total=2,
            documents_imported=2,
            documents_skipped=0,
            documents_failed=0,
        ),
        entity_counts=EntityCounts(topics=2, sections=4),
    )
    with TemporaryDirectory(prefix="entity-mcp-contract-") as directory:
        root = Path(directory)
        result = build_topic_package(root / "package", manifest, topics)
        (root / "cache").mkdir()
        loaded = load_topic_package(
            result.path,
            expected_manifest_sha256=result.manifest_sha256,
            cache_dir=root / "cache",
        )
        try:
            run_topic_stdio(TopicQueryService(loaded))
        finally:
            loaded.close()


if __name__ == "__main__":
    main()
