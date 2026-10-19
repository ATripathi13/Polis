from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError

from domain.common.identifier import Identifier

from domain.organization import (
    OrganizationEvent,
    OrganizationEventRepository,
    OrganizationEventType,
)
from domain.organization.identity import derive_source_event_id
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

    TARGET_UNIQUE_CONSTRAINT = "uq_organization_events_source_event_type"

    @classmethod
    def _is_duplicate_constraint_violation(cls, exc: IntegrityError) -> bool:
        """
        Determine whether an IntegrityError was caused by a duplicate violation
        of the target unique constraint uq_organization_events_source_event_type.
        Supports structured driver diagnostics (e.g. exc.orig.diag.constraint_name)
        and bounded message matching when diagnostics are unavailable.
        """
        original = getattr(exc, "orig", None)

        # 1. Structured driver diagnostics (e.g. psycopg2 / PostgreSQL)
        diag = getattr(original, "diag", None)
        constraint_name = getattr(diag, "constraint_name", None)
        if constraint_name == cls.TARGET_UNIQUE_CONSTRAINT:
            return True

        # 2. Driver / SQLAlchemy message matching when diagnostics are unavailable
        candidates: list[str] = []
        if original is not None:
            candidates.append(str(original))
            orig_args = getattr(original, "args", None)
            if orig_args:
                for arg in orig_args:
                    if isinstance(arg, str):
                        candidates.append(arg)
            if diag is not None:
                primary = getattr(diag, "message_primary", None)
                if primary:
                    candidates.append(str(primary))
                detail = getattr(diag, "message_detail", None)
                if detail:
                    candidates.append(str(detail))

        candidates.append(str(exc))
        statement = getattr(exc, "statement", None)
        if statement:
            candidates.append(str(statement))

        for text in candidates:
            if not text:
                continue
            if cls.TARGET_UNIQUE_CONSTRAINT in text:
                return True
            # Also support SQLite format if SQLite is used in test/embedded environments
            if (
                "organization_events." in text
                and "source_type" in text
                and "source_event_id" in text
                and "event_type" in text
            ):
                return True

        return False

    def save(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str | None = None,
        correlation_id: str | Identifier | None = None,
    ) -> None:

        if not source_type.strip():
            raise ValueError("source_type cannot be empty.")

        if source_event_id is not None and not source_event_id.strip():
            raise ValueError("source_event_id cannot be empty.")

        effective_source_event_id = (
            source_event_id.strip() if source_event_id else None
        )
        if not effective_source_event_id:
            derived = derive_source_event_id(
                event,
                source_type=source_type,
                correlation_id=correlation_id,
            )
            if derived:
                effective_source_event_id = derived
            else:
                raise ValueError("source_event_id cannot be empty.")

        with SessionLocal() as session:

            existing = (
                session.query(OrganizationEventModel)
                .filter(
                    and_(
                        OrganizationEventModel.source_type
                        == source_type,
                        OrganizationEventModel.source_event_id
                        == effective_source_event_id,
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
                    "correlation_graph_id": (
                        str(observation.correlation_id.graph_id)
                        if observation.correlation_id
                        else None
                    ),
                    "correlation_business_id": (
                        observation.correlation_id.business_id or None
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
                source_event_id=effective_source_event_id,
                correlation_id=corr_graph_id,
                correlation_business_id=corr_business_id,
                occurred_at=event.occurred_at,
                created_at=datetime.utcnow(),
            )

            session.add(record)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                if not self._is_duplicate_constraint_violation(exc):
                    raise
                return

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

    def find_by_correlation(
        self,
        correlation_id: str | Identifier,
    ) -> list[OrganizationEvent]:
        if isinstance(correlation_id, Identifier):
            if correlation_id.business_id:
                criterion = (
                    OrganizationEventModel.correlation_business_id
                    == correlation_id.business_id
                )
            else:
                criterion = (
                    OrganizationEventModel.correlation_id
                    == str(correlation_id.graph_id)
                )
        else:
            criterion = (
                (OrganizationEventModel.correlation_business_id == correlation_id)
                | (OrganizationEventModel.correlation_id == correlation_id)
            )

        with SessionLocal() as session:
            records = (
                session.query(OrganizationEventModel)
                .filter(criterion)
                .order_by(OrganizationEventModel.created_at.asc())
                .all()
            )
            return [self._to_domain(record) for record in records]

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
            graph_id = item.get("correlation_graph_id")
            business_id = item.get("correlation_business_id")
            legacy_correlation_id = item.get("correlation_id")

            if graph_id or business_id:
                corr = Identifier(
                    graph_id=UUID(graph_id) if graph_id else uuid5(
                        NAMESPACE_URL,
                        f"polis:observation-correlation:{business_id}",
                    ),
                    business_id=business_id or "",
                )
            elif legacy_correlation_id:
                try:
                    corr = Identifier(graph_id=UUID(legacy_correlation_id))
                except (TypeError, ValueError):
                    corr = Identifier(business_id=legacy_correlation_id)

            if corr is not None and event_corr is None:
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
