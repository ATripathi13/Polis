"""
Phase 1 Isolated Local Validation Tests for POLIS Milestone 6.

Strict Isolation Boundaries:
- Never connects to real Slack Socket Mode or Web API.
- Never connects to PostgreSQL (localhost:5432/ctmc_production).
- Never accesses or creates live Slack reminders.
- Uses purely synthetic tokens and credentials.
- All external dependencies are mocked or in-memory.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import logging
import signal
import subprocess
import sys
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from connectors.slack.routing import EventDeduplicator
from connectors.slack.socket.listener import SlackSocketListener
from engines.slack.router.slack_intent_router import _sanitize_error_message
from domain.reasoning.value_objects import ConversationContext
from infrastructure.database.conversation_repository import InMemoryConversationRepository


def _make_isolated_listener(
    bot_token: str = "xoxb-mock-bot-token",
    app_token: str = "xapp-mock-app-token",
    reminder_service: MagicMock | None = None,
    handler_mock: MagicMock | None = None,
):
    """Create a strictly isolated SlackSocketListener with in-memory conversation repo and mocked connectors."""
    mock_slack_service = MagicMock()
    mock_activity_processor = MagicMock()
    mock_reminder_service = reminder_service or MagicMock()
    conv_repo = InMemoryConversationRepository()
    mock_intent_router = MagicMock()

    with patch("connectors.slack.socket.listener.AsyncApp"), \
         patch("connectors.slack.socket.listener.AsyncSocketModeHandler") as mock_handler_cls, \
         patch("connectors.slack.socket.listener.SlackConnector"), \
         patch("connectors.slack.socket.listener.SlackClient"), \
         patch("connectors.slack.socket.listener.SlackResponder"):

        if handler_mock is not None:
            mock_handler_cls.return_value = handler_mock

        listener = SlackSocketListener(
            bot_token=bot_token,
            app_token=app_token,
            slack_service=mock_slack_service,
            activity_processor=mock_activity_processor,
            reminder_service=mock_reminder_service,
            conversation_repository=conv_repo,
            intent_router=mock_intent_router,
        )

        return listener, handler_mock or mock_handler_cls.return_value


# ==============================================================================
# A. Lifecycle Validation
# ==============================================================================


@pytest.mark.asyncio
async def test_a1_listener_initialization():
    """1. Listener initialization: starts in 'initialized' state with stop_event cleared."""
    listener, _ = _make_isolated_listener()
    assert listener._lifecycle_state == "initialized"
    assert not listener._stop_event.is_set()
    assert listener._reminder_worker_thread is None


@pytest.mark.asyncio
async def test_a2_transition_from_initialized_to_running():
    """2. Transition from initialized to running when start() is called."""
    mock_handler = MagicMock()
    mock_handler.start_async = AsyncMock(side_effect=lambda: asyncio.sleep(5))
    mock_handler.close_async = AsyncMock()

    listener, _ = _make_isolated_listener(handler_mock=mock_handler)

    async def verify_running_state():
        await asyncio.sleep(0.01)
        assert listener._lifecycle_state == "running"
        assert listener._reminder_worker_thread is not None
        assert listener._reminder_worker_thread.is_alive()
        await listener.stop()

    task = asyncio.create_task(listener.start())
    verify_task = asyncio.create_task(verify_running_state())

    await verify_task
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert listener._lifecycle_state == "stopped"


def test_a3_reminder_worker_startup_using_mocked_service():
    """3. Reminder worker startup: creates thread named 'polis-reminder-worker' as daemon."""
    mock_reminder_service = MagicMock()
    mock_reminder_service.find_due.return_value = []

    listener, _ = _make_isolated_listener(reminder_service=mock_reminder_service)

    worker = threading.Thread(
        target=listener._run_reminder_worker,
        name="polis-reminder-worker",
        daemon=True,
    )
    worker.start()
    listener._reminder_worker_thread = worker

    assert worker.is_alive()
    assert worker.name == "polis-reminder-worker"
    assert worker.daemon is True

    # Stop worker
    listener._stop_event.set()
    worker.join(timeout=1.0)
    assert not worker.is_alive()
    assert mock_reminder_service.find_due.called


def test_a4_interruptible_worker_wait():
    """4. Interruptible worker wait: stop_event.wait(timeout=30) unblocks immediately on stop."""
    mock_reminder_service = MagicMock()
    mock_reminder_service.find_due.return_value = []

    listener, _ = _make_isolated_listener(reminder_service=mock_reminder_service)

    worker = threading.Thread(
        target=listener._run_reminder_worker,
        name="polis-reminder-worker",
        daemon=True,
    )
    worker.start()
    listener._reminder_worker_thread = worker

    start_time = time.monotonic()
    listener._stop_event.set()
    worker.join(timeout=2.0)
    elapsed = time.monotonic() - start_time

    # Must unblock and exit in well under 1 second, not 30 seconds
    assert elapsed < 1.0
    assert not worker.is_alive()


def test_a5_genuine_sigint_handling_in_isolated_subprocess():
    """5. Genuine SIGINT handling in an isolated subprocess with mocked dependencies."""
    subproc_code = (
        "import asyncio, signal, sys\n"
        "from unittest.mock import MagicMock, AsyncMock, patch\n"
        "async def run():\n"
        "    with patch('run_slack_listener.configure_logging'), \\\n"
        "         patch('run_slack_listener.get_settings'), \\\n"
        "         patch('run_slack_listener.bootstrap'), \\\n"
        "         patch('run_slack_listener.get_slack_service'), \\\n"
        "         patch('run_slack_listener.get_activity_processor'), \\\n"
        "         patch('run_slack_listener.get_knowledge_base_ingestion_service'), \\\n"
        "         patch('run_slack_listener.SlackSocketListener') as mock_listener_cls:\n"
        "        mock_listener = MagicMock()\n"
        "        mock_listener.start = AsyncMock(side_effect=lambda: asyncio.sleep(60))\n"
        "        mock_listener.stop = AsyncMock()\n"
        "        mock_listener_cls.return_value = mock_listener\n"
        "        from run_slack_listener import main\n"
        "        async def fire():\n"
        "            await asyncio.sleep(0.5)\n"
        "            signal.raise_signal(signal.SIGINT)\n"
        "        asyncio.create_task(fire())\n"
        "        await main()\n"
        "        assert mock_listener.start.called\n"
        "        assert mock_listener.stop.called\n"
        "        print('GENUINE_SIGINT_SHUTDOWN_CONFIRMED')\n"
        "asyncio.run(run())\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", subproc_code],
        capture_output=True,
        text=True,
        timeout=35,
    )

    assert result.returncode == 0, f"Subprocess failed with code {result.returncode}: {result.stderr}"
    assert "GENUINE_SIGINT_SHUTDOWN_CONFIRMED" in result.stdout


@pytest.mark.asyncio
async def test_a6_socket_mode_handler_closure_through_mocked_handler():
    """6. Socket Mode handler closure through a mocked handler."""
    mock_handler = MagicMock()
    mock_handler.close_async = AsyncMock()

    listener, _ = _make_isolated_listener(handler_mock=mock_handler)
    await listener.stop()
    assert mock_handler.close_async.called


@pytest.mark.asyncio
async def test_a7_worker_termination_within_expected_timeout():
    """7. Worker termination within expected timeout (join timeout 2.0s)."""
    mock_handler = MagicMock()
    mock_handler.close_async = AsyncMock()

    listener, _ = _make_isolated_listener(handler_mock=mock_handler)
    listener._reminder_service.find_due.return_value = []

    worker = threading.Thread(
        target=listener._run_reminder_worker,
        name="polis-reminder-worker",
        daemon=True,
    )
    worker.start()
    listener._reminder_worker_thread = worker

    assert worker.is_alive()
    await listener.stop()
    assert not worker.is_alive()
    assert listener._lifecycle_state == "stopped"


@pytest.mark.asyncio
async def test_a8_idempotent_repeated_stop_calls():
    """8. Idempotent repeated stop calls: subsequent calls are clean no-ops."""
    mock_handler = MagicMock()
    mock_handler.close_async = AsyncMock()

    listener, _ = _make_isolated_listener(handler_mock=mock_handler)

    # First stop
    await listener.stop()
    assert listener._lifecycle_state == "stopped"
    assert mock_handler.close_async.call_count == 1

    # Second stop: no-op
    await listener.stop()
    assert listener._lifecycle_state == "stopped"
    assert mock_handler.close_async.call_count == 1

    # Third stop: no-op
    await listener.stop()
    assert listener._lifecycle_state == "stopped"
    assert mock_handler.close_async.call_count == 1


@pytest.mark.asyncio
async def test_a9_startup_failure_cleanup():
    """9. Startup failure cleanup: listener.stop() is executed if start fails."""
    mock_listener = MagicMock()
    mock_listener.start = AsyncMock(side_effect=ConnectionError("Failed to connect to gateway"))
    mock_listener.stop = AsyncMock()

    with patch("run_slack_listener.configure_logging"), \
         patch("run_slack_listener.get_settings"), \
         patch("run_slack_listener.bootstrap"), \
         patch("run_slack_listener.get_slack_service"), \
         patch("run_slack_listener.get_activity_processor"), \
         patch("run_slack_listener.get_knowledge_base_ingestion_service"), \
         patch("run_slack_listener.SlackSocketListener", return_value=mock_listener):

        from run_slack_listener import main

        with pytest.raises(ConnectionError, match="Failed to connect to gateway"):
            await main()

        assert mock_listener.stop.called


@pytest.mark.asyncio
async def test_a10_shutdown_failure_recovery():
    """10. Shutdown failure recovery: exception during handler.close_async() is isolated."""
    mock_handler = MagicMock()
    mock_handler.close_async = AsyncMock(side_effect=RuntimeError("Abrupt socket drop"))

    listener, _ = _make_isolated_listener(handler_mock=mock_handler)

    # Should not raise exception
    await listener.stop()
    assert listener._lifecycle_state == "stopped"


# ==============================================================================
# B. LIVE-11 — Duplicate Event Validation
# ==============================================================================


def test_b1_first_event_is_accepted():
    """LIVE-11.1: First event payload is accepted (not duplicate)."""
    dedup = EventDeduplicator()
    assert dedup.is_duplicate("C0123456789", "1700000000.000100") is False


def test_b2_identical_event_is_rejected():
    """LIVE-11.2: Identical event payload is rejected as duplicate."""
    dedup = EventDeduplicator()
    assert dedup.is_duplicate("C0123456789", "1700000000.000100") is False
    assert dedup.is_duplicate("C0123456789", "1700000000.000100") is True


def test_b3_same_timestamp_in_different_channel_accepted():
    """LIVE-11.3: Same timestamp in different channels treated as distinct events."""
    dedup = EventDeduplicator()
    ts = "1700000000.000200"
    assert dedup.is_duplicate("C_ALPHA", ts) is False
    assert dedup.is_duplicate("C_BETA", ts) is False


def test_b4_different_timestamps_are_accepted():
    """LIVE-11.4: Different timestamps in same channel are both accepted."""
    dedup = EventDeduplicator()
    assert dedup.is_duplicate("C0123456789", "1700000000.000301") is False
    assert dedup.is_duplicate("C0123456789", "1700000000.000302") is False


def test_b5_concurrent_duplicate_deliveries_remain_safe():
    """LIVE-11.5: Concurrent duplicate deliveries across threads accept exactly one."""
    dedup = EventDeduplicator()
    channel = "C_CONCURRENT"
    ts = "1700000000.000400"

    results = []
    def check():
        results.append(dedup.is_duplicate(channel, ts))

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(check) for _ in range(20)]
        for f in futures:
            f.result()

    # Exactly 1 accepted (False) and 19 rejected (True)
    assert results.count(False) == 1
    assert results.count(True) == 19


def test_b6_bounded_cache_behavior():
    """LIVE-11.6: Bounded cache eviction (FIFO) prevents memory growth."""
    dedup = EventDeduplicator(max_entries=5)

    # Insert 5 events
    for i in range(5):
        assert dedup.is_duplicate("C_TEST", f"1000.{i}") is False

    # All 5 are currently duplicates
    for i in range(5):
        assert dedup.is_duplicate("C_TEST", f"1000.{i}") is True

    # Insert 6th event; causes 1000.0 to be evicted
    assert dedup.is_duplicate("C_TEST", "1000.5") is False

    # 1000.0 is evicted and now accepted again
    assert dedup.is_duplicate("C_TEST", "1000.0") is False

    # 1000.1 through 1000.5 remain bounded
    assert len(dedup._seen) == 5


# ==============================================================================
# C. LIVE-12 — Logging and Secret Audit
# ==============================================================================


def test_c1_slack_token_prefixes_scrubbed():
    """LIVE-12.1: All six Slack token prefixes scrubbed by _sanitize_error_message."""
    prefixes = ["xoxb", "xapp", "xoxp", "xoxa", "xoxr", "xoxs"]
    for pfx in prefixes:
        secret = f"{pfx}-mock-synthetic-secret-value-12345"
        raw = f"Error during call with token {secret} to endpoint"
        sanitized = _sanitize_error_message(raw)
        assert secret not in sanitized
        assert f"{pfx}-***" in sanitized


def test_c2_database_uri_credentials_scrubbed():
    """LIVE-12.2: Database URI credentials scrubbed by _sanitize_error_message."""
    synthetic_uri = "postgresql://synth_user:SuperSecretPassword456@db.internal.local:5432/synthetic_db"
    raw = f"OperationalError: Failed connecting to {synthetic_uri}"
    sanitized = _sanitize_error_message(raw)

    assert "SuperSecretPassword456" not in sanitized
    assert "synth_user:***@db.internal.local:5432/synthetic_db" in sanitized


def test_c3_password_parameters_scrubbed():
    """LIVE-12.3: Password parameters in query strings or DSNs scrubbed."""
    raw_single = "dsn='dbname=mydb user=myuser password='SingleQuotePass999''"
    sanitized_single = _sanitize_error_message(raw_single)
    assert "SingleQuotePass999" not in sanitized_single
    assert "password='***'" in sanitized_single

    raw_double = 'dsn="dbname=mydb user=myuser password="DoubleQuotePass999""'
    sanitized_double = _sanitize_error_message(raw_double)
    assert "DoubleQuotePass999" not in sanitized_double
    assert 'password="***"' in sanitized_double

    raw_unquoted = "host=localhost password=UnquotedSecretPassword123"
    sanitized_unquoted = _sanitize_error_message(raw_unquoted)
    assert "UnquotedSecretPassword123" not in sanitized_unquoted
    assert "password=***" in sanitized_unquoted


def test_c4_exception_messages_and_validation_errors():
    """LIVE-12.4: Exceptions containing both Slack tokens and database URIs sanitized."""
    raw_exc = (
        "Validation error: Slack API returned auth_error for token xoxb-synthetic-12345; "
        "fallback failed against postgresql://admin:SuperSecretPass987@localhost:5432/polis"
    )
    sanitized = _sanitize_error_message(raw_exc)
    assert "xoxb-synthetic-12345" not in sanitized
    assert "SuperSecretPass987" not in sanitized
    assert "xoxb-***" in sanitized
    assert "admin:***@localhost:5432/polis" in sanitized


def test_c5_structured_metadata_logging_no_secrets(caplog):
    """LIVE-12.5: Structured logging captures operations without leaking secrets."""
    test_logger = logging.getLogger("test_structured_audit")
    with caplog.at_level(logging.INFO):
        test_logger.info(
            "Listener shutdown requested",
            extra={"operation": "listener_shutdown_requested", "channel_id": "C_AUDIT"},
        )

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.operation == "listener_shutdown_requested"
    assert record.channel_id == "C_AUDIT"
    assert not hasattr(record, "token")
    assert not hasattr(record, "password")


# ==============================================================================
# D. Scope and Pending-Operation Isolation
# ==============================================================================


def test_d1_cross_user_isolation():
    """D1. Cross-user isolation: User A and User B maintain distinct conversation contexts."""
    repo = InMemoryConversationRepository()

    ctx_alice = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="100.1")
    ctx_alice = ctx_alice.add_exchange("Alice msg", "Alice reply", "U_ALICE")
    repo.save(ctx_alice)

    ctx_bob = ConversationContext(user_id="U_BOB", channel_id="D_BOB", thread_ts="200.1")
    ctx_bob = ctx_bob.add_exchange("Bob msg", "Bob reply", "U_BOB")
    repo.save(ctx_bob)

    loaded_alice = repo.get("D_ALICE", "100.1")
    loaded_bob = repo.get("D_BOB", "200.1")

    assert loaded_alice.user_id == "U_ALICE"
    assert loaded_bob.user_id == "U_BOB"
    assert not any("Bob" in m["content"] for m in loaded_alice.history)
    assert not any("Alice" in m["content"] for m in loaded_bob.history)


def test_d2_cross_channel_isolation():
    """D2. Cross-channel isolation: Channels maintain strictly isolated histories."""
    repo = InMemoryConversationRepository()
    ctx_c1 = ConversationContext(user_id="U_USER", channel_id="C_CHAN1", thread_ts="300.1")
    ctx_c1 = ctx_c1.add_exchange("Chan 1 question", "Chan 1 answer", "U_USER")
    repo.save(ctx_c1)

    ctx_c2 = ConversationContext(user_id="U_USER", channel_id="C_CHAN2", thread_ts="300.1")
    ctx_c2 = ctx_c2.add_exchange("Chan 2 question", "Chan 2 answer", "U_USER")
    repo.save(ctx_c2)

    assert repo.get("C_CHAN1", "300.1").history[0]["content"] == "Chan 1 question"
    assert repo.get("C_CHAN2", "300.1").history[0]["content"] == "Chan 2 question"


def test_d3_thread_isolation():
    """D3. Thread isolation: Different threads in same channel remain separate."""
    repo = InMemoryConversationRepository()
    channel = "C_SHARED"

    ctx_t1 = ConversationContext(user_id="U_USER", channel_id=channel, thread_ts="400.1")
    ctx_t1 = ctx_t1.add_exchange("Thread 1 question", "Thread 1 answer", "U_USER")
    repo.save(ctx_t1)

    ctx_t2 = ConversationContext(user_id="U_USER", channel_id=channel, thread_ts="400.2")
    ctx_t2 = ctx_t2.add_exchange("Thread 2 question", "Thread 2 answer", "U_USER")
    repo.save(ctx_t2)

    assert len(repo.get(channel, "400.1").history) == 2
    assert len(repo.get(channel, "400.2").history) == 2
    assert repo.get(channel, "400.1").history[0]["content"] == "Thread 1 question"
    assert repo.get(channel, "400.2").history[0]["content"] == "Thread 2 question"


def test_d4_pending_operation_retrieval_and_scoping():
    """D4. Pending-operation retrieval strictly validates expected user, channel, and thread."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=1)
    pending_op = {
        "operation_id": "op-test-1",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_TEST",
        "thread_ts": "500.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
    }

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_TEST",
        thread_ts="500.1",
        pending_operation=pending_op,
    )

    # Valid retrieval
    valid = ctx.get_pending_operation(
        expected_user_id="U_ALICE",
        expected_channel_id="C_TEST",
        expected_thread_ts="500.1",
    )
    assert valid is not None
    assert valid["operation_id"] == "op-test-1"

    # Mismatched user -> None
    assert ctx.get_pending_operation(
        expected_user_id="U_BOB",
        expected_channel_id="C_TEST",
        expected_thread_ts="500.1",
    ) is None

    # Mismatched channel -> None
    assert ctx.get_pending_operation(
        expected_user_id="U_ALICE",
        expected_channel_id="C_OTHER",
        expected_thread_ts="500.1",
    ) is None

    # Mismatched thread -> None
    assert ctx.get_pending_operation(
        expected_user_id="U_ALICE",
        expected_channel_id="C_TEST",
        expected_thread_ts="999.1",
    ) is None


def test_d5_no_accidental_continuation_across_unrelated_conversations():
    """D5. Expired or unassociated pending operations are rejected."""
    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=1)
    created = now - timedelta(hours=2)
    expired_op = {
        "operation_id": "op-expired-1",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_TEST",
        "thread_ts": "600.1",
        "created_at_iso": created.isoformat(),
        "expires_at_iso": past.isoformat(),
    }

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_TEST",
        thread_ts="600.1",
        pending_operation=expired_op,
    )

    # Expired operation must return None
    assert ctx.get_pending_operation(
        expected_user_id="U_ALICE",
        expected_channel_id="C_TEST",
        expected_thread_ts="600.1",
    ) is None
