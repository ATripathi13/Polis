"""
In-memory repository for testing.
"""

from __future__ import annotations

from datetime import datetime

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)
from engines.communication.domain.repositories import (
    CommunicationRepository,
)


class InMemoryCommunicationRepository(
    CommunicationRepository,
):
    """
    Simple in-memory repository.
    """

    def __init__(self) -> None:
        self._events: list[CommunicationEvent] = []

    def save(
        self,
        event: CommunicationEvent,
    ) -> CommunicationEvent:
        self._events.append(event)
        return event

    @property
    def events(self) -> list[CommunicationEvent]:
        return self._events

    def search(
        self,
        *,
        query: str,
        limit: int = 20,
        actor_id: str | None = None,
        exclude_questions: bool = False,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[CommunicationEvent]:

        query = query.strip().lower()

        if not query:
            return []

        query_words = {
            word.strip(".,!?;:()[]{}\"'")
            for word in query.split()
            if word.strip(".,!?;:()[]{}\"'")
        }

        stop_words = {
            "what",
            "am",
            "i",
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "do",
            "does",
            "did",
            "on",
            "in",
            "to",
            "of",
            "for",
            "my",
            "me",
            "we",
            "our",
            "you",
            "your",
            "today",
        }

        meaningful_words = query_words - stop_words

        records = sorted(
            self._events,
            key=lambda event: event.created_at,
            reverse=True,
        )

        results: list[CommunicationEvent] = []
        seen_bodies: set[str] = set()

        for event in records:

            if start_time is not None:
                if event.created_at < start_time:
                    continue

            if end_time is not None:
                if event.created_at >= end_time:
                    continue

            if actor_id is not None:
                if (
                    event.actor.identity.internal_id
                    != actor_id
                ):
                    continue

            body = event.content.body.strip()

            if not body:
                continue

            searchable_text = body.lower()

            if exclude_questions and event.is_question():
                continue

            if meaningful_words and not all(
                word in searchable_text
                for word in meaningful_words
            ):
                continue

            normalized_body = " ".join(
                searchable_text.split()
            )

            if normalized_body in seen_bodies:
                continue

            seen_bodies.add(normalized_body)
            results.append(event)

            if len(results) >= limit:
                break

        return results