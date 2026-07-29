"""server/matchmaker_service.py: the Matchmaker - the one process that
decides who plays whom. server/ws_server.py's WS Gateway used to run
server.matchmaking.find_opponent itself, against its own in-memory
`_queue` - but that queue was per Gateway *instance*, so two players
PLAY-ing on two different WS Gateway replicas would never be compared
against each other at all. The waiting pool lives here instead, in Redis
(QUEUE_KEY, a hash of connection_id -> json {username, rating, queued_at}),
reachable no matter which Gateway instance a given PLAY happened to land on.

PLAY requests arrive as NATS envelopes on INBOX_SUBJECT (published by
server/ws_server.py's _handle_play, once it's confirmed the connection is
authenticated and not already in a room - this service never checks either
of those itself, same division of responsibility server/shard.py's own
docstring describes for MOVE/JUMP). A match publishes the exact same
"match" envelope server/shard.py's GameShard._handle_match already expects
on its own inbox (SHARD_INBOX_SUBJECT) - shard.py needed no changes at all
for this split. A timeout instead sends "no_match" back through
server.nats_connection.NatsConnectionProxy, the same way server/shard.py
replies to a connection it doesn't hold a socket for either.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from server.db import build_redis_client
from server.logging_config import configure_server_logging
from server.matchmaking import find_opponent
from server.nats_connection import NatsConnectionProxy
from server.protocol import encode_no_match

logger = logging.getLogger(__name__)

INBOX_SUBJECT = "matchmaker.inbox"

# Same constant as server/ws_server.py's own INBOX_SUBJECT for server/
# shard.py - duplicated deliberately rather than imported, so this service
# never pulls in shard.py's GameEngine/Room import chain (same reasoning
# ws_server.py's own docstring gives for its copy of this constant).
SHARD_INBOX_SUBJECT = "shard.inbox"

QUEUE_KEY = "matchmaker:queue"

TICK_INTERVAL_SECONDS = 0.05

# How long a PLAY request waits for a compatible opponent before the
# player gets "no_match" instead - same value server/ws_server.py used
# before this split.
MATCHMAKING_TIMEOUT_SECONDS = 60


def _decode(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


class MatchmakerService:
    """Owns the shared waiting pool in Redis - see this module's own
    docstring for why it isn't in-process memory (unlike server/shard.py's
    `_rooms`, which is fine staying in-process since exactly one shard
    inbox reaches exactly one shard so far)."""

    def __init__(self, nats_client, redis_client):
        self._nats = nats_client
        self._redis = redis_client

    def _proxy_for(self, connection_id):
        return NatsConnectionProxy(self._nats, self._redis, connection_id)

    async def handle_message(self, msg):
        """The NATS subscription callback for INBOX_SUBJECT - one envelope
        per PLAY request. Fire-and-forget delivery, same reasoning as
        server/shard.py's own handle_message: a bad envelope must not
        crash the whole Matchmaker over one bad message."""
        try:
            envelope = json.loads(msg.data)
            await self._handle_play(envelope)
        except Exception:
            logger.exception("failed to handle matchmaker inbox message")

    async def _handle_play(self, envelope):
        connection_id = envelope["connection_id"]
        if self._redis.hexists(QUEUE_KEY, connection_id):
            return  # already searching - PLAY is a no-op, same guard ws_server.py used to apply

        waiting = [
            (_decode(other_id), json.loads(raw)["rating"])
            for other_id, raw in self._redis.hgetall(QUEUE_KEY).items()
        ]
        opponent_id = find_opponent(envelope["rating"], waiting)
        if opponent_id is None:
            entry = {"username": envelope["username"], "rating": envelope["rating"], "queued_at": time.time()}
            self._redis.hset(QUEUE_KEY, connection_id, json.dumps(entry))
            return

        opponent = json.loads(self._redis.hget(QUEUE_KEY, opponent_id))
        self._redis.hdel(QUEUE_KEY, opponent_id)
        logger.info("matched %s vs %s", envelope["username"], opponent["username"])
        await self._nats.publish(SHARD_INBOX_SUBJECT, json.dumps({
            "kind": "match",
            "players": [
                {"connection_id": connection_id, "username": envelope["username"], "rating": envelope["rating"]},
                {"connection_id": opponent_id, "username": opponent["username"], "rating": opponent["rating"]},
            ],
        }).encode("utf-8"))

    async def resolve_timeouts(self):
        now = time.time()
        for connection_id, raw in list(self._redis.hgetall(QUEUE_KEY).items()):
            info = json.loads(raw)
            if now - info["queued_at"] >= MATCHMAKING_TIMEOUT_SECONDS:
                connection_id = _decode(connection_id)
                self._redis.hdel(QUEUE_KEY, connection_id)
                logger.info("%s's matchmaking search timed out", info["username"])
                await self._proxy_for(connection_id).send(json.dumps(encode_no_match()))


async def run_forever(nats_client, redis_client, on_ready=None):
    """Runs the Matchmaker until cancelled. `on_ready(service)` mirrors
    server/shard.py's own run_forever - mainly so tests can reach the
    service instance without a module-level global."""
    service = MatchmakerService(nats_client, redis_client)
    await nats_client.subscribe(INBOX_SUBJECT, cb=service.handle_message)
    if on_ready is not None:
        on_ready(service)
    while True:
        await asyncio.sleep(TICK_INTERVAL_SECONDS)
        await service.resolve_timeouts()


def main():  # pragma: no cover
    configure_server_logging()
    redis_client = build_redis_client()

    async def _main():
        import nats

        nats_client = await nats.connect(os.environ["NATS_URL"])
        logger.info("starting KungFu Chess Matchmaker, connected to %s", os.environ["NATS_URL"])
        await run_forever(nats_client, redis_client)

    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
