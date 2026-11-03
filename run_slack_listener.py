import asyncio
import logging
import signal

from infrastructure.config.settings import get_settings
from infrastructure.logging import configure_logging
from api.dependencies import (
    get_slack_service,
    get_activity_processor,
    get_knowledge_base_ingestion_service,
)
from application.bootstrap.bootstrap import bootstrap
from connectors.slack.socket.listener import SlackSocketListener

logger = logging.getLogger(__name__)


async def main():
    configure_logging()
    settings = get_settings()
    application = bootstrap()

    listener = SlackSocketListener(
        settings.slack_bot_token,
        settings.slack_app_token,
        get_slack_service(),
        get_activity_processor(),
        get_knowledge_base_ingestion_service(),
        reminder_service=application.reminder_service,
        calendar_agent=application.calendar_agent,
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _trigger_stop():
        stop_event.set()

    for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
        if sig is not None:
            try:
                loop.add_signal_handler(sig, _trigger_stop)
            except (NotImplementedError, AttributeError):
                try:
                    signal.signal(sig, lambda *_: _trigger_stop())
                except Exception:
                    pass

    try:
        listener_task = asyncio.create_task(listener.start())
        stop_wait_task = asyncio.create_task(stop_event.wait())

        done, pending = await asyncio.wait(
            [listener_task, stop_wait_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if listener_task in done and not listener_task.cancelled():
            exc = listener_task.exception()
            if exc:
                raise exc

    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info(
            "Listener shutdown requested",
            extra={"operation": "listener_shutdown_requested"},
        )
    finally:
        await listener.stop()


if __name__ == "__main__":
    asyncio.run(main())
