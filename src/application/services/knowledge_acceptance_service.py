import logging

from domain.knowledge import KnowledgeRepository
from memory.models.knowledge_record import KnowledgeRecord

logger = logging.getLogger(__name__)


class KnowledgeAcceptanceService:

    def __init__(
        self,
        repository: KnowledgeRepository,
    ) -> None:
        self._repository = repository

    def accept(self, validation_result):

        candidate = validation_result.knowledge

        # Store the validated knowledge in the
        # domain repository used by reasoning.
        self._repository.save(candidate)

        # Create the memory record for the future
        # persistent memory layer.
        record = KnowledgeRecord.from_validation(
            validation_result
        )

        logger.info(
            "Knowledge record accepted (validation_id: %s)",
            getattr(validation_result, "id", "unknown"),
            extra={"operation": "knowledge_accepted"},
        )

        return record