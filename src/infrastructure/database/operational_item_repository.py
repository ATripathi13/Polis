from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_

from domain.common.identifier import Identifier
from domain.operations import (
    OperationalItem,
    OperationalItemPriority,
    OperationalItemRepository,
    OperationalItemStatus,
    OperationalItemType,
)

from .connection import SessionLocal
from .models import OperationalItemModel


class PostgreSQLOperationalItemRepository(
    OperationalItemRepository,
):
    """
    PostgreSQL repository for operational tasks, decisions, and risks.
    """

    def save(
        self,
        item: OperationalItem,
    ) -> OperationalItem:
        with SessionLocal() as session:

            existing = (
                session.query(OperationalItemModel)
                .filter(
                    OperationalItemModel.id
                    == str(item.identifier.graph_id)
                )
                .first()
            )

            if existing is not None:
                return self._to_domain(existing)

            if item.source_event_id:
                existing = (
                    session.query(OperationalItemModel)
                    .filter(
                        OperationalItemModel.source_type
                        == item.source_type,
                        OperationalItemModel.source_event_id
                        == item.source_event_id,
                        OperationalItemModel.item_type
                        == item.item_type.value,
                    )
                    .first()
                )

                if existing is not None:
                    return self._to_domain(existing)

            record = OperationalItemModel(
                id=str(item.identifier.graph_id),
                item_type=item.item_type.value,
                summary=item.summary,
                status=item.status.value,
                priority=item.priority.value,
                owner_id=item.owner_id,
                owner_name=item.owner_name,
                due_at=item.due_at,
                source_event_id=item.source_event_id,
                source_type=item.source_type,
                confidence=item.confidence,
                evidence=list(item.evidence),
                metadata_=dict(item.metadata),
                created_at=item.created_at,
                updated_at=item.updated_at,
            )

            session.add(record)
            session.commit()
            session.refresh(record)

            return self._to_domain(record)

    def find_by_id(
        self,
        item_id: str,
    ) -> OperationalItem | None:

        with SessionLocal() as session:

            record = (
                session.query(OperationalItemModel)
                .filter(
                    OperationalItemModel.id == item_id
                )
                .first()
            )

            if record is None:
                return None

            return self._to_domain(record)

    def find_by_source_event(
        self,
        source_type: str,
        source_event_id: str,
        item_type: OperationalItemType,
    ) -> OperationalItem | None:

        with SessionLocal() as session:

            record = (
                session.query(OperationalItemModel)
                .filter(
                    and_(
                        OperationalItemModel.source_type
                        == source_type,
                        OperationalItemModel.source_event_id
                        == source_event_id,
                        OperationalItemModel.item_type
                        == item_type.value,
                    )
                )
                .first()
            )

            if record is None:
                return None

            return self._to_domain(record)

    def find_open(
        self,
        *,
        item_type: OperationalItemType | None = None,
        owner_id: str | None = None,
    ) -> list[OperationalItem]:

        with SessionLocal() as session:

            query = session.query(
                OperationalItemModel
            ).filter(
                OperationalItemModel.status.in_(
                    [
                        OperationalItemStatus.OPEN.value,
                        OperationalItemStatus.IN_PROGRESS.value,
                    ]
                )
            )

            if item_type is not None:
                query = query.filter(
                    OperationalItemModel.item_type
                    == item_type.value
                )

            if owner_id is not None:
                query = query.filter(
                    OperationalItemModel.owner_id
                    == owner_id
                )

            records = query.order_by(
                OperationalItemModel.created_at.desc()
            ).all()

            return [
                self._to_domain(record)
                for record in records
            ]

    def find_overdue(
        self,
        now: datetime,
    ) -> list[OperationalItem]:

        with SessionLocal() as session:

            records = (
                session.query(OperationalItemModel)
                .filter(
                    OperationalItemModel.due_at.isnot(None),
                    OperationalItemModel.due_at < now,
                    OperationalItemModel.status.in_(
                        [
                            OperationalItemStatus.OPEN.value,
                            OperationalItemStatus.IN_PROGRESS.value,
                        ]
                    ),
                )
                .order_by(
                    OperationalItemModel.due_at.asc()
                )
                .all()
            )

            return [
                self._to_domain(record)
                for record in records
            ]

    def update_status(
        self,
        item_id: str,
        status: OperationalItemStatus,
    ) -> OperationalItem | None:

        with SessionLocal() as session:

            record = (
                session.query(OperationalItemModel)
                .filter(
                    OperationalItemModel.id == item_id
                )
                .first()
            )

            if record is None:
                return None

            record.status = status.value
            record.updated_at = datetime.now(
                record.updated_at.tzinfo
            )

            session.commit()
            session.refresh(record)

            return self._to_domain(record)

    @staticmethod
    def _to_domain(
        record: OperationalItemModel,
    ) -> OperationalItem:

        return OperationalItem(
            identifier=Identifier(
                graph_id=UUID(record.id),
            ),
            item_type=OperationalItemType(
                record.item_type,
            ),
            summary=record.summary,
            status=OperationalItemStatus(
                record.status,
            ),
            priority=OperationalItemPriority(
                record.priority,
            ),
            owner_id=record.owner_id,
            owner_name=record.owner_name,
            due_at=record.due_at,
            source_event_id=record.source_event_id,
            source_type=record.source_type,
            confidence=record.confidence,
            evidence=list(record.evidence or []),
            metadata=dict(record.metadata_ or {}),
        )
