from domain.knowledge import KnowledgeRepository
from memory.models.knowledge_record import KnowledgeRecord


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

        print("[KNOWLEDGE ACCEPTED]", record)

        return record