"""Strict source references and safe package locators."""

import re
from urllib.parse import unquote, urlsplit

from pydantic import Field, StrictStr, field_validator

from .errors import InvalidCanonicalUrlError, UnsafeLocatorError
from .models import Language, OpaqueId, StrictModel

MAX_LOCATOR_LENGTH = 2_048
MAX_TITLE_LENGTH = 4_096
MAX_URL_LENGTH = 2_048


def _validate_locator(value: str) -> str:
    if not value or len(value) > MAX_LOCATOR_LENGTH:
        raise UnsafeLocatorError("locator must be a non-empty bounded relative path")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise UnsafeLocatorError("locator contains a control character")

    decoded = value
    for _ in range(3):
        decoded = unquote(decoded)

    path = decoded.split("#", 1)[0]
    if not path or path.startswith("/") or "\\" in decoded:
        raise UnsafeLocatorError("locator must use a relative POSIX path")
    if re.match(r"^[A-Za-z]:", path) or re.match(
        r"^[A-Za-z][A-Za-z0-9+.-]*:", path
    ):
        raise UnsafeLocatorError("locator must not be a drive path or URI")

    segments = path.split("/")
    if any(segment in {".", ".."} for segment in segments):
        raise UnsafeLocatorError("locator must not contain traversal segments")
    return value


def _validate_canonical_url(value: str) -> str:
    if not value or len(value) > MAX_URL_LENGTH:
        raise InvalidCanonicalUrlError("canonical_url must be a bounded absolute URL")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise InvalidCanonicalUrlError("canonical_url contains a control character")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError as exc:
        raise InvalidCanonicalUrlError("canonical_url is malformed") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not hostname:
        raise InvalidCanonicalUrlError("canonical_url must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise InvalidCanonicalUrlError("canonical_url must not contain credentials")
    return value


class SourceReference(StrictModel):
    """A field-level pointer into an approved source snapshot."""

    source_id: OpaqueId
    snapshot_id: OpaqueId
    topic_id: OpaqueId | None = None
    section_id: OpaqueId | None = None
    title: StrictStr | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    language: Language
    canonical_url: StrictStr | None = Field(default=None, max_length=MAX_URL_LENGTH)
    locator: StrictStr = Field(min_length=1, max_length=MAX_LOCATOR_LENGTH)
    content_hash: StrictStr = Field(pattern=r"^[0-9a-fA-F]{64}$")

    _safe_locator = field_validator("locator")(_validate_locator)
    _safe_canonical_url = field_validator("canonical_url")(_validate_canonical_url)
