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
from .topic_hierarchy import (
    TopicHierarchyExtractionError,
    extract_topic_hierarchies,
    extract_topic_hierarchy,
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
    "TopicHierarchyExtractionError",
    "extract_topic_hierarchies",
    "extract_topic_hierarchy",
    "read_infosys",
]
