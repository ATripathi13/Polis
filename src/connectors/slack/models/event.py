from dataclasses import dataclass

from .channel import SlackChannel
from .message import SlackMessage
from .user import SlackUser


@dataclass(slots=True)
class SlackEvent:
    """
    Complete Slack event.
    """

    user: SlackUser

    channel: SlackChannel

    message: SlackMessage