from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import and_

from domain.organization import (
    OrganizationEvent,
    OrganizationEventRepository,
    OrganizationEventType,
)
from domain.observation import (
    Observation,
    ObservationType,
)

from .connection import SessionLocal
from .models import OrganizationEventModel


class PostgreSQLOrganizationEventRepository(
    OrganizationEventRepository,
):
    """
    PostgreSQL repository for canonical organizational events.
    """

    def save(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str,
    ) -> None:

        if not source_type.strip():
            raise ValueError("source_type cannot be empty.")

        if not source_event_id.strip():
            raise ValueError("source_event_id cannot be empty.")

        with SessionLocal() as session:

            existing = (
                session.query(OrganizationEventModel)
                .filter(
                    and_(
                        OrganizationEventModel.source_type
                        == source_type,
                        OrganizationEventModel.source_event_id
                        == source_event_id,
                        OrganizationEventModel.event_type
                        == event.event_type.value,
                    )
                )
                .first()
            )

            if existing is not None:
                return

            observations = [
                {
                    "observation_type": (
                        observation.observation_type.value
                    ),
                    "summary": observation.summary,
                    "confidence": observation.confidence,
                    "evidence": list(observation.evidence),
                }
                for observation in event.observations
            ]

            record = OrganizationEventModel(
                id=str(uuid4()),
                event_type=event.event_type.value,
                summary=event.summary,
                observations=observations,
                confidence=event.confidence,
                source_type=source_type,
                source_event_id=source_event_id,
                created_at=datetime.utcnow(),
            )

            session.add(record)
            session.commit()

    def find_by_source_event(
        self,
        source_type: str,
        source_event_id: str,
        event_type: OrganizationEventType,
    ) -> OrganizationEvent | None:

        with SessionLocal() as session:

            record = (
                session.query(OrganizationEventModel)
                .filter(
                    and_(
                        OrganizationEventModel.source_type
                        == source_type,
                        OrganizationEventModel.source_event_id
                        == source_event_id,
                        OrganizationEventModel.event_type
                        == event_type.value,
                    )
                )
                .first()
            )

            if record is None:
                return None

            return self._to_domain(record)

    def all(self) -> list[OrganizationEvent]:

        with SessionLocal() as session:

            records = (
                session.query(OrganizationEventModel)
                .order_by(
                    OrganizationEventModel.created_at.asc()
                )
                .all()
            )

            return [
                self._to_domain(record)
                for record in records
            ]

    @staticmethod
    def _to_domain(
        record: OrganizationEventModel,
    ) -> OrganizationEvent:

        observations = [
            Observation(
                observation_type=ObservationType(
                    item["observation_type"]
                ),
                summary=item["summary"],
                confidence=float(
                    item.get("confidence", 1.0)
                ),
                evidence=list(
                    item.get("evidence", [])
                ),
            )
            for item in (record.observations or [])
        ]

        return OrganizationEvent(
            event_type=OrganizationEventType(
                record.event_type
            ),
            summary=record.summary,
            observations=observations,
            confidence=record.confidence,
        )
