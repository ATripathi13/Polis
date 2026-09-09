import asyncio

from infrastructure.config.settings import get_settings
from api.dependencies import (
    get_slack_service,
    get_activity_processor,
)
from connectors.slack.socket.listener import SlackSocketListener


async def main():
    settings = get_settings()

    listener = SlackSocketListener(
        settings.slack_bot_token,
        settings.slack_app_token,
        get_slack_service(),
        get_activity_processor(),
    )

    await listener.start()


if __name__ == "__main__":
    asyncio.run(main())
