"""
Background renewal for the Microsoft Teams transcript subscription.
"""

from __future__ import annotations

import asyncio
import logging

from .teams_subscription_service import TeamsSubscriptionService

logger = logging.getLogger(__name__)


class TeamsSubscriptionRenewal:
    """
    Keeps the Microsoft Teams transcript subscription active.
    """

    CHECK_INTERVAL_SECONDS = 5 * 60

    def __init__(self, service: TeamsSubscriptionService) -> None:
        self._service = service
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return

        logger.warning("Teams subscription renewal worker starting")

        self._task = asyncio.create_task(
            self._run(),
            name="teams-subscription-renewal",
        )

    async def stop(self) -> None:
        if self._task is None:
            return

        logger.warning("Teams subscription renewal worker stopping")

        self._task.cancel()

        try:
            await self._task
        except asyncio.CancelledError:
            pass

        self._task = None

    async def _run(self) -> None:
        logger.warning("Teams subscription renewal worker running")

        while True:
            try:
                logger.warning(
                    "Checking Teams transcript subscription"
                )

                subscription = await asyncio.to_thread(
                    self._service.ensure_subscription
                )

                logger.warning(
                    "Teams transcript subscription check complete: "
                    "expires=%s",
                    subscription.expiration_datetime,
                )

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception(
                    "Failed to check Teams transcript subscription"
                )

            await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)
