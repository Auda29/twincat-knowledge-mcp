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
from .infosys_discovery import (
    DiscoveredInfoSysArchive,
    InfoSysDiscoveryAmbiguityError,
    InfoSysDiscoveryError,
    default_catalog_root,
    discover_infosys_archives,
    select_infosys_archive,
)
from .topic_hierarchy import (
    TopicHierarchyExtractionError,
    extract_topic_hierarchies,
    extract_topic_hierarchy,
)

__all__ = [
    "DiscoveredInfoSysArchive",
    "InfoSysArchiveError",
    "InfoSysDiscoveryAmbiguityError",
    "InfoSysDiscoveryError",
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
    "default_catalog_root",
    "discover_infosys_archives",
    "extract_topic_hierarchies",
    "extract_topic_hierarchy",
    "read_infosys",
    "select_infosys_archive",
]
