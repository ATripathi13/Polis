"""
Unit tests for run_slack_listener.py lifecycle and signal handling.
"""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from run_slack_listener import main


@pytest.mark.asyncio
async def test_run_slack_listener_main_starts_and_stops_cleanly():
    """Verify run_slack_listener.main starts listener and cleanly invokes stop() upon shutdown."""
    mock_listener = MagicMock()
    mock_listener.start = AsyncMock()
    mock_listener.stop = AsyncMock()

    with patch("run_slack_listener.configure_logging"), \
         patch("run_slack_listener.get_settings"), \
         patch("run_slack_listener.bootstrap"), \
         patch("run_slack_listener.get_slack_service"), \
         patch("run_slack_listener.get_activity_processor"), \
         patch("run_slack_listener.get_knowledge_base_ingestion_service"), \
         patch("run_slack_listener.SlackSocketListener", return_value=mock_listener):

        # Make start() sleep briefly so stop_event can trigger
        async def mock_start():
            await asyncio.sleep(0.01)

        mock_listener.start.side_effect = mock_start

        await main()

        assert mock_listener.start.called
        assert mock_listener.stop.called


@pytest.mark.asyncio
async def test_run_slack_listener_handles_windows_signal_unsupported():
    """Verify run_slack_listener gracefully falls back on Windows where loop.add_signal_handler raises NotImplementedError."""
    mock_listener = MagicMock()
    mock_listener.start = AsyncMock(return_value=None)
    mock_listener.stop = AsyncMock()

    with patch("run_slack_listener.configure_logging"), \
         patch("run_slack_listener.get_settings"), \
         patch("run_slack_listener.bootstrap"), \
         patch("run_slack_listener.get_slack_service"), \
         patch("run_slack_listener.get_activity_processor"), \
         patch("run_slack_listener.get_knowledge_base_ingestion_service"), \
         patch("run_slack_listener.SlackSocketListener", return_value=mock_listener), \
         patch("asyncio.get_running_loop") as mock_get_loop:

        loop = MagicMock()
        loop.add_signal_handler.side_effect = NotImplementedError("Windows unsupported")
        loop.create_task = asyncio.create_task
        mock_get_loop.return_value = loop

        # Should not raise NotImplementedError
        await main()

        assert mock_listener.stop.called


@pytest.mark.asyncio
async def test_run_slack_listener_propagates_listener_start_exception_and_stops():
    """Verify run_slack_listener cleanly invokes stop() even if listener.start() fails with exception."""
    mock_listener = MagicMock()
    mock_listener.start = AsyncMock(side_effect=RuntimeError("Fatal listener connection error"))
    mock_listener.stop = AsyncMock()

    with patch("run_slack_listener.configure_logging"), \
         patch("run_slack_listener.get_settings"), \
         patch("run_slack_listener.bootstrap"), \
         patch("run_slack_listener.get_slack_service"), \
         patch("run_slack_listener.get_activity_processor"), \
         patch("run_slack_listener.get_knowledge_base_ingestion_service"), \
         patch("run_slack_listener.SlackSocketListener", return_value=mock_listener):

        with pytest.raises(RuntimeError, match="Fatal listener connection error"):
            await main()

        assert mock_listener.stop.called
