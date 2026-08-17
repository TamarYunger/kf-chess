"""server/inbox.py's own tests - the shared parse/dispatch/except shape
every NATS inbox callback in this codebase (GameShard's, MatchmakerService's,
AllocatorService's) delegates to.
"""
import asyncio
import json
import logging
from types import SimpleNamespace

from server.inbox import handle_inbox_message

logger = logging.getLogger("test_inbox")


def run(coro):
    return asyncio.run(coro)


def test_a_well_formed_envelope_reaches_dispatch():
    async def scenario():
        received = []

        async def dispatch(envelope):
            received.append(envelope)

        msg = SimpleNamespace(data=json.dumps({"kind": "ping"}).encode("utf-8"))
        await handle_inbox_message(msg, dispatch, "test message", logger)

        assert received == [{"kind": "ping"}]

    run(scenario())


def test_a_malformed_envelope_is_logged_not_raised(caplog):
    async def scenario():
        async def dispatch(envelope):
            raise AssertionError("must not be called for a malformed envelope")

        msg = SimpleNamespace(data=b"not json")
        with caplog.at_level(logging.ERROR, logger="test_inbox"):
            await handle_inbox_message(msg, dispatch, "test message", logger)  # must not raise

        assert any("failed to handle test message" in record.message for record in caplog.records)

    run(scenario())


def test_a_dispatch_failure_is_logged_not_raised(caplog):
    async def scenario():
        async def dispatch(envelope):
            raise RuntimeError("boom")

        msg = SimpleNamespace(data=json.dumps({"kind": "ping"}).encode("utf-8"))
        with caplog.at_level(logging.ERROR, logger="test_inbox"):
            await handle_inbox_message(msg, dispatch, "test message", logger)  # must not raise

        assert any("failed to handle test message" in record.message for record in caplog.records)

    run(scenario())
