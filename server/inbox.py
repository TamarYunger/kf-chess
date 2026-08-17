"""Shared shape for a NATS inbox subscription callback: parse the JSON
envelope, hand it to the service's own per-kind dispatch, and swallow any
exception so one malformed envelope can't take down the whole subscription
over a single bad message. server/shard.py's GameShard, server/
matchmaker_service.py's MatchmakerService, and server/allocator_service.py's
AllocatorService each re-typed this exact try/parse/dispatch/except shape
under their own handle_message - kept here so a change to it (e.g. what
counts as swallowable) only has to be made once.
"""
from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable


async def handle_inbox_message(
    msg: object, dispatch: Callable[[dict], Awaitable[None]], description: str, logger: logging.Logger,
) -> None:
    """`logger` is the caller's own module logger (not one defined here), so
    a failure is still attributed to the service that actually hit it
    (server.shard, server.matchmaker_service, server.allocator_service) -
    not to this shared helper."""
    try:
        envelope = json.loads(msg.data)
        await dispatch(envelope)
    except Exception:
        logger.exception("failed to handle %s", description)
