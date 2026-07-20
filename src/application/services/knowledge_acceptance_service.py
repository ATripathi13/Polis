from memory.models.knowledge_record import KnowledgeRecord


class KnowledgeAcceptanceService:

    def accept(self, validation_result):

        record = KnowledgeRecord.from_validation(
            validation_result
        )

        print(record)