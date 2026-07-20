from engines.knowledge.domain.indexing import KnowledgeIndexer


class NullKnowledgeIndexer(KnowledgeIndexer):

    def index(self, candidate):
        print(
            "[INDEXER]",
            candidate.summary,
        )