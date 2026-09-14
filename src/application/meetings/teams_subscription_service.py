from __future__ import annotations

from datetime import datetime, timedelta, timezone

from domain.meetings import TeamsSubscription
from domain.meetings.repositories import TeamsSubscriptionRepository


class TeamsSubscriptionService:
    """
    Manages the lifecycle of the POLIS Microsoft Teams transcript
    Graph subscription.
    """

    CLIENT_STATE = "polis-teams-transcript"
    RESOURCE = "communications/onlineMeetings/getAllTranscripts"
    RENEWAL_THRESHOLD_MINUTES = 15

    def __init__(
        self,
        repository: TeamsSubscriptionRepository,
        provider,
        *,
        notification_url: str,
        subscription_lifetime_hours: int = 1,
        now_provider=None,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.notification_url = notification_url
        self.subscription_lifetime_hours = (
            subscription_lifetime_hours
        )
        self._now_provider = now_provider or (
            lambda: datetime.now(timezone.utc)
        )

    def ensure_subscription(self) -> TeamsSubscription:
        existing = self.repository.find_active()

        now = self._now_provider()

        if existing is not None:

            renewal_threshold = (
                now
                + timedelta(
                    minutes=self.RENEWAL_THRESHOLD_MINUTES,
                )
            )

            if existing.expiration_datetime > renewal_threshold:
                return existing

            expiration_datetime = (
                now
                + timedelta(
                    hours=self.subscription_lifetime_hours,
                )
            )

            data = self.provider.renew_subscription(
                subscription_id=existing.subscription_id,
                expiration_datetime=expiration_datetime,
            )

            renewed = TeamsSubscription.create(
                subscription_id=data["id"],
                resource=data.get(
                    "resource",
                    existing.resource,
                ),
                expiration_datetime=self._parse_datetime(
                    data["expirationDateTime"]
                ),
                client_state=data.get(
                    "clientState",
                    existing.client_state,
                ),
                created_at=existing.created_at,
                updated_at=now,
            )

            self.repository.save(renewed)

            return renewed

        expiration_datetime = (
            now
            + timedelta(
                hours=self.subscription_lifetime_hours,
            )
        )

        data = self.provider.create_subscription(
            resource=self.RESOURCE,
            notification_url=self.notification_url,
            expiration_datetime=expiration_datetime,
            client_state=self.CLIENT_STATE,
        )

        subscription = TeamsSubscription.create(
            subscription_id=data["id"],
            resource=data["resource"],
            expiration_datetime=self._parse_datetime(
                data["expirationDateTime"]
            ),
            client_state=data["clientState"],
            created_at=now,
            updated_at=now,
        )

        self.repository.save(subscription)

        return subscription

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )