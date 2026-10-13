"""
Extracts knowledge observations from communications.
"""

from __future__ import annotations

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)

from domain.observation.enums import (
    ObservationType,
)

from domain.observation.rules import (
    ObservationRule,
)

from domain.observation.value_objects import (
    Observation,
)


class KnowledgeObservationRule(
    ObservationRule,
):
    """
    Detects organizational knowledge using
    semantic understanding.

    The rule itself does not contain hardcoded
    phrases for identifying knowledge.
    """

    def __init__(
        self,
        knowledge_understanding,
    ) -> None:

        self._knowledge_understanding = (
            knowledge_understanding
        )

    @property
    def priority(self) -> int:
        return 50

    def extract(
        self,
        communication: CommunicationEvent,
    ) -> list[Observation]:

        text = communication.content.body.strip()

        if not text:
            return []

        result = self._knowledge_understanding.analyze(
            text,
        )

        if not result.get("is_knowledge", False):
            return []

        summary = result.get(
            "summary",
            text,
        )

        confidence = float(
            result.get(
                "confidence",
                0.0,
            )
        )

        is_update = bool(
            result.get("is_update", False)
            or result.get("type") == "update"
            or result.get("lifecycle") == "updated"
        )

        return [
            Observation(
                observation_type=ObservationType.KNOWLEDGE,
                summary=summary,
                confidence=confidence,
                evidence=[
                    communication.source_event_id,
                ],
                correlation_id=getattr(communication, "correlation_id", None),
                occurred_at=getattr(communication, "created_at", None),
                metadata={
                    "subject": result.get("subject", ""),
                    "is_update": is_update,
                    "lifecycle": "updated" if is_update else "discovered",
                },
            )
        ]