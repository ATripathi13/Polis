from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from domain.activity import (
    PersonPreference,
    PersonPreferenceRepository,
    SignoffReminderPolicy,
)
from domain.common.identifier import Identifier

from .connection import SessionLocal
from .models import PersonPreferenceModel


class PostgreSQLPersonPreferenceRepository(PersonPreferenceRepository):
    """
    PostgreSQL repository for PersonPreference aggregate persistence.
    """

    TARGET_UNIQUE_CONSTRAINT = "uq_person_preferences_person_id"

    def __init__(
        self,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self._session_factory = session_factory

    def _get_session(self) -> Any:
        factory = self._session_factory or SessionLocal
        return factory()

    @classmethod
    def _is_person_preference_violation(cls, exc: IntegrityError) -> bool:
        """
        Positively identify whether an IntegrityError was caused by violating
        the named unique constraint 'uq_person_preferences_person_id'.

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
    def _to_domain(record: PersonPreferenceModel) -> PersonPreference:
        return PersonPreference(
            person_id=record.person_id,
            reminders_after_signoff=SignoffReminderPolicy(
                record.reminders_after_signoff
            ),
            preferred_timezone=record.preferred_timezone,
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
        preference: PersonPreference,
    ) -> None:
        if not isinstance(preference, PersonPreference):
            raise TypeError("preference must be an instance of PersonPreference.")

        with self._get_session() as db_session:
            existing = (
                db_session.query(PersonPreferenceModel)
                .filter(PersonPreferenceModel.person_id == preference.person_id)
                .first()
            )

            if existing is not None:
                existing.reminders_after_signoff = (
                    preference.reminders_after_signoff.value
                )
                existing.preferred_timezone = preference.preferred_timezone
                existing.business_id = preference.identifier.business_id
                existing.metadata_ = dict(preference.metadata)
                existing.created_at = preference.created_at
                existing.updated_at = preference.updated_at
            else:
                record = PersonPreferenceModel(
                    id=str(preference.identifier.graph_id),
                    person_id=preference.person_id,
                    reminders_after_signoff=preference.reminders_after_signoff.value,
                    preferred_timezone=preference.preferred_timezone,
                    business_id=preference.identifier.business_id,
                    metadata_=dict(preference.metadata),
                    created_at=preference.created_at,
                    updated_at=preference.updated_at,
                )
                db_session.add(record)

            try:
                db_session.commit()
            except IntegrityError as exc:
                db_session.rollback()
                if self._is_person_preference_violation(exc):
                    raise ValueError(
                        f"Preference for person '{preference.person_id}' already exists or a concurrent write occurred."
                    ) from exc
                raise

    def find_by_person_id(
        self,
        person_id: str,
    ) -> PersonPreference | None:
        if not isinstance(person_id, str) or not person_id.strip():
            raise ValueError("person_id must be a non-empty string.")

        with self._get_session() as db_session:
            record = (
                db_session.query(PersonPreferenceModel)
                .filter(PersonPreferenceModel.person_id == person_id)
                .first()
            )
            if record is None:
                return None
            return self._to_domain(record)

    def get_or_default(
        self,
        person_id: str,
    ) -> PersonPreference:
        if not isinstance(person_id, str) or not person_id.strip():
            raise ValueError("person_id must be a non-empty string.")

        found = self.find_by_person_id(person_id)
        if found is not None:
            return found

        return PersonPreference.create(person_id=person_id)
