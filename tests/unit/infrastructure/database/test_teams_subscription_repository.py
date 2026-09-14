from datetime import datetime, timedelta, timezone

from domain.meetings import TeamsSubscription
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

    repository.save(subscription)

    found = repository.find_active()

    assert found is not None
    assert found.subscription_id == "polis-test-subscription"
    assert (
        found.resource
        == "/communications/onlineMeetings/getAllTranscripts"
    )
    assert found.client_state == "polis-teams-transcript"

    repository.delete("polis-test-subscription")

    assert repository.find_active() is None