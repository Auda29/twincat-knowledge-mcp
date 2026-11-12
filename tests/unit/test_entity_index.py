"""Synthetic-only bounded typed-entity index checks."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from twincat_knowledge.corpus.entity_index import EntityIndex, EntityIndexError
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic, TopicMetadata


def _topic(number: int, *, version: str = "1.0", domain: str = "ADS") -> Topic:
    source = SourceReference(
        source_id="synthetic",
        snapshot_id=f"snapshot-{number}",
        topic_id=f"help-{number}",
        title="FB_Demo",
        language="en",
        locator=f"synthetic/{number}.html",
        content_hash="a" * 64,
    )
    return Topic(
        id=f"topic-{number}",
        title="FB_Demo",
        original_topic_id=f"help-{number}",
        library="routing",
        language="en",
        source=source,
        metadata=(
            TopicMetadata(name="Library", content=f"Lib{number}"),
            TopicMetadata(name="Namespace", content=f"Ns{number}"),
            TopicMetadata(name="LibraryVersion", content=version),
        ),
        sections=(
            Section(
                id=f"code-{number}",
                kind="code",
                language="st",
                code="FUNCTION_BLOCK FB_Demo\nEND_FUNCTION_BLOCK",
                source=source.model_copy(update={"section_id": f"code-{number}"}),
            ),
            Section(
                id=f"table-{number}",
                kind="table",
                rows=(
                    ("Error code", "Error domain", "Description"),
                    ("0x0001", domain, "Text"),
                ),
                source=source.model_copy(update={"section_id": f"table-{number}"}),
            ),
        ),
    )


def test_index_preserves_ambiguous_names_versions_namespaces_and_snapshots() -> None:
    index = EntityIndex((_topic(1), _topic(2, version="2.0")))
    matches = index.find(kind="symbol", name="fb_demo")
    assert len(matches) == 2
    assert {e.library for e in matches} == {"Lib1", "Lib2"}
    assert {e.documented_version for e in matches} == {"1.0", "2.0"}
    assert (
        len(index.find(kind="symbol", name="FB_DEMO", library="lib1", namespace="ns1"))
        == 1
    )
    assert len(index.find(kind="symbol", documented_version="2.0")) == 1
    assert index.find(name="Demo") == ()
    assert index.find(documented_version="2") == ()
    assert index.get(matches[0].id) == matches[0]
    assert index.get("missing") is None
    assert isinstance(index.entities, tuple)


def test_error_code_filter_is_exact_and_domain_filter_separates_equal_codes() -> None:
    index = EntityIndex((_topic(1), _topic(2, domain="NC")))
    assert len(index.find(kind="error", error_code="0x0001")) == 2
    (nc,) = index.find(kind="error", error_code="0x0001", error_domain="nc")
    assert nc.error_domain == "NC"
    assert index.find(kind="error", error_code="1") == ()
    assert index.find(kind="error", error_code="0X0001") == ()


def test_order_is_stable_across_topic_input_order_and_pages_are_bounded() -> None:
    first = EntityIndex((_topic(1), _topic(2)))
    second = EntityIndex((_topic(2), _topic(1)))
    assert first.entities == second.entities
    assert first.find(limit=2, offset=1) == first.entities[1:3]
    assert (
        first.find(kind="symbol", limit=1, offset=1) == first.find(kind="symbol")[1:2]
    )


@pytest.mark.parametrize(
    "options",
    [
        {"limit": 0},
        {"limit": 21},
        {"limit": True},
        {"offset": -1},
        {"offset": 200001},
        {"offset": False},
        {"kind": "device"},
        {"name": ""},
        {"name": "\x00"},
        {"library": "x" * 2049},
        {"error_domain": 123},
    ],
)
def test_invalid_queries_fail_explicitly(options: dict[str, object]) -> None:
    with pytest.raises(EntityIndexError):
        EntityIndex(()).find(**options)  # type: ignore[arg-type]


def test_topic_and_entity_budgets_and_duplicate_ids_fail_closed() -> None:
    with pytest.raises(EntityIndexError, match="duplicate topic"):
        EntityIndex((_topic(1), _topic(1)))
    with pytest.raises(EntityIndexError, match="entity count"):
        EntityIndex((_topic(1),), max_entities=1)
    consumed: list[int] = []

    def topics() -> Iterator[Topic]:
        for number in range(100):
            consumed.append(number)
            yield _topic(number)

    with pytest.raises(EntityIndexError, match="topic count"):
        EntityIndex(topics(), max_topics=1)
    assert consumed == [0, 1]
