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

        return Channel(
            identity=CommunicationIdentity(
                internal_id=self.channel_id,
            ),
            name=self.name or self.channel_id,
            channel_type="private" if self.is_private else "public",
        )