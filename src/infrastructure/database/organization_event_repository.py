from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import and_

from domain.common.identifier import Identifier

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
        correlation_id: str | Identifier | None = None,
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

            corr = correlation_id or event.correlation_id
            corr_graph_id = None
            corr_business_id = None

            if isinstance(corr, Identifier):
                corr_graph_id = str(corr.graph_id)
                corr_business_id = corr.business_id or None
            elif corr is not None:
                corr_business_id = str(corr)

            observations = [
                {
                    "observation_type": (
                        observation.observation_type.value
                    ),
                    "summary": observation.summary,
                    "confidence": observation.confidence,
                    "evidence": list(observation.evidence),
                    "correlation_id": (
                        observation.correlation_id.business_id
                        if observation.correlation_id and observation.correlation_id.business_id
                        else str(observation.correlation_id.graph_id)
                        if observation.correlation_id
                        else corr_business_id
                    ),
                    "occurred_at": (
                        (observation.occurred_at or event.occurred_at).isoformat()
                        if (observation.occurred_at or event.occurred_at)
                        else None
                    ),
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
                correlation_id=corr_graph_id,
                correlation_business_id=corr_business_id,
                occurred_at=event.occurred_at,
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

    def find_by_source(
        self,
        source_type: str,
        source_event_id: str,
    ) -> list[OrganizationEvent]:

        with SessionLocal() as session:

            records = (
                session.query(OrganizationEventModel)
                .filter(
                    and_(
                        OrganizationEventModel.source_type
                        == source_type,
                        OrganizationEventModel.source_event_id
                        == source_event_id,
                    )
                )
                .order_by(
                    OrganizationEventModel.created_at.asc()
                )
                .all()
            )

            return [
                self._to_domain(record)
                for record in records
            ]

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

        observations = []
        event_corr = None
        event_occurred_at = record.occurred_at

        if record.correlation_id or record.correlation_business_id:
            try:
                event_corr = Identifier(
                    graph_id=UUID(record.correlation_id)
                    if record.correlation_id
                    else uuid5(NAMESPACE_URL, f"polis:organization-correlation:{record.correlation_business_id}"),
                    business_id=record.correlation_business_id or "",
                )
            except (TypeError, ValueError):
                event_corr = Identifier(
                    business_id=record.correlation_business_id or "",
                )

        for item in (record.observations or []):
            corr = None
            if item.get("correlation_id"):
                corr = Identifier(
                    business_id=item["correlation_id"]
                )
                if event_corr is None:
                    event_corr = corr

            occurred = None
            if item.get("occurred_at"):
                try:
                    occurred = datetime.fromisoformat(item["occurred_at"])
                    if event_occurred_at is None:
                        event_occurred_at = occurred
                except Exception:
                    pass

            observations.append(
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
                    correlation_id=corr,
                    occurred_at=occurred,
                )
            )

        return OrganizationEvent(
            event_type=OrganizationEventType(
                record.event_type
            ),
            summary=record.summary,
            observations=observations,
            confidence=record.confidence,
            correlation_id=event_corr,
            occurred_at=event_occurred_at,
        )
