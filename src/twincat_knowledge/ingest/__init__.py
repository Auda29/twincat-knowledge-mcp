"""Read-only source adapters."""

from .infosys import (
    InfoSysArchiveError,
    InfoSysError,
    InfoSysLimitError,
    InfoSysLimits,
    InfoSysMetadata,
    InfoSysReader,
    InfoSysSection,
    InfoSysTopic,
    InfoSysXmlError,
    UnsafeArchiveError,
    XMLDepthLimitError,
    read_infosys,
)

__all__ = [
    "InfoSysArchiveError",
    "InfoSysError",
    "InfoSysLimitError",
    "InfoSysLimits",
    "InfoSysMetadata",
    "InfoSysReader",
    "InfoSysSection",
    "InfoSysTopic",
    "InfoSysXmlError",
    "UnsafeArchiveError",
    "XMLDepthLimitError",
    "read_infosys",
]
