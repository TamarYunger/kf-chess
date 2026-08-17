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
docstring describes for MOVE/JUMP). A match forwards a "need_room" request
(the same shape server/ws_server.py's own ROOM CREATE forwards, just with
two players instead of one) to server/allocator_service.py's Allocator
(ALLOCATOR_INBOX_SUBJECT) rather than publishing straight to a Shard - see
that module's own docstring for why picking *which* Shard replica hosts a
new room is a real decision now, not something this service (or
server/shard.py itself) can still assume there's only ever one answer to.
A timeout instead sends "no_match" back through
server.nats_connection.NatsConnectionProxy, the same way server/shard.py
replies to a connection it doesn't hold a socket for either.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Callable

from server.db import build_redis_client
from server.health import start_health_server
from server.logging_config import configure_server_logging
from server.matchmaking import find_opponent
from server.nats_connection import NatsConnectionProxy
from server.protocol import encode_no_match

logger = logging.getLogger(__name__)

INBOX_SUBJECT = "matchmaker.inbox"

# Internal only, same reasoning as server/ws_server.py's own HEALTH_PORT.
HEALTH_PORT = 9100

# Same constant as server/ws_server.py's own ALLOCATOR_INBOX_SUBJECT -
# duplicated deliberately rather than imported, so this service never
# pulls in server/allocator_service.py's own import chain (same reasoning
# ws_server.py's own docstring gives for its copies of other services'
# subject constants).
ALLOCATOR_INBOX_SUBJECT = "allocator.inbox"

QUEUE_KEY = "matchmaker:queue"

TICK_INTERVAL_SECONDS = 0.05

# How long a PLAY request waits for a compatible opponent before the
# player gets "no_match" instead - same value server/ws_server.py used
# before this split.
MATCHMAKING_TIMEOUT_SECONDS = 60


def _decode(value: bytes | str) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


class MatchmakerService:
    """Owns the shared waiting pool in Redis - see this module's own
    docstring for why it isn't in-process memory (unlike server/shard.py's
    `_rooms`, which is fine staying in-process since exactly one shard
    inbox reaches exactly one shard so far)."""

    def __init__(self, nats_client: object, redis_client: object) -> None:
        self._nats = nats_client
        self._redis = redis_client

    def _proxy_for(self, connection_id: str) -> NatsConnectionProxy:
        return NatsConnectionProxy(self._nats, self._redis, connection_id)

    async def handle_message(self, msg: object) -> None:
        """The NATS subscription callback for INBOX_SUBJECT - one envelope
        per PLAY request. Fire-and-forget delivery, same reasoning as
        server/shard.py's own handle_message: a bad envelope must not
        crash the whole Matchmaker over one bad message."""
        try:
            envelope = json.loads(msg.data)
            await self._handle_play(envelope)
        except Exception:
            logger.exception("failed to handle matchmaker inbox message")

    async def _handle_play(self, envelope: dict) -> None:
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
        await self._nats.publish(ALLOCATOR_INBOX_SUBJECT, json.dumps({
            "players": [
                {"connection_id": connection_id, "username": envelope["username"], "rating": envelope["rating"]},
                {"connection_id": opponent_id, "username": opponent["username"], "rating": opponent["rating"]},
            ],
        }).encode("utf-8"))

    async def resolve_timeouts(self) -> None:
        now = time.time()
        for connection_id, raw in list(self._redis.hgetall(QUEUE_KEY).items()):
            info = json.loads(raw)
            if now - info["queued_at"] >= MATCHMAKING_TIMEOUT_SECONDS:
                connection_id = _decode(connection_id)
                self._redis.hdel(QUEUE_KEY, connection_id)
                logger.info("%s's matchmaking search timed out", info["username"])
                await self._proxy_for(connection_id).send(json.dumps(encode_no_match()))

    def metrics(self) -> dict:
        """Fed to server/health.py's GET /metrics by run_forever - see
        that module's own docstring for the format."""
        return {"kf_chess_matchmaker_queue_depth": self._redis.hlen(QUEUE_KEY)}


async def run_forever(
    nats_client: object, redis_client: object, on_ready: Callable | None = None, health_port: int = HEALTH_PORT,
) -> None:
    """Runs the Matchmaker until cancelled. `on_ready(service, health_runner)`
    mirrors server/shard.py's own run_forever - mainly so tests can reach
    the service instance without a module-level global. `health_port=0` is
    how tests avoid colliding on the fixed default HEALTH_PORT across
    separate test runs."""
    service = MatchmakerService(nats_client, redis_client)
    await nats_client.subscribe(INBOX_SUBJECT, cb=service.handle_message)
    health_runner = await start_health_server("0.0.0.0", health_port, service.metrics)
    if on_ready is not None:
        on_ready(service, health_runner)
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
