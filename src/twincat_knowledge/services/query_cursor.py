"""Small authenticated cursors for stateless bounded service pagination."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Final

MAX_CURSOR_BYTES: Final = 2048
_CURSOR_VERSION: Final = 1


class CursorError(ValueError):
    """A cursor is malformed, forged, stale, or for another request."""


@dataclass(frozen=True, slots=True)
class CursorState:
    tool: str
    generation: str
    query_digest: str
    filters_digest: str
    sections: tuple[str, ...] | None
    sections_digest: str
    limit: int
    position: int


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _b64(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, UnicodeError):
        raise CursorError("cursor is invalid") from None


class QueryCursor:
    """HMAC-authenticated cursor codec owned by one service instance."""

    def __init__(self, secret: bytes) -> None:
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("cursor secret is invalid")
        self._secret = secret

    def encode(
        self,
        *,
        tool: str,
        generation: str,
        query: str | None,
        filters: object,
        selected_sections: tuple[str, ...] | None,
        limit: int,
        position: int,
    ) -> str:
        body = {
            "v": _CURSOR_VERSION,
            "tool": tool,
            "generation": generation,
            "query": _digest(query),
            "filters": _digest(filters),
            "sections": selected_sections,
            "sections_digest": _digest(selected_sections),
            "limit": limit,
            "position": position,
        }
        encoded = _b64(
            json.dumps(
                body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        )
        signature = _b64(
            hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        token = f"{encoded}.{signature}"
        if len(token.encode("ascii")) > MAX_CURSOR_BYTES:
            raise CursorError("cursor state is too large")
        return token

    def decode(
        self,
        token: str,
        *,
        tool: str,
        generation: str,
        query: str | None,
        filters: object,
        selected_sections: tuple[str, ...] | None,
        limit: int,
    ) -> CursorState:
        if not isinstance(token, str) or len(token.encode("utf-8")) > MAX_CURSOR_BYTES:
            raise CursorError("cursor is invalid")
        parts = token.split(".")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise CursorError("cursor is invalid")
        encoded, supplied = parts
        try:
            expected = _b64(
                hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
            )
        except UnicodeError:
            raise CursorError("cursor is invalid") from None
        try:
            valid_signature = hmac.compare_digest(supplied, expected)
        except (TypeError, ValueError):
            raise CursorError("cursor is invalid") from None
        if not valid_signature:
            raise CursorError("cursor is invalid")
        try:
            raw = json.loads(_unb64(encoded).decode("utf-8"))
            if not isinstance(raw, dict) or set(raw) != {
                "v",
                "tool",
                "generation",
                "query",
                "filters",
                "sections",
                "sections_digest",
                "limit",
                "position",
            }:
                raise ValueError
            if not all(
                isinstance(raw[key], str)
                for key in ("tool", "generation", "query", "filters", "sections_digest")
            ):
                raise ValueError
            if isinstance(raw["v"], bool) or not isinstance(raw["v"], int):
                raise ValueError
            if isinstance(raw["limit"], bool) or not isinstance(raw["limit"], int):
                raise ValueError
            if (
                raw["v"] != _CURSOR_VERSION
                or raw["tool"] != tool
                or raw["generation"] != generation
                or raw["query"] != _digest(query)
                or raw["filters"] != _digest(filters)
                or raw["limit"] != limit
            ):
                raise ValueError
            sections_raw = raw["sections"]
            if sections_raw is not None:
                if not isinstance(sections_raw, list) or not all(
                    isinstance(item, str) for item in sections_raw
                ):
                    raise ValueError
                sections = tuple(sections_raw)
                if sections != selected_sections and selected_sections is not None:
                    raise ValueError
            else:
                sections = None
            if raw["sections_digest"] != _digest(sections):
                raise ValueError
            position = raw["position"]
            if (
                isinstance(position, bool)
                or not isinstance(position, int)
                or position < 1
            ):
                raise ValueError
        except (CursorError, json.JSONDecodeError, UnicodeError, TypeError, ValueError):
            raise CursorError(
                "cursor is invalid or does not match this request"
            ) from None
        return CursorState(
            tool=tool,
            generation=generation,
            query_digest=raw["query"],
            filters_digest=raw["filters"],
            sections=sections,
            sections_digest=raw["sections_digest"],
            limit=limit,
            position=position,
        )


__all__ = ["CursorError", "CursorState", "MAX_CURSOR_BYTES", "QueryCursor"]
