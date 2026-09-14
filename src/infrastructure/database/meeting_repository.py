"""
PostgreSQL repository for meeting memory.
"""

from __future__ import annotations

from uuid import UUID

from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import MeetingModel

from domain.common.identifier import Identifier
from domain.meetings import Meeting
from domain.meetings.repositories import MeetingRepository


class PostgreSQLMeetingRepository(MeetingRepository):
    """
    PostgreSQL implementation of MeetingRepository.
    """

    def save(
        self,
        meeting: Meeting,
    ) -> None:

        with SessionLocal() as session:

            record = session.get(
                MeetingModel,
                str(meeting.graph_id),
            )

            if record is None:

                record = MeetingModel(
                    id=str(meeting.graph_id),
                    external_id=meeting.external_id,
                    title=meeting.title,
                    source=meeting.source,
                    started_at=meeting.started_at,
                    ended_at=meeting.ended_at,
                    created_at=meeting.created_at,
                    metadata_=meeting.metadata,
                )

                session.add(record)

            else:

                record.external_id = meeting.external_id
                record.title = meeting.title
                record.source = meeting.source
                record.started_at = meeting.started_at
                record.ended_at = meeting.ended_at
                record.metadata_ = meeting.metadata

            session.commit()

    def find(
        self,
        identifier: str,
    ) -> Meeting | None:

        with SessionLocal() as session:

            record = session.get(
                MeetingModel,
                identifier,
            )

            if record is None:
                return None

            return self._to_domain(record)

    def find_by_external_id(
        self,
        external_id: str,
    ) -> Meeting | None:

        with SessionLocal() as session:

            record = (
                session.query(MeetingModel)
                .filter(
                    MeetingModel.external_id == external_id
                )
                .first()
            )

            if record is None:
                return None

            return self._to_domain(record)

    @staticmethod
    def _to_domain(
        record: MeetingModel,
    ) -> Meeting:

        return Meeting(
            identifier=Identifier(
                graph_id=UUID(record.id),
            ),
            external_id=record.external_id,
            title=record.title,
            source=record.source,
            started_at=record.started_at,
            ended_at=record.ended_at,
            metadata=dict(record.metadata_ or {}),
        )
