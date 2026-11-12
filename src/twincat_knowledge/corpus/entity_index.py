"""Bounded in-memory exact indexes over derived, evidence-scoped entities."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from types import MappingProxyType

from twincat_knowledge.domain.entities import TypedEntity
from twincat_knowledge.domain.topics import Topic
from twincat_knowledge.ingest.entities import extract_entities

MAX_TOPICS = 100_000
MAX_ENTITIES = 200_000
MAX_LIMIT = 20
MAX_OFFSET = MAX_ENTITIES
MAX_FILTER_BYTES = 2048
_FILTERS = (
    "kind",
    "name",
    "namespace",
    "library",
    "documented_version",
    "error_code",
    "error_domain",
)
_CASEFOLD = {"kind", "name", "namespace", "library", "error_domain"}


class EntityIndexError(ValueError):
    """An entity-index input is invalid or exceeds a supported bound."""


def _integer(value: int, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EntityIndexError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise EntityIndexError(f"{name} must be between {minimum} and {maximum}")
    return value


def _text(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise EntityIndexError(f"{name} must be a string")
    if (
        not value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > MAX_FILTER_BYTES
    ):
        raise EntityIndexError(f"{name} must be nonblank bounded text without NUL")
    return value.casefold() if name in _CASEFOLD else value


class EntityIndex:
    """Immutable records and field postings built only on first caller demand.

    Construction consumes a bounded iterable once. Callers should construct this
    index lazily from an already validated topic package, rather than persisting
    a second corpus format. Every match retains its own source and snapshot.
    """

    def __init__(
        self,
        topics: Iterable[Topic],
        *,
        max_topics: int = MAX_TOPICS,
        max_entities: int = MAX_ENTITIES,
    ) -> None:
        _integer(max_topics, "max_topics", 1, MAX_TOPICS)
        _integer(max_entities, "max_entities", 1, MAX_ENTITIES)
        topic_ids: set[str] = set()
        entities: dict[str, TypedEntity] = {}
        for count, topic in enumerate(topics, start=1):
            if count > max_topics:
                raise EntityIndexError("topic count exceeds bound")
            if not isinstance(topic, Topic):
                raise EntityIndexError("topics must contain only Topic models")
            if topic.id in topic_ids:
                raise EntityIndexError("duplicate topic id")
            topic_ids.add(topic.id)
            for entity in extract_entities(topic):
                if entity.id in entities:
                    raise EntityIndexError("duplicate entity id")
                entities[entity.id] = entity
                if len(entities) > max_entities:
                    raise EntityIndexError("entity count exceeds bound")
        ordered = tuple(
            sorted(
                entities.values(),
                key=lambda entity: (
                    entity.kind,
                    entity.name.casefold(),
                    entity.topic_id,
                    entity.id,
                ),
            )
        )
        postings: dict[tuple[str, str], list[int]] = defaultdict(list)
        for position, entity in enumerate(ordered):
            for key in _FILTERS:
                value = getattr(entity, key)
                if value is not None:
                    normalized = value.casefold() if key in _CASEFOLD else value
                    postings[(key, normalized)].append(position)
        self._entities = ordered
        self._by_id = MappingProxyType(entities)
        self._postings = MappingProxyType(
            {key: frozenset(positions) for key, positions in postings.items()}
        )

    @property
    def entities(self) -> tuple[TypedEntity, ...]:
        return self._entities

    def get(self, entity_id: str) -> TypedEntity | None:
        return self._by_id.get(_text(entity_id, "entity_id"))

    def find(
        self,
        *,
        kind: str | None = None,
        name: str | None = None,
        namespace: str | None = None,
        library: str | None = None,
        documented_version: str | None = None,
        error_code: str | None = None,
        error_domain: str | None = None,
        limit: int = MAX_LIMIT,
        offset: int = 0,
    ) -> tuple[TypedEntity, ...]:
        """Match exact fields; identifiers fold case, versions/codes stay exact.

        Unknown fields never satisfy a supplied filter. Ambiguous matches across
        topics, libraries, namespaces or snapshots remain separate candidates.
        """
        _integer(limit, "limit", 1, MAX_LIMIT)
        _integer(offset, "offset", 0, MAX_OFFSET)
        requested = {
            "kind": kind,
            "name": name,
            "namespace": namespace,
            "library": library,
            "documented_version": documented_version,
            "error_code": error_code,
            "error_domain": error_domain,
        }
        matches: list[frozenset[int]] = []
        for key, value in requested.items():
            if value is None:
                continue
            normalized = _text(value, key)
            if key == "kind" and normalized not in {"symbol", "library", "error"}:
                raise EntityIndexError("unsupported entity kind")
            matches.append(self._postings.get((key, normalized), frozenset()))
        if not matches:
            return self._entities[offset : offset + limit]
        matches.sort(key=len)
        candidates = matches[0].intersection(*matches[1:])
        return tuple(
            self._entities[index]
            for index in sorted(candidates)[offset : offset + limit]
        )


__all__ = ["EntityIndex", "EntityIndexError", "MAX_ENTITIES", "MAX_LIMIT", "MAX_TOPICS"]
