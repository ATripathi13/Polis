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


class OrganizationalIntentObservationRule(
    ObservationRule,
):
    """
    Detects organizational intents not covered by the
    question, knowledge, or operational observation rules.
    """

    def __init__(
        self,
        organizational_intent_understanding,
    ) -> None:
        self._organizational_intent_understanding = (
            organizational_intent_understanding
        )

    @property
    def priority(self) -> int:
        return 60

    def extract(
        self,
        communication: CommunicationEvent,
    ) -> list[Observation]:

        text = communication.content.body.strip()

        if not text:
            return []

        result = self._organizational_intent_understanding.analyze(
            text,
        )

        if not result.get("is_intent", False):
            return []

        type_mapping = {
            "approval": ObservationType.APPROVAL,
            "contradiction": ObservationType.CONTRADICTION,
            "policy_violation": ObservationType.ALERT,
            "summary_request": ObservationType.SUMMARY_REQUEST,
        }

        observation_type = type_mapping.get(
            str(result.get("type", "")).lower()
        )

        if observation_type is None:
            return []

        summary = str(
            result.get("summary", text)
        ).strip()

        if not summary:
            return []

        confidence = float(
            result.get("confidence", 0.0)
        )

        return [
            Observation(
                observation_type=observation_type,
                summary=summary,
                confidence=confidence,
                evidence=[
                    communication.source_event_id,
                ],
            )
        ]
