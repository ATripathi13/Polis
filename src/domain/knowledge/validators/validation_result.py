"""
Result of validating knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..value_objects import (
    KnowledgeCandidate,
)

from .validation_status import (
    ValidationStatus,
)



@dataclass(frozen=True, slots=True)
class ValidationResult:
    """
    Result returned by a validator.
    """

    status: ValidationStatus

    knowledge: KnowledgeCandidate