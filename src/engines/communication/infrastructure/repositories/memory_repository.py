"""
In-memory repository for testing.
"""

from __future__ import annotations

import copy
import dataclasses
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
                if actor_id is None:
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

    def get_person_recent_activity(
        self,
        *,
        actor_ids: list[str] | str,
        actor_name: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 50,
        include_mentions: bool = True,
        include_parent_context: bool = True,
    ) -> list[CommunicationEvent]:
        from datetime import timezone, timedelta
        from engines.communication.domain.value_objects import MessageReference

        if isinstance(actor_ids, str):
            id_list = [actor_ids.strip()] if actor_ids.strip() else []
        else:
            id_list = [i.strip() for i in actor_ids if i and i.strip()]

        if not id_list and not actor_name:
            return []

        if start_time is None:
            start_time = datetime.now(timezone.utc) - timedelta(days=7)

        records = sorted(
            self._events,
            key=lambda event: event.created_at,
            reverse=True,
        )

        results: list[CommunicationEvent] = []
        seen_source_ids: set[str] = set()

        for event in records:
            if start_time is not None and event.created_at < start_time:
                continue
            if end_time is not None and event.created_at >= end_time:
                continue

            actor_internal = getattr(getattr(event.actor, "identity", None), "internal_id", "") or ""
            actor_slack = (getattr(getattr(event.actor, "identity", None), "external_ids", {}) or {}).get("slack", "")
            actor_disp = getattr(event.actor, "display_name", "") or ""
            body = (getattr(event.content, "body", "") or "").strip()

            matched = False
            if actor_internal in id_list or actor_slack in id_list:
                matched = True
            elif actor_name and actor_disp.lower() == actor_name.lower():
                matched = True
            elif include_mentions:
                # Check mentions list
                for m in event.mentions:
                    m_id = getattr(getattr(m, "identity", None), "internal_id", "")
                    if m_id in id_list:
                        matched = True
                        break
                # Check mentions in body
                if not matched and any(f"<@{uid}" in body for uid in id_list):
                    matched = True
                elif not matched and actor_name and len(actor_name.strip()) >= 3 and actor_name.lower() in body.lower():
                    matched = True

            if not matched:
                continue

            if event.source_event_id in seen_source_ids:
                continue
            seen_source_ids.add(event.source_event_id)

            event_to_return = event
            # If reply and parent context requested
            if (
                include_parent_context
                and event.correlation_id.business_id
                and event.correlation_id.business_id != event.source_event_id
            ):
                parent_id = event.correlation_id.business_id
                parent_ev = next((e for e in self._events if e.source_event_id == parent_id), None)
                # Verify parent belongs to the same channel
                ev_ch_name = getattr(getattr(event, "channel", None), "name", None)
                p_ch_name = getattr(getattr(parent_ev, "channel", None), "name", None) if parent_ev else None
                if parent_ev is not None and ev_ch_name and p_ch_name and ev_ch_name == p_ch_name:
                    p_body = getattr(parent_ev.content, "body", "") or ""
                    p_author = getattr(parent_ev.actor, "display_name", "") or ""
                    p_channel = getattr(parent_ev.channel, "name", "") or ""

                    new_metadata = dict(event.content.metadata)
                    new_metadata["parent_message_body"] = p_body
                    new_metadata["parent_actor_name"] = p_author
                    new_metadata["parent_channel_name"] = p_channel
                    new_metadata["parent_ts"] = parent_id

                    new_content = dataclasses.replace(event.content, metadata=new_metadata)
                    new_references = list(event.references)

                    if not any(ref.reference_id == parent_id and ref.relationship_type == "parent_message" for ref in new_references):
                        new_references.append(
                            MessageReference(
                                reference_id=parent_id,
                                relationship_type="parent_message",
                                source=event.source,
                                metadata={
                                    "body": p_body,
                                    "author": p_author,
                                    "channel": p_channel,
                                },
                            )
                        )

                    event_to_return = dataclasses.replace(copy.copy(event), content=new_content, references=new_references)

            results.append(event_to_return)
            if len(results) >= limit:
                break

        return results

    def get_recent_events(
        self,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 500,
        include_parent_context: bool = True,
    ) -> list[CommunicationEvent]:
        from engines.communication.domain.value_objects import MessageReference

        records = sorted(
            self._events,
            key=lambda ev: ev.created_at,
            reverse=True,
        )

        results: list[CommunicationEvent] = []
        seen_source_ids: set[str] = set()

        for event in records:
            if start_time is not None and event.created_at < start_time:
                continue
            if end_time is not None and event.created_at >= end_time:
                continue

            if event.source_event_id in seen_source_ids:
                continue
            seen_source_ids.add(event.source_event_id)

            event_to_return = event
            # If reply and parent context requested
            if (
                include_parent_context
                and event.correlation_id.business_id
                and event.correlation_id.business_id != event.source_event_id
            ):
                parent_id = event.correlation_id.business_id
                parent_ev = next((e for e in self._events if e.source_event_id == parent_id), None)
                # Verify parent belongs to the same channel
                ev_ch_name = getattr(getattr(event, "channel", None), "name", None)
                p_ch_name = getattr(getattr(parent_ev, "channel", None), "name", None) if parent_ev else None
                if parent_ev is not None and ev_ch_name and p_ch_name and ev_ch_name == p_ch_name:
                    p_body = getattr(parent_ev.content, "body", "") or ""
                    p_author = getattr(parent_ev.actor, "display_name", "") or ""
                    p_channel = getattr(parent_ev.channel, "name", "") or ""

                    new_metadata = dict(event.content.metadata)
                    new_metadata["parent_message_body"] = p_body
                    new_metadata["parent_actor_name"] = p_author
                    new_metadata["parent_channel_name"] = p_channel
                    new_metadata["parent_ts"] = parent_id

                    new_content = dataclasses.replace(event.content, metadata=new_metadata)
                    new_references = list(event.references)

                    if not any(ref.reference_id == parent_id and ref.relationship_type == "parent_message" for ref in new_references):
                        new_references.append(
                            MessageReference(
                                reference_id=parent_id,
                                relationship_type="parent_message",
                                source=event.source,
                                metadata={
                                    "body": p_body,
                                    "author": p_author,
                                    "channel": p_channel,
                                },
                            )
                        )

                    event_to_return = dataclasses.replace(copy.copy(event), content=new_content, references=new_references)

            results.append(event_to_return)
            if len(results) >= limit:
                break

        return results
