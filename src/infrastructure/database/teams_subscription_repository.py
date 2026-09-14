"""
PostgreSQL repository for Microsoft Teams Graph subscriptions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import TeamsSubscriptionModel

from domain.common.identifier import Identifier
from domain.meetings import TeamsSubscription
from domain.meetings.repositories.teams_subscription_repository import (
    TeamsSubscriptionRepository,
)


class PostgreSQLTeamsSubscriptionRepository(
    TeamsSubscriptionRepository
):
    """
    PostgreSQL implementation of TeamsSubscriptionRepository.
    """

    def save(
        self,
        subscription: TeamsSubscription,
    ) -> None:

        with SessionLocal() as session:

            record = (
                session.query(TeamsSubscriptionModel)
                .filter(
                    TeamsSubscriptionModel.subscription_id
                    == subscription.subscription_id
                )
                .first()
            )

            if record is None:

                record = TeamsSubscriptionModel(
                    id=str(uuid4()),
                    subscription_id=subscription.subscription_id,
                    resource=subscription.resource,
                    expiration_datetime=subscription.expiration_datetime,
                    client_state=subscription.client_state,
                    created_at=subscription.created_at,
                    updated_at=subscription.updated_at,
                )

                session.add(record)

            else:

                record.resource = subscription.resource
                record.expiration_datetime = (
                    subscription.expiration_datetime
                )
                record.client_state = subscription.client_state
                record.updated_at = subscription.updated_at

            session.commit()

    def find_active(self) -> TeamsSubscription | None:

        now = datetime.now(timezone.utc)

        with SessionLocal() as session:

            record = (
                session.query(TeamsSubscriptionModel)
                .filter(
                    TeamsSubscriptionModel.expiration_datetime > now
                )
                .order_by(
                    TeamsSubscriptionModel.expiration_datetime.desc()
                )
                .first()
            )

            if record is None:
                return None

            return self._to_domain(record)

    def delete(
        self,
        subscription_id: str,
    ) -> None:

        with SessionLocal() as session:

            record = (
                session.query(TeamsSubscriptionModel)
                .filter(
                    TeamsSubscriptionModel.subscription_id
                    == subscription_id
                )
                .first()
            )

            if record is not None:
                session.delete(record)
                session.commit()

    @staticmethod
    def _to_domain(
        record: TeamsSubscriptionModel,
    ) -> TeamsSubscription:

        return TeamsSubscription(
            identifier=Identifier(
                graph_id=uuid4(),
            ),
            subscription_id=record.subscription_id,
            resource=record.resource,
            expiration_datetime=record.expiration_datetime,
            client_state=record.client_state,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )