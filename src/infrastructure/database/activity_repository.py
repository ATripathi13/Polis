from __future__ import annotations

from datetime import datetime
from uuid import UUID

from domain.activity import (
    ActivityEvent,
    ActivityRepository,
    ActivitySource,
    ActivityType,
)
from domain.common.identifier import Identifier

from .connection import SessionLocal
from .models import ActivityEventModel

from sqlalchemy import func
class PostgreSQLActivityRepository(
    ActivityRepository,
):
    """
    PostgreSQL repository for observed activity events.
    """

    def save(
        self,
        event: ActivityEvent,
    ) -> None:
        with SessionLocal() as session:

            if event.source_event_id is not None:
                existing = (
                    session.query(ActivityEventModel)
                    .filter(
                        ActivityEventModel.person_id == event.person_id,
                        ActivityEventModel.source_event_id
                        == event.source_event_id,
                    )
                    .first()
                )

                if existing is not None:
                    return

            record = ActivityEventModel(
                id=str(event.identifier.graph_id),
                person_id=event.person_id,
                person_name=event.person_name,
                activity_type=event.activity_type.value,
                occurred_at=event.occurred_at,
                source=event.source.value,
                source_event_id=event.source_event_id,
                break_type=event.break_type,
                note=event.note,
                created_at=event.created_at,
            )

            session.add(record)
            session.commit()

    def find_for_person(
        self,
        person_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[ActivityEvent]:

        with SessionLocal() as session:

            query = session.query(
                ActivityEventModel
            ).filter(
                ActivityEventModel.person_id == person_id
            )

            if start is not None:
                query = query.filter(
                    ActivityEventModel.occurred_at >= start
                )

            if end is not None:
                query = query.filter(
                    ActivityEventModel.occurred_at <= end
                )

            records = query.order_by(
                ActivityEventModel.occurred_at
            ).all()

            return [
                self._to_domain(record)
                for record in records
            ]

    def find_people_by_name(
        self,
        person_name: str,
    ) -> list[ActivityEvent]:

        normalized_name = person_name.strip()

        if not normalized_name:
            return []

        with SessionLocal() as session:

            records = (
                session.query(ActivityEventModel)
                .filter(
                    func.lower(ActivityEventModel.person_name)
                    == normalized_name.lower()
                )
                .order_by(
                    ActivityEventModel.person_id,
                    ActivityEventModel.occurred_at.desc(),
                    ActivityEventModel.created_at.desc(),
                )
                .all()
            )

            latest_by_person: dict[
                str,
                ActivityEventModel,
            ] = {}

            for record in records:
                if record.person_id not in latest_by_person:
                    latest_by_person[
                        record.person_id
                    ] = record

            return [
                self._to_domain(record)
                for record in latest_by_person.values()
            ]

    def find_currently_on_break(
        self,
    ) -> list[ActivityEvent]:

        latest = self.find_latest_for_people()

        return [
            event
            for event in latest
            if event.activity_type
            == ActivityType.BREAK_START
        ]

    def find_currently_working(
        self,
    ) -> list[ActivityEvent]:

        latest = self.find_latest_for_people()

        return [
            event
            for event in latest
            if event.activity_type
            in {
                ActivityType.WORK_START,
                ActivityType.BREAK_END,
            }
        ]

    def find_currently_off_work(
        self,
    ) -> list[ActivityEvent]:

        latest = self.find_latest_for_people()

        return [
            event
            for event in latest
            if event.activity_type
            == ActivityType.WORK_END
        ]

    def find_latest_for_people(
        self,
    ) -> list[ActivityEvent]:

        with SessionLocal() as session:

            records = (
                session.query(ActivityEventModel)
                .order_by(
                    ActivityEventModel.person_id,
                    ActivityEventModel.occurred_at.desc(),
                    ActivityEventModel.created_at.desc(),
                )
                .all()
            )

            latest_by_person: dict[
                str,
                ActivityEventModel,
            ] = {}

            for record in records:
                if record.person_id not in latest_by_person:
                    latest_by_person[
                        record.person_id
                    ] = record

            return [
                self._to_domain(record)
                for record in latest_by_person.values()
            ]

    @staticmethod
    def _to_domain(
        record: ActivityEventModel,
    ) -> ActivityEvent:

        return ActivityEvent(
            identifier=Identifier(
                graph_id=UUID(record.id),
            ),
            person_id=record.person_id,
            person_name=record.person_name,
            activity_type=ActivityType(
                record.activity_type,
            ),
            occurred_at=record.occurred_at,
            source=ActivitySource(
                record.source,
            ),
            source_event_id=record.source_event_id,
            break_type=record.break_type,
            note=record.note,
            created_at=record.created_at,
        )