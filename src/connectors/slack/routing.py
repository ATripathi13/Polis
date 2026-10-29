"""
Slack message routing, mention detection, text cleaning, and event deduplication.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
import re
import threading
import time

logger = logging.getLogger(__name__)


def clean_slack_text(text: str, bot_user_id: str | None = None) -> str:
    """
    Remove bot mentions and redundant whitespace from Slack message text.

    Strips:
    - Slack user mentions for the bot: <@BOT_ID> or <@BOT_ID|name>
    - Plain-text @polis mentions (case-insensitive)
    - Leading/trailing whitespace
    """
    if not text:
        return ""

    cleaned = text

    if bot_user_id and bot_user_id.strip():
        cleaned = re.sub(
            rf"<@{re.escape(bot_user_id.strip())}(?:\|[^>]+)?>",
            "",
            cleaned,
        )

    # Strip explicit @polis mention token if present
    cleaned = re.sub(r"(?i)@polis\b", "", cleaned)

    return cleaned.strip()


def is_bot_mentioned(text: str, bot_user_id: str | None = None) -> bool:
    """
    Determine whether POLIS is explicitly mentioned in the Slack message text.

    Recognizes:
    - <@BOT_ID> or <@BOT_ID|...>
    - Case-insensitive @polis mention
    """
    if not text:
        return False

    if bot_user_id and bot_user_id.strip():
        bot_id = bot_user_id.strip()
        if f"<@{bot_id}>" in text or f"<@{bot_id}|" in text:
            return True

    if re.search(r"(?i)(?:^|\s)@polis\b", text):
        return True

    return False


def is_direct_message(event: dict, channel_id: str | None = None) -> bool:
    """
    Determine whether a Slack event occurred in a 1-to-1 Direct Message.

    Checks:
    - event.channel_type == 'im'
    - channel ID starting with 'D'
    """
    channel_type = event.get("channel_type")
    if channel_type == "im":
        return True

    cid = channel_id or event.get("channel")
    if isinstance(cid, str) and cid.startswith("D"):
        return True

    return False


class EventDeduplicator:
    """
    Thread-safe, bounded in-memory deduplicator for Slack events.

    Tracks (channel_id, ts) tuples to prevent duplicate processing
    from retries or multiple handler callbacks within a single process.

    Runtime architecture boundary:
    This deduplicator operates strictly in-memory per process. It does not provide
    cross-process deduplication if multiple listener instances run concurrently in
    separate processes against the same Slack workspace. Cross-process deduplication
    would require external coordination (such as Redis or database locks).
    """

    def __init__(self, max_entries: int = 1000) -> None:
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._seen: OrderedDict[tuple[str, str], float] = OrderedDict()

    def is_duplicate(self, channel_id: str, ts: str) -> bool:
        """
        Check if an event key has already been seen.
        If not seen, registers it and returns False.
        If already seen, returns True.
        """
        if not channel_id or not ts:
            return False

        key = (channel_id, ts)
        with self._lock:
            if key in self._seen:
                return True

            self._seen[key] = time.time()
            if len(self._seen) > self._max_entries:
                self._seen.popitem(last=False)

            return False

    def clear(self) -> None:
        """Clear all registered event keys."""
        with self._lock:
            self._seen.clear()
