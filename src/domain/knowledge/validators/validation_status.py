"""
Knowledge validation status.
"""

from enum import Enum


class ValidationStatus(str, Enum):
    """
    Result of validating a knowledge candidate.
    """

    ACCEPTED = "accepted"

    UPDATED = "updated"

    REJECTED = "rejected"

    CONFLICT = "conflict"