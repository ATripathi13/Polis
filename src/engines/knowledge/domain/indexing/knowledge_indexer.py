from abc import ABC, abstractmethod

from domain.knowledge.value_objects import KnowledgeCandidate


class KnowledgeIndexer(ABC):

    @abstractmethod
    def index(
        self,
        candidate: KnowledgeCandidate,
    ) -> None:
        raise NotImplementedError