from __future__ import annotations

from abc import ABC, abstractmethod


class KnowledgeDetectionResult:
    def __init__(
        self,
        is_knowledge: bool,
        summary: str | None = None,
        confidence: float = 0.0,
    ) -> None:

        self.is_knowledge = is_knowledge
        self.summary = summary
        self.confidence = confidence


class KnowledgeDetector(ABC):

    @abstractmethod
    def detect(
        self,
        text: str,
    ) -> KnowledgeDetectionResult:
        raise NotImplementedError