"""
Knowledge validator interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..value_objects import (
    KnowledgeCandidate,
)

from .validation_result import (
    ValidationResult,
)


class KnowledgeValidator(ABC):
    """
    Validates knowledge candidates before
    they enter organizational memory.
    """

    @abstractmethod
    def validate(
        self,
        candidate: KnowledgeCandidate,
    ) -> ValidationResult:
        raise NotImplementedError