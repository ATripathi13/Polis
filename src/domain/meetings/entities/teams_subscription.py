"""
Domain entity for Microsoft Teams Graph subscriptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from domain.common.identifier import Identifier


@dataclass(slots=True)
class TeamsSubscription:
    """
    Represents an active Microsoft Graph subscription for Teams data.
    """

    identifier: Identifier
    subscription_id: str
    resource: str
    expiration_datetime: datetime
    client_state: str
    created_at: datetime
    updated_at: datetime

    @property
    def graph_id(self):
        return self.identifier.graph_id

    @classmethod
    def create(
        cls,
        *,
        subscription_id: str,
        resource: str,
        expiration_datetime: datetime,
        client_state: str,
        created_at: datetime,
        updated_at: datetime,
        business_id: str = "",
    ) -> "TeamsSubscription":

        return cls(
            identifier=Identifier(
                business_id=business_id,
            ),
            subscription_id=subscription_id,
            resource=resource,
            expiration_datetime=expiration_datetime,
            client_state=client_state,
            created_at=created_at,
            updated_at=updated_at,
        )