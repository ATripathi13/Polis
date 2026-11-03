from dataclasses import dataclass

from engines.communication.domain.value_objects import (
    Channel,
    CommunicationIdentity,
)


@dataclass(slots=True)
class SlackChannel:
    """
    Slack channel information.
    """

    channel_id: str

    name: str | None = None

    is_private: bool = False

    def to_channel(self) -> Channel:
        """
        Convert this Slack channel into a Communication Channel.
        """
        if self.channel_id.startswith("D"):
            channel_type = "im"
        elif self.channel_id.startswith("G"):
            channel_type = "mpim"
        elif self.is_private:
            channel_type = "private"
        else:
            channel_type = "public"

        return Channel(
            identity=CommunicationIdentity(
                internal_id=self.channel_id,
                external_ids={"slack": self.channel_id},
                metadata={"platform": "slack", "slack_channel_id": self.channel_id},
            ),
            name=self.name or self.channel_id,
            channel_type=channel_type,
            metadata={"platform": "slack", "slack_channel_id": self.channel_id},
        )