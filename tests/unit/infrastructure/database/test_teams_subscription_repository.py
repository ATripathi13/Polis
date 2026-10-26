from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from domain.meetings import TeamsSubscription
from infrastructure.database.models import TeamsSubscriptionModel
from infrastructure.database.teams_subscription_repository import (
    PostgreSQLTeamsSubscriptionRepository,
)


def test_teams_subscription_repository_save_and_find_active():
    repository = PostgreSQLTeamsSubscriptionRepository()
    now = datetime.now(timezone.utc)

    subscription = TeamsSubscription.create(
        subscription_id="polis-test-subscription",
        resource="/communications/onlineMeetings/getAllTranscripts",
        expiration_datetime=now + timedelta(hours=1),
        client_state="polis-teams-transcript",
        created_at=now,
        updated_at=now,
    )

    records = []
    session = MagicMock()

    def query_side_effect(model):
        query = MagicMock()
        query.filter.return_value = query
        query.order_by.return_value = query

        def first():
            if model is not TeamsSubscriptionModel:
                return None

            # Match the repository's save/delete subscription lookup.
            for record in records:
                if record.subscription_id == subscription.subscription_id:
                    return record

            # Match the active resource lookup.
            for record in records:
                if (
                    record.resource == subscription.resource
                    and record.expiration_datetime > datetime.now(timezone.utc)
                ):
                    return record

            return None

        query.first.side_effect = first
        return query

    session.query.side_effect = query_side_effect
    session.add.side_effect = records.append
    session.delete.side_effect = records.remove

    with patch(
        "infrastructure.database.teams_subscription_repository.SessionLocal"
    ) as session_factory:
        session_factory.return_value.__enter__.return_value = session

        repository.save(subscription)

        assert len(records) == 1
        assert records[0].subscription_id == "polis-test-subscription"

        found = repository.find_active(
            "/communications/onlineMeetings/getAllTranscripts"
        )

        assert found is not None
        assert found.subscription_id == "polis-test-subscription"
        assert (
            found.resource
            == "/communications/onlineMeetings/getAllTranscripts"
        )
        assert found.client_state == "polis-teams-transcript"

        repository.delete("polis-test-subscription")
        assert records == []

        assert repository.find_active(
            "/communications/onlineMeetings/getAllTranscripts"
        ) is None
