"""
Base organizational reasoning service.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)

from domain.reasoning.value_objects import (
    ReasoningDecision,
    Answer,
    Question,
)

class ReasoningService(ABC):
    """
    Organizational reasoning interface.

    Every reasoning implementation must
    return a ReasoningDecision.
    """

    @abstractmethod
    def reason(
        self,
        communication: CommunicationEvent,
    ) -> ReasoningDecision:
        """
        Determine what Polis should do.
        """
        raise NotImplementedError
    
    """
    Base interface for answering
    organizational questions.
    """

    def answer(
        self,
        question: Question,
    ) -> Answer:
        """
        Answer a question using
        organizational knowledge.
        """
        raise NotImplementedError