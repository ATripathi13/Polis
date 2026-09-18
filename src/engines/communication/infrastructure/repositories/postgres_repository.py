"""
PostgreSQL repository for communication events.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from domain.common.identifier import Identifier

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)
from engines.communication.domain.enums import (
    EventSource,
    ProcessingStatus,
)
from engines.communication.domain.repositories import (
    CommunicationRepository,
)
from engines.communication.domain.value_objects import (
    Actor,
    Attachment,
    Channel,
    CommunicationIdentity,
    Content,
    Mention,
    MessageReference,
)

from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import CommunicationEventModel


class PostgreSQLCommunicationRepository(
    CommunicationRepository,
):
    """
    PostgreSQL repository for normalized communication events.
    """

    def save(
        self,
        event: CommunicationEvent,
    ) -> CommunicationEvent:

        with SessionLocal() as session:

            existing = (
                session.query(CommunicationEventModel)
                .filter(
                    CommunicationEventModel.source
                    == event.source.value,
                    CommunicationEventModel.source_event_id
                    == event.source_event_id,
                )
                .first()
            )

            if existing is not None:
                return self._to_domain(existing)

            record = CommunicationEventModel(
                id=str(event.identifier.graph_id),
                correlation_id=str(
                    event.correlation_id.graph_id
                ),
                source=event.source.value,
                source_event_id=event.source_event_id,
                actor=self._actor_to_dict(event.actor),
                channel=self._channel_to_dict(event.channel),
                content=self._content_to_dict(event.content),
                status=event.status.value,
                attachments=[
                    self._attachment_to_dict(item)
                    for item in event.attachments
                ],
                references=[
                    self._reference_to_dict(item)
                    for item in event.references
                ],
                mentions=[
                    self._mention_to_dict(item)
                    for item in event.mentions
                ],
                created_at=datetime.utcnow(),
            )

            session.add(record)

            try:
                session.commit()
            except IntegrityError:
                session.rollback()

                existing = (
                    session.query(
                        CommunicationEventModel
                    )
                    .filter(
                        CommunicationEventModel.source
                        == event.source.value,
                        CommunicationEventModel.source_event_id
                        == event.source_event_id,
                    )
                    .first()
                )

                if existing is None:
                    raise

                return self._to_domain(existing)

            return event

    def find_by_source_event_id(
        self,
        *,
        source: EventSource,
        source_event_id: str,
    ) -> CommunicationEvent | None:

        with SessionLocal() as session:

            record = (
                session.query(
                    CommunicationEventModel
                )
                .filter(
                    CommunicationEventModel.source
                    == source.value,
                    CommunicationEventModel.source_event_id
                    == source_event_id,
                )
                .first()
            )

            if record is None:
                return None

            return self._to_domain(record)
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

        with SessionLocal() as session:

            records = (
                session.query(
                    CommunicationEventModel
                )
            )

            if start_time is not None:
                records = records.filter(
                    CommunicationEventModel.created_at
                    >= start_time
                )

            if end_time is not None:
                records = records.filter(
                    CommunicationEventModel.created_at
                    < end_time
                )

            records = (
                records
                .order_by(
                    CommunicationEventModel.created_at.desc()
                )
                .limit(100)
                .all()
            )

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

            results = []

            for record in records:

                if actor_id is not None:

                    internal_id = (
                        record.actor.get("identity", {}).get(
                            "internal_id"
                        )
                        if record.actor
                        else None
                    )

                    if internal_id != actor_id:
                        continue

                body = (
                    record.content.get("body", "")
                    if record.content
                    else ""
                )

                if not body:
                    continue

                searchable_text = body.lower()

                if exclude_questions:

                    if searchable_text.endswith("?"):
                        continue

                    question_starters = (
                        "what ",
                        "why ",
                        "who ",
                        "where ",
                        "when ",
                        "which ",
                        "how ",
                        "can ",
                        "could ",
                        "would ",
                        "should ",
                        "is ",
                        "are ",
                        "do ",
                        "does ",
                        "did ",
                        "tell me ",
                        "show me ",
                        "list ",
                        "summarize ",
                        "explain ",
                    )

                    if searchable_text.startswith(
                        question_starters
                    ):
                        continue

                if meaningful_words and all(
                    word in searchable_text
                    for word in meaningful_words
                ):
                    normalized_body = " ".join(
                        searchable_text.split()
                    )

                    already_seen = any(
                        " ".join(
                            event.content.body.lower().split()
                        ) == normalized_body
                        for event in results
                    )

                    if not already_seen:
                        results.append(
                            self._to_domain(record)
                        )

                if len(results) >= limit:
                    break

            return results
            
    @staticmethod
    def _actor_to_dict(
        actor: Actor,
    ) -> dict:
        return {
            "identity": {
                "internal_id": actor.identity.internal_id,
                "external_ids": actor.identity.external_ids,
                "metadata": actor.identity.metadata,
            },
            "display_name": actor.display_name,
            "email": actor.email,
            "metadata": actor.metadata,
        }

    @staticmethod
    def _actor_from_dict(
        data: dict,
    ) -> Actor:

        identity_data = data.get("identity", {})

        return Actor(
            identity=CommunicationIdentity(
                internal_id=identity_data["internal_id"],
                external_ids=identity_data.get(
                    "external_ids",
                    {},
                ),
                metadata=identity_data.get(
                    "metadata",
                    {},
                ),
            ),
            display_name=data["display_name"],
            email=data.get("email"),
            metadata=data.get("metadata", {}),
        )

    @staticmethod
    def _channel_to_dict(
        channel: Channel,
    ) -> dict:
        return {
            "identity": {
                "internal_id": channel.identity.internal_id,
                "external_ids": channel.identity.external_ids,
                "metadata": channel.identity.metadata,
            },
            "name": channel.name,
            "channel_type": channel.channel_type,
            "metadata": channel.metadata,
        }

    @staticmethod
    def _channel_from_dict(
        data: dict,
    ) -> Channel:

        identity_data = data.get("identity", {})

        return Channel(
            identity=CommunicationIdentity(
                internal_id=identity_data["internal_id"],
                external_ids=identity_data.get(
                    "external_ids",
                    {},
                ),
                metadata=identity_data.get(
                    "metadata",
                    {},
                ),
            ),
            name=data["name"],
            channel_type=data["channel_type"],
            metadata=data.get("metadata", {}),
        )

    @staticmethod
    def _content_to_dict(
        content: Content,
    ) -> dict:
        return {
            "body": content.body,
            "title": content.title,
            "language": content.language,
            "content_type": content.content_type,
            "summary": content.summary,
            "metadata": content.metadata,
        }

    @staticmethod
    def _content_from_dict(
        data: dict,
    ) -> Content:

        return Content(
            body=data["body"],
            title=data.get("title"),
            language=data.get("language", "en"),
            content_type=data.get(
                "content_type",
                "text",
            ),
            summary=data.get("summary"),
            metadata=data.get("metadata", {}),
        )

    @staticmethod
    def _attachment_to_dict(
        attachment: Attachment,
    ) -> dict:
        return {
            "attachment_id": attachment.attachment_id,
            "filename": attachment.filename,
            "mime_type": attachment.mime_type,
            "size_bytes": attachment.size_bytes,
            "url": attachment.url,
            "metadata": attachment.metadata,
        }

    @staticmethod
    def _attachment_from_dict(
        data: dict,
    ) -> Attachment:

        return Attachment(
            attachment_id=data["attachment_id"],
            filename=data["filename"],
            mime_type=data["mime_type"],
            size_bytes=data["size_bytes"],
            url=data.get("url"),
            metadata=data.get("metadata", {}),
        )

    @staticmethod
    def _reference_to_dict(
        reference: MessageReference,
    ) -> dict:
        return {
            "reference_id": reference.reference_id,
            "relationship_type": reference.relationship_type,
            "source": reference.source,
            "metadata": reference.metadata,
        }

    @staticmethod
    def _reference_from_dict(
        data: dict,
    ) -> MessageReference:

        return MessageReference(
            reference_id=data["reference_id"],
            relationship_type=data["relationship_type"],
            source=data["source"],
            metadata=data.get("metadata", {}),
        )

    @staticmethod
    def _mention_to_dict(
        mention: Mention,
    ) -> dict:
        return {
            "identity": {
                "internal_id": mention.identity.internal_id,
                "external_ids": mention.identity.external_ids,
                "metadata": mention.identity.metadata,
            },
            "display_name": mention.display_name,
        }

    @staticmethod
    def _mention_from_dict(
        data: dict,
    ) -> Mention:

        identity_data = data.get("identity", {})

        return Mention(
            identity=CommunicationIdentity(
                internal_id=identity_data["internal_id"],
                external_ids=identity_data.get(
                    "external_ids",
                    {},
                ),
                metadata=identity_data.get(
                    "metadata",
                    {},
                ),
            ),
            display_name=data["display_name"],
        )

    @classmethod
    def _to_domain(
        cls,
        record: CommunicationEventModel,
    ) -> CommunicationEvent:

        event = CommunicationEvent(
            identifier=Identifier(
                graph_id=UUID(record.id),
            ),
            correlation_id=Identifier(
                graph_id=UUID(record.correlation_id),
            ),
            source=EventSource(record.source),
            source_event_id=record.source_event_id,
            actor=cls._actor_from_dict(record.actor),
            channel=cls._channel_from_dict(record.channel),
            content=cls._content_from_dict(record.content),
            status=ProcessingStatus(record.status),
            attachments=[
                cls._attachment_from_dict(item)
                for item in record.attachments
            ],
            references=[
                cls._reference_from_dict(item)
                for item in record.references
            ],
            mentions=[
                cls._mention_from_dict(item)
                for item in record.mentions
            ],
        )

        return event
