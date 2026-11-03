from __future__ import annotations

import threading

from ..aggregates.person_preference import PersonPreference
from .person_preference_repository import PersonPreferenceRepository


class InMemoryPersonPreferenceRepository(PersonPreferenceRepository):
    """
    In-memory thread-safe implementation of PersonPreferenceRepository.
    """

    def __init__(self) -> None:
        self._preferences: dict[str, PersonPreference] = {}
        self._lock = threading.Lock()

    def save(
        self,
        preference: PersonPreference,
    ) -> None:
        with self._lock:
            self._preferences[preference.person_id] = preference

    def find_by_person_id(
        self,
        person_id: str,
    ) -> PersonPreference | None:
        if not isinstance(person_id, str) or not person_id.strip():
            raise ValueError("person_id must be a non-empty string.")

        with self._lock:
            return self._preferences.get(person_id)

    def get_or_default(
        self,
        person_id: str,
    ) -> PersonPreference:
        if not isinstance(person_id, str) or not person_id.strip():
            raise ValueError("person_id must be a non-empty string.")

        with self._lock:
            existing = self._preferences.get(person_id)
            if existing is not None:
                return existing

        return PersonPreference.create(person_id=person_id)
