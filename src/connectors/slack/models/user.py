from dataclasses import dataclass
from engines.communication.domain.value_objects import (
    Actor,
    CommunicationIdentity,
)


@dataclass(slots=True)
class SlackUser:
    """
    Slack user information.
    """

    user_id: str

    username: str | None = None

    email: str | None = None

    def to_actor(self) -> Actor:
        """
        Convert this Slack user into a Communication Actor.
        """

        return Actor(
            identity=CommunicationIdentity(
                internal_id=self.user_id,
                external_ids={"slack": self.user_id},
                metadata={"platform": "slack", "slack_user_id": self.user_id},
            ),
            display_name=self.username or self.user_id,
            email=self.email,
            metadata={"platform": "slack", "slack_user_id": self.user_id},
        )