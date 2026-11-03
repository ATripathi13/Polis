from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from domain.activity import (
    WorkdaySession,
    WorkdaySessionRepository,
    WorkdaySessionStatus,
)
from domain.common.identifier import Identifier

from .connection import SessionLocal
from .models import WorkdaySessionModel


class PostgreSQLWorkdaySessionRepository(WorkdaySessionRepository):
    """
    PostgreSQL repository for WorkdaySession aggregate persistence.
    """

    TARGET_UNIQUE_CONSTRAINT = "uq_workday_sessions_active_person"

    def __init__(
        self,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self._session_factory = session_factory

    def _get_session(self) -> Any:
        factory = self._session_factory or SessionLocal
        return factory()

    @classmethod
    def _is_active_session_violation(cls, exc: IntegrityError) -> bool:
        """
        Positively identify whether an IntegrityError was caused by violating
        the partial unique index 'uq_workday_sessions_active_person'.

        Inspects driver diagnostic attributes (e.g. psycopg2/psycopg3
        exc.orig.diag.constraint_name, asyncpg exc.orig.constraint_name)
        and exact constraint name matching without broad or heuristic substring matches.
        """
        orig = getattr(exc, "orig", None)
        if orig is not None:
            diag = getattr(orig, "diag", None)
            if diag is not None:
                constraint = getattr(diag, "constraint_name", None)
                if constraint is not None:
                    return constraint == cls.TARGET_UNIQUE_CONSTRAINT
            constraint = getattr(orig, "constraint_name", None)
            if constraint is not None:
                return constraint == cls.TARGET_UNIQUE_CONSTRAINT

        # Fallback when structured diagnostics are unavailable on the DBAPI error
        message_sources: list[str] = []
        if orig is not None:
            message_sources.append(str(orig))
            orig_args = getattr(orig, "args", None)
            if orig_args:
                for arg in orig_args:
                    if isinstance(arg, str):
                        message_sources.append(arg)
        message_sources.append(str(exc))

        for msg in message_sources:
            if cls.TARGET_UNIQUE_CONSTRAINT in msg:
                return True

        return False

    @staticmethod
    def _to_domain(record: WorkdaySessionModel) -> WorkdaySession:
        return WorkdaySession(
            person_id=record.person_id,
            person_name=record.person_name,
            work_date=record.work_date,
            started_at=record.started_at,
            timezone=record.timezone,
            status=WorkdaySessionStatus(record.status),
            ended_at=record.ended_at,
            briefing_sent_at=record.briefing_sent_at,
            total_work_minutes=record.total_work_minutes,
            total_break_minutes=record.total_break_minutes,
            start_source_event_id=record.start_source_event_id,
            end_source_event_id=record.end_source_event_id,
            identifier=Identifier(
                graph_id=UUID(record.id),
                business_id=record.business_id,
            ),
            metadata=dict(record.metadata_ or {}),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def save(
        self,
        session: WorkdaySession,
    ) -> None:
        if not isinstance(session, WorkdaySession):
            raise TypeError("session must be an instance of WorkdaySession.")

        with self._get_session() as db_session:
            existing = (
                db_session.query(WorkdaySessionModel)
                .filter(WorkdaySessionModel.id == str(session.identifier.graph_id))
                .first()
            )

            if existing is not None:
                existing.person_id = session.person_id
                existing.person_name = session.person_name
                existing.work_date = session.work_date
                existing.status = session.status.value
                existing.started_at = session.started_at
                existing.ended_at = session.ended_at
                existing.briefing_sent_at = session.briefing_sent_at
                existing.total_work_minutes = session.total_work_minutes
                existing.total_break_minutes = session.total_break_minutes
                existing.timezone = session.timezone
                existing.start_source_event_id = session.start_source_event_id
                existing.end_source_event_id = session.end_source_event_id
                existing.business_id = session.identifier.business_id
                existing.metadata_ = dict(session.metadata)
                existing.created_at = session.created_at
                existing.updated_at = session.updated_at
            else:
                record = WorkdaySessionModel(
                    id=str(session.identifier.graph_id),
                    person_id=session.person_id,
                    person_name=session.person_name,
                    work_date=session.work_date,
                    status=session.status.value,
                    started_at=session.started_at,
                    ended_at=session.ended_at,
                    briefing_sent_at=session.briefing_sent_at,
                    total_work_minutes=session.total_work_minutes,
                    total_break_minutes=session.total_break_minutes,
                    timezone=session.timezone,
                    start_source_event_id=session.start_source_event_id,
                    end_source_event_id=session.end_source_event_id,
                    business_id=session.identifier.business_id,
                    metadata_=dict(session.metadata),
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                )
                db_session.add(record)

            try:
                db_session.commit()
            except IntegrityError as exc:
                db_session.rollback()
                if self._is_active_session_violation(exc):
                    raise ValueError(
                        f"Person '{session.person_id}' already has an active workday session."
                    ) from exc
                raise

    def find_active(
        self,
        person_id: str,
    ) -> WorkdaySession | None:
        if not isinstance(person_id, str) or not person_id.strip():
            raise ValueError("person_id must be a non-empty string.")

        with self._get_session() as db_session:
            record = (
                db_session.query(WorkdaySessionModel)
                .filter(
                    WorkdaySessionModel.person_id == person_id,
                    WorkdaySessionModel.status == WorkdaySessionStatus.ACTIVE.value,
                )
                .first()
            )
            if record is None:
                return None
            return self._to_domain(record)

    def find_latest_for_person(
        self,
        person_id: str,
    ) -> WorkdaySession | None:
        if not isinstance(person_id, str) or not person_id.strip():
            raise ValueError("person_id must be a non-empty string.")

        with self._get_session() as db_session:
            record = (
                db_session.query(WorkdaySessionModel)
                .filter(
                    WorkdaySessionModel.person_id == person_id,
                )
                .order_by(
                    WorkdaySessionModel.started_at.desc(),
                    WorkdaySessionModel.created_at.desc(),
                )
                .first()
            )
            if record is None:
                return None
            return self._to_domain(record)

    def find_for_person_on_date(
        self,
        person_id: str,
        work_date: date,
    ) -> list[WorkdaySession]:
        if not isinstance(person_id, str) or not person_id.strip():
            raise ValueError("person_id must be a non-empty string.")
        if not isinstance(work_date, date) or isinstance(work_date, datetime):
            raise ValueError("work_date must be a valid date.")

        with self._get_session() as db_session:
            records = (
                db_session.query(WorkdaySessionModel)
                .filter(
                    WorkdaySessionModel.person_id == person_id,
                    WorkdaySessionModel.work_date == work_date,
                )
                .order_by(
                    WorkdaySessionModel.started_at.asc(),
                )
                .all()
            )
            return [self._to_domain(record) for record in records]
