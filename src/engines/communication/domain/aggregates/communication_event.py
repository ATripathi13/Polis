"""
Communication Event Aggregate.

Represents a normalized communication observed by Polis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Self

from domain.common.aggregate import AggregateRoot
from domain.common.identifier import Identifier

from engines.communication.domain.enums.event_source import EventSource
from engines.communication.domain.enums.processing_status import ProcessingStatus

from engines.communication.domain.value_objects.actor import Actor
from engines.communication.domain.value_objects.attachment import Attachment
from engines.communication.domain.value_objects.channel import Channel
from engines.communication.domain.value_objects.content import Content
from engines.communication.domain.value_objects.message_reference import (
    MessageReference,
)
from engines.communication.domain.events import (
    CommunicationCreatedEvent,
)
from engines.communication.domain.value_objects.mention import (
    Mention,
)

@dataclass(slots=True, kw_only=True)
class CommunicationEvent(AggregateRoot):
    """
    Aggregate Root representing a normalized communication.
    """

    correlation_id: Identifier

    source: EventSource

    source_event_id: str

    actor: Actor

    channel: Channel

    content: Content

    status: ProcessingStatus = ProcessingStatus.RECEIVED

    attachments: list[Attachment] = field(default_factory=list)

    references: list[MessageReference] = field(default_factory=list)

    mentions: list[Mention] = field(default_factory=list,)

    _ALLOWED_TRANSITIONS: ClassVar[dict] = {
        ProcessingStatus.RECEIVED: {
            ProcessingStatus.NORMALIZED,
            ProcessingStatus.FAILED,
        },
        ProcessingStatus.NORMALIZED: {
            ProcessingStatus.VALIDATED,
            ProcessingStatus.FAILED,
        },
        ProcessingStatus.VALIDATED: {
            ProcessingStatus.PERSISTED,
            ProcessingStatus.FAILED,
        },
        ProcessingStatus.PERSISTED: {
            ProcessingStatus.PUBLISHED,
            ProcessingStatus.FAILED,
        },
        ProcessingStatus.PUBLISHED: set(),
        ProcessingStatus.FAILED: set(),
    }

    @classmethod
    def create(
        cls,
        *,
        correlation_id: Identifier,
        source: EventSource,
        source_event_id: str,
        actor: Actor,
        channel: Channel,
        content: Content,
    ) -> Self:
        """
        Factory method.
        """

        event = cls(
            correlation_id=correlation_id,
            source=source,
            source_event_id=source_event_id,
            actor=actor,
            channel=channel,
            content=content,
        )

        event.validate()
        event.add_domain_event(
            CommunicationCreatedEvent(
                communication_id=event.identifier,
            )
        )

        return event

    def validate(self) -> None:
        """
        Validate aggregate invariants.
        """

        if not self.source_event_id.strip():
            raise ValueError("source_event_id cannot be empty.")

        if self.actor is None:
            raise ValueError("actor is required.")

        if self.channel is None:
            raise ValueError("channel is required.")

        if self.content is None:
            raise ValueError("content is required.")

    def _transition_to(self, status: ProcessingStatus) -> None:
        if status not in self._ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(
                f"Invalid transition: {self.status} -> {status}"
            )

        self.status = status

    def mark_normalized(self) -> None:
        self._transition_to(ProcessingStatus.NORMALIZED)

    def mark_validated(self) -> None:
        self._transition_to(ProcessingStatus.VALIDATED)

    def mark_persisted(self) -> None:
        self._transition_to(ProcessingStatus.PERSISTED)

    def mark_published(self) -> None:
        self._transition_to(ProcessingStatus.PUBLISHED)

    def mark_failed(self) -> None:
        self.status = ProcessingStatus.FAILED

    def is_addressed_to(
        self,
        internal_id: str,
    ) -> bool:
        """
        Returns True if this communication explicitly
        mentions the given identity.
        """

        return any(
            mention.identity.internal_id == internal_id
            for mention in self.mentions
        )
    def is_question(self) -> bool:
        """
        Returns True if the communication appears
        to be asking a question.
        """

        text = self.content.body.strip().lower()

        if not text:
            return False

        if text.endswith("?"):
            return True

        question_starters = (
            "what",
            "why",
            "who",
            "where",
            "when",
            "which",
            "how",
            "can",
            "could",
            "would",
            "should",
            "is",
            "are",
            "do",
            "does",
            "did",
            "tell me",
            "show me",
            "list",
            "summarize",
            "explain",
        )

        return text.startswith(question_starters)