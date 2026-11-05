"""
PostgreSQL repository for communication events.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, or_
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
                if (
                    not existing.correlation_business_id
                    and event.correlation_id.business_id
                ):
                    existing.correlation_business_id = (
                        event.correlation_id.business_id
                    )
                    session.commit()

                return self._to_domain(existing)

            record = CommunicationEventModel(
                id=str(event.identifier.graph_id),
                correlation_id=str(
                    event.correlation_id.graph_id
                ),
                correlation_business_id=event.correlation_id.business_id,
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
            records = session.query(CommunicationEventModel)

            if start_time is not None:
                records = records.filter(
                    CommunicationEventModel.created_at >= start_time
                )

            if end_time is not None:
                records = records.filter(
                    CommunicationEventModel.created_at < end_time
                )

            # Apply actor filtering in SQL before pagination/limiting
            if actor_id is not None:
                bind = session.get_bind()
                if bind and bind.dialect.name == "postgresql":
                    records = records.filter(
                        or_(
                            func.jsonb_extract_path_text(
                                CommunicationEventModel.actor, "identity", "internal_id"
                            ) == actor_id,
                            func.jsonb_extract_path_text(
                                CommunicationEventModel.actor, "identity", "external_ids", "slack"
                            ) == actor_id,
                        )
                    )

            records = (
                records
                .order_by(
                    CommunicationEventModel.created_at.desc()
                )
                .limit(limit * 5 if actor_id is not None else 100)
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

            ranked_results = []

            for record in records:
                if actor_id is not None:
                    act_ident = (record.actor or {}).get("identity", {}) or {}
                    ext_ids = act_ident.get("external_ids", {}) or {}
                    internal_id = act_ident.get("internal_id")
                    slack_id = ext_ids.get("slack")

                    if internal_id != actor_id and slack_id != actor_id:
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
                    if self._to_domain(record).is_question():
                        continue

                matched_words = {
                    word
                    for word in meaningful_words
                    if word in searchable_text
                }

                if meaningful_words:
                    if matched_words:
                        match_score = (
                            len(matched_words)
                            / len(meaningful_words)
                        )
                    elif actor_id is not None:
                        # Actor was explicitly filtered; do not drop substantive messages
                        # that don't literally repeat meta-query words
                        match_score = 0.5
                    else:
                        continue
                else:
                    match_score = 1.0

                normalized_body = " ".join(
                    searchable_text.split()
                )

                already_seen = any(
                    " ".join(
                        event.content.body.lower().split()
                    ) == normalized_body
                    for _, _, event in ranked_results
                )

                if already_seen:
                    continue

                ranked_results.append(
                    (match_score, record.created_at, self._to_domain(record))
                )

            ranked_results.sort(
                key=lambda item: (
                    item[0],
                    item[1],
                ),
                reverse=True,
            )

            return [
                event
                for _, _, event in ranked_results[:limit]
            ]

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
        """
        Retrieve recent communications authored by or involving a specific person.
        Supports:
        - Person/actor identity filtering in SQL.
        - Mentions of the person in message bodies.
        - Look-back period (default 7 days).
        - Thread parent context attachment for replies.
        """
        if isinstance(actor_ids, str):
            id_list = [actor_ids.strip()] if actor_ids.strip() else []
        else:
            id_list = [i.strip() for i in actor_ids if i and i.strip()]

        if not id_list and not actor_name:
            return []

        if start_time is None:
            start_time = datetime.now(timezone.utc) - timedelta(days=7)

        with SessionLocal() as session:
            bind = session.get_bind()
            is_postgres = bool(bind and bind.dialect.name == "postgresql")

            query = session.query(CommunicationEventModel)

            if start_time is not None:
                query = query.filter(CommunicationEventModel.created_at >= start_time)
            if end_time is not None:
                query = query.filter(CommunicationEventModel.created_at < end_time)

            if is_postgres:
                conditions = []
                if id_list:
                    conditions.append(
                        func.jsonb_extract_path_text(
                            CommunicationEventModel.actor, "identity", "internal_id"
                        ).in_(id_list)
                    )
                    conditions.append(
                        func.jsonb_extract_path_text(
                            CommunicationEventModel.actor, "identity", "external_ids", "slack"
                        ).in_(id_list)
                    )
                if actor_name:
                    clean_name = actor_name.strip()
                    conditions.append(
                        func.lower(
                            func.jsonb_extract_path_text(
                                CommunicationEventModel.actor, "display_name"
                            )
                        ) == clean_name.lower()
                    )

                if include_mentions:
                    for uid in id_list:
                        conditions.append(
                            func.jsonb_extract_path_text(
                                CommunicationEventModel.content, "body"
                            ).ilike(f"%<@{uid}%")
                        )
                    if actor_name and len(actor_name.strip()) >= 3:
                        conditions.append(
                            func.jsonb_extract_path_text(
                                CommunicationEventModel.content, "body"
                            ).ilike(f"%{actor_name.strip()}%")
                        )

                if conditions:
                    query = query.filter(or_(*conditions))

                records = (
                    query
                    .order_by(CommunicationEventModel.created_at.desc())
                    .limit(limit)
                    .all()
                )
            else:
                # Fallback for SQLite / generic mock engines in tests
                all_recs = (
                    query
                    .order_by(CommunicationEventModel.created_at.desc())
                    .all()
                )
                filtered = []
                for r in all_recs:
                    act = r.actor or {}
                    ident = act.get("identity", {}) or {}
                    ext = ident.get("external_ids", {}) or {}
                    r_id = ident.get("internal_id") or ""
                    r_slack = ext.get("slack") or ""
                    r_name = act.get("display_name") or ""
                    r_body = (r.content or {}).get("body", "")

                    matched = False
                    if r_id in id_list or r_slack in id_list:
                        matched = True
                    elif actor_name and r_name.lower() == actor_name.lower():
                        matched = True
                    elif include_mentions:
                        if any(f"<@{uid}" in r_body for uid in id_list):
                            matched = True
                        elif actor_name and len(actor_name.strip()) >= 3 and actor_name.lower() in r_body.lower():
                            matched = True

                    if matched:
                        filtered.append(r)
                        if len(filtered) >= limit:
                            break
                records = filtered

            if not records:
                return []

            # Retrieve parent context for thread replies
            parent_records_map = {}
            if include_parent_context:
                parent_source_ids = {
                    r.correlation_business_id
                    for r in records
                    if r.correlation_business_id
                    and r.correlation_business_id != r.source_event_id
                }
                if parent_source_ids:
                    parents = (
                        session.query(CommunicationEventModel)
                        .filter(CommunicationEventModel.source_event_id.in_(parent_source_ids))
                        .all()
                    )
                    parent_records_map = {p.source_event_id: p for p in parents}

            events = []
            seen_source_ids = set()
            for r in records:
                if r.source_event_id in seen_source_ids:
                    continue
                seen_source_ids.add(r.source_event_id)

                event = self._to_domain(r)

                # If reply, attach parent context
                if (
                    r.correlation_business_id
                    and r.correlation_business_id != r.source_event_id
                    and r.correlation_business_id in parent_records_map
                ):
                    p_rec = parent_records_map[r.correlation_business_id]
                    r_ch_id = (r.channel or {}).get("identity", {}).get("internal_id") or (r.channel or {}).get("name")
                    p_ch_id = (p_rec.channel or {}).get("identity", {}).get("internal_id") or (p_rec.channel or {}).get("name")
                    if r_ch_id and p_ch_id and r_ch_id == p_ch_id:
                        p_body = (p_rec.content or {}).get("body", "")
                        p_actor_name = (p_rec.actor or {}).get("display_name", "")
                        p_channel_name = (p_rec.channel or {}).get("name", "")
                        p_ts = p_rec.source_event_id

                        event.content.metadata["parent_message_body"] = p_body
                        event.content.metadata["parent_actor_name"] = p_actor_name
                        event.content.metadata["parent_channel_name"] = p_channel_name
                        event.content.metadata["parent_ts"] = p_ts

                        if not any(ref.reference_id == p_ts and ref.relationship_type == "parent_message" for ref in event.references):
                            event.references.append(
                                MessageReference(
                                    reference_id=p_ts,
                                    relationship_type="parent_message",
                                    source=r.source,
                                    metadata={
                                        "body": p_body,
                                        "author": p_actor_name,
                                        "channel": p_channel_name,
                                    },
                                )
                            )

                events.append(event)

            return events

    def get_recent_events(
        self,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 500,
        include_parent_context: bool = True,
    ) -> list[CommunicationEvent]:
        """
        Retrieve recent communication events across all users and channels.
        - Supports configurable start_time and end_time filters.
        - Newest messages first (ORDER BY created_at DESC).
        - Database-level filtering, ordering, and limiting.
        - Thread parent context attachment for replies.
        - Deduplication by source_event_id.
        """
        with SessionLocal() as session:
            query = session.query(CommunicationEventModel)

            if start_time is not None:
                query = query.filter(CommunicationEventModel.created_at >= start_time)
            if end_time is not None:
                query = query.filter(CommunicationEventModel.created_at < end_time)

            query = query.order_by(CommunicationEventModel.created_at.desc())

            # Batch fetch so deduplication yields up to `limit` unique events
            batch_size = max(limit, 10)
            offset = 0
            records = []
            seen_source_ids = set()

            while len(records) < limit:
                batch = query.offset(offset).limit(batch_size).all()
                if not batch:
                    break
                for r in batch:
                    if r.source_event_id not in seen_source_ids:
                        seen_source_ids.add(r.source_event_id)
                        records.append(r)
                        if len(records) >= limit:
                            break
                offset += batch_size
                if len(batch) < batch_size:
                    break

            if not records:
                return []

            # Retrieve parent context for thread replies
            parent_records_map = {}
            if include_parent_context:
                parent_source_ids = {
                    r.correlation_business_id
                    for r in records
                    if r.correlation_business_id
                    and r.correlation_business_id != r.source_event_id
                }
                if parent_source_ids:
                    parents = (
                        session.query(CommunicationEventModel)
                        .filter(CommunicationEventModel.source_event_id.in_(parent_source_ids))
                        .all()
                    )
                    parent_records_map = {p.source_event_id: p for p in parents}

            events = []
            for r in records:
                event = self._to_domain(r)

                # If reply, attach parent context (verifying same channel)
                if (
                    r.correlation_business_id
                    and r.correlation_business_id != r.source_event_id
                    and r.correlation_business_id in parent_records_map
                ):
                    p_rec = parent_records_map[r.correlation_business_id]
                    r_ch_id = (r.channel or {}).get("identity", {}).get("internal_id") or (r.channel or {}).get("name")
                    p_ch_id = (p_rec.channel or {}).get("identity", {}).get("internal_id") or (p_rec.channel or {}).get("name")
                    if r_ch_id and p_ch_id and r_ch_id == p_ch_id:
                        p_body = (p_rec.content or {}).get("body", "")
                        p_actor_name = (p_rec.actor or {}).get("display_name", "")
                        p_channel_name = (p_rec.channel or {}).get("name", "")
                        p_ts = p_rec.source_event_id

                        event.content.metadata["parent_message_body"] = p_body
                        event.content.metadata["parent_actor_name"] = p_actor_name
                        event.content.metadata["parent_channel_name"] = p_channel_name
                        event.content.metadata["parent_ts"] = p_ts

                        if not any(ref.reference_id == p_ts and ref.relationship_type == "parent_message" for ref in event.references):
                            event.references.append(
                                MessageReference(
                                    reference_id=p_ts,
                                    relationship_type="parent_message",
                                    source=r.source,
                                    metadata={
                                        "body": p_body,
                                        "author": p_actor_name,
                                        "channel": p_channel_name,
                                    },
                                )
                            )

                events.append(event)

            return events

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
            created_at=record.created_at,
            correlation_id=Identifier(
                graph_id=UUID(record.correlation_id),
                business_id=record.correlation_business_id,
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
