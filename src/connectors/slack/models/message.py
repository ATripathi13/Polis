from dataclasses import dataclass

from engines.communication.domain.value_objects import Content


@dataclass(slots=True)
class SlackMessage:
    """
    Slack message.
    """

    text: str

    ts: str

    thread_ts: str | None = None

    def to_content(self) -> Content:
        """
        Convert this Slack message into Communication Content.
        """

        return Content(
            body=self.text,
        )