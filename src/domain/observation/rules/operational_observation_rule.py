from __future__ import annotations

from domain.observation.rules.timestamp_utils import resolve_occurred_at

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


class OperationalObservationRule(
    ObservationRule,
):
    """
    Detects operational tasks, decisions, and risks
    from organizational communications.
    """

    def __init__(
        self,
        operational_understanding,
    ) -> None:
        self._operational_understanding = (
            operational_understanding
        )

    @property
    def priority(self) -> int:
        return 40

    def extract(
        self,
        communication: CommunicationEvent,
    ) -> list[Observation]:

        text = communication.content.body.strip()

        if not text:
            return []

        result = self._operational_understanding.analyze(
            text,
        )

        if not result.get("is_operational", False):
            return []

        type_mapping = {
            "task": ObservationType.TASK,
            "decision": ObservationType.DECISION,
            "risk": ObservationType.RISK,
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

        metadata = {}
        if "status" in result:
            metadata["status"] = result["status"]
        if "action" in result:
            metadata["action"] = result["action"]
        if "lifecycle" in result:
            metadata["lifecycle"] = result["lifecycle"]

        return [
            Observation(
                observation_type=observation_type,
                summary=summary,
                confidence=confidence,
                evidence=[
                    communication.source_event_id,
                ],
                correlation_id=getattr(communication, "correlation_id", None),
                occurred_at=resolve_occurred_at(communication),
                metadata=metadata,
            )
        ]
