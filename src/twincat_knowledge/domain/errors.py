"""Typed validation errors used by the provenance/domain models."""


class ProvenanceModelError(ValueError):
    """Base class for invalid provenance data."""


class UnsafeLocatorError(ProvenanceModelError):
    """Raised when a package locator is not safely relative."""


class InvalidCanonicalUrlError(ProvenanceModelError):
    """Raised when a canonical URL is not an allowed HTTP(S) URL."""


class VersionApplicabilityError(ProvenanceModelError):
    """Raised when documented version and applicability contradict."""


class InventoryBalanceError(ProvenanceModelError):
    """Raised when document inventory counts do not reconcile."""


class DuplicateIdentifierError(ProvenanceModelError):
    """Raised when a manifest contains a duplicate snapshot identifier."""
