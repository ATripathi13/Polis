"""
Simple implementation of knowledge validation.
"""

from __future__ import annotations

from ..repositories import (
    KnowledgeRepository,
)

from ..value_objects import (
    KnowledgeCandidate,
)

from .knowledge_validator import (
    KnowledgeValidator,
)

from .validation_result import (
    ValidationResult,
)

from .validation_status import (
    ValidationStatus,
)
from engines.knowledge.domain.indexing import (
    KnowledgeIndexer,
)


class SimpleKnowledgeValidator(
    KnowledgeValidator,
):
    """
    First implementation.

    Future versions will support:
    - contradiction detection
    - confidence updates
    - evidence merging
    """

    def __init__(
        self,
        repository: KnowledgeRepository,
        indexer: KnowledgeIndexer,
    ) -> None:

        self._repository = repository
        self._indexer = indexer

    def validate(
        self,
        candidate: KnowledgeCandidate,
    ) -> ValidationResult:

        existing = self._repository.find(
            candidate.subject.identifier,
        )

        if existing is None:

            self._repository.save(candidate)

            return ValidationResult(
                status=ValidationStatus.ACCEPTED,
                knowledge=candidate,
            )

        self._repository.save(candidate)

        return ValidationResult(
            status=ValidationStatus.UPDATED,
            knowledge=candidate,
        )