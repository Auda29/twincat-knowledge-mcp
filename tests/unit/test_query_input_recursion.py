"""Malformed in-process graphs must not escape the query error boundary."""

import json

import pytest

from twincat_knowledge.services.query_contracts import (
    CorpusStatusInput,
    GetTopicInput,
    SearchInput,
)
from twincat_knowledge.services.topic_queries import (
    MAX_DOMAIN_RESPONSE_BYTES,
    TopicQueryService,
)


@pytest.mark.parametrize("shape", ["cycle", "deep"])
@pytest.mark.parametrize(
    "method,model,field",
    [
        ("search", SearchInput, "query"),
        ("get_topic", GetTopicInput, "topic_id"),
        ("get_corpus_status", CorpusStatusInput, "snapshot_id"),
    ],
)
def test_recursive_bypass_returns_bounded_error(shape, method, model, field):
    value = []
    if shape == "cycle":
        value.append(value)
    else:
        for _ in range(1100):
            value = [value]
    request = model.model_construct(**{field: value})
    response = getattr(TopicQueryService(None), method)(request)
    assert response.status == "error"
    assert response.next_cursor is None
    assert response.data is None
    payload = json.dumps(response.model_dump(mode="json"), ensure_ascii=True)
    assert len(payload.encode("ascii")) <= MAX_DOMAIN_RESPONSE_BYTES
    assert "RecursionError" not in payload
    assert "Traceback" not in payload


def test_bypass_inspection_exception_is_sanitized():
    class BrokenList(list):
        def __iter__(self):
            raise RuntimeError("private fixture diagnostic")

    request = SearchInput.model_construct(query=BrokenList())
    response = TopicQueryService(None).search(request)
    assert response.status == "error"
    assert "private fixture diagnostic" not in response.model_dump_json()


def test_bypass_inspection_cancellation_propagates():
    class Cancelled(BaseException):
        pass

    class CancelledList(list):
        def __iter__(self):
            raise Cancelled

    with pytest.raises(Cancelled):
        TopicQueryService(None).search(
            SearchInput.model_construct(query=CancelledList())
        )
