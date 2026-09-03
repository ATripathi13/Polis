from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from domain.knowledge.repositories import KnowledgeRepository
from domain.knowledge.value_objects import (
    KnowledgeCandidate,
    KnowledgeSubject,
)

from memory.models.knowledge_record import KnowledgeRecord

from .connection import SessionLocal
from .models import KnowledgeRecordModel


class PostgreSQLKnowledgeRepository(
    KnowledgeRepository,
):

    def save(
        self,
        candidate: KnowledgeCandidate,
    ) -> None:

        with SessionLocal() as session:

            existing = session.get(
                KnowledgeRecordModel,
                candidate.subject.identifier,
            )

            record = session.query(
                KnowledgeRecordModel
            ).filter(
                KnowledgeRecordModel.subject
                == candidate.subject.identifier
            ).first()

            if record is None:

                record = KnowledgeRecordModel(
                    id=str(uuid4()),
                    subject=candidate.subject.identifier,
                    summary=candidate.summary,
                    canonical_text=candidate.summary,
                    confidence=candidate.confidence,
                    source="Slack",
                    created_at=datetime.utcnow(),
                    tags=[],
                    embedding=None,
                    metadata={},
                )

                session.add(record)

            else:

                record.summary = candidate.summary
                record.canonical_text = candidate.summary
                record.confidence = candidate.confidence

            session.commit()

    def find(
        self,
        identifier: str,
    ) -> KnowledgeCandidate | None:

        with SessionLocal() as session:

            record = session.query(
                KnowledgeRecordModel
            ).filter(
                KnowledgeRecordModel.subject
                == identifier
            ).first()

            if record is None:
                return None

            return self._to_candidate(record)

    def all(
        self,
    ) -> list[KnowledgeCandidate]:

        with SessionLocal() as session:

            records = session.query(
                KnowledgeRecordModel
            ).order_by(
                KnowledgeRecordModel.created_at
            ).all()

            return [
                self._to_candidate(record)
                for record in records
            ]

    @staticmethod
    def _to_candidate(
        record: KnowledgeRecordModel,
    ) -> KnowledgeCandidate:

        return KnowledgeCandidate(
            subject=KnowledgeSubject(
                kind="general",
                identifier=record.subject,
            ),
            summary=record.summary,
            supporting_events=[],
            confidence=record.confidence,
        )