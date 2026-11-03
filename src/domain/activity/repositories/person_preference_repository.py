from __future__ import annotations

from abc import ABC, abstractmethod

from ..aggregates.person_preference import PersonPreference


class PersonPreferenceRepository(ABC):
    """
    Repository contract for PersonPreference aggregate persistence.
    """

    @abstractmethod
    def save(
        self,
        preference: PersonPreference,
    ) -> None:
        """
        Persist a new or modified PersonPreference aggregate.
        """
        raise NotImplementedError

    @abstractmethod
    def find_by_person_id(
        self,
        person_id: str,
    ) -> PersonPreference | None:
        """
        Query storage for an existing preference for person_id.
        Returns the persisted aggregate if found, otherwise None.
        """
        raise NotImplementedError

    @abstractmethod
    def get_or_default(
        self,
        person_id: str,
    ) -> PersonPreference:
        """
        Return the persisted PersonPreference if present, or an in-memory
        transient default PersonPreference aggregate using SignoffReminderPolicy.CONTINUE
        and preferred_timezone=None if absent.

        Must be read-only when no preference exists: must NOT call save() or mutate
        repository storage.
        """
        raise NotImplementedError
