"""
Knowledge status enumeration.
"""

from enum import Enum


class KnowledgeStatus(str, Enum):
    """
    Canonical knowledge statuses understood by the Knowledge Agent.
    """

    KNOWN = "known"
    UPDATED = "updated"
    CONFLICTING = "conflicting"
    UNCERTAIN = "uncertain"
    MISSING = "missing"
