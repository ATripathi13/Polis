import logging

from engines.knowledge.domain.indexing import KnowledgeIndexer

logger = logging.getLogger(__name__)


class NullKnowledgeIndexer(KnowledgeIndexer):

    def index(self, candidate):
        logger.debug(
            "NullKnowledgeIndexer received candidate for indexing (candidate_id: %s)",
            getattr(candidate, "id", "unknown"),
            extra={"operation": "null_knowledge_index"},
        )