"""
Public cognitive interface for Polis.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)

from domain.reasoning import (
    Answer,
    Question,
)


class CognitiveEngine(ABC):
    """
    Public application interface for
    interacting with Polis.
    """

    @abstractmethod
    def learn(
        self,
        communication: CommunicationEvent,
    ) -> None:
        """
        Learn from a communication.
        """
        raise NotImplementedError

    @abstractmethod
    def ask(
        self,
        question: Question,
    ) -> Answer:
        """
        Answer a question.
        """
        raise NotImplementedError