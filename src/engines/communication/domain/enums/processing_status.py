"""
Communication event processing lifecycle.
"""

from enum import Enum


class ProcessingStatus(str, Enum):
    """Lifecycle states of a communication event."""

    RECEIVED = "received"
    NORMALIZED = "normalized"
    VALIDATED = "validated"
    PERSISTED = "persisted"
    PUBLISHED = "published"
    FAILED = "failed"