"""server/allocator_service.py: the Game Allocator - the one process that
decides *which* Game Server Shard replica a new room lands on. server/
ws_server.py's ROOM CREATE and server/matchmaker_service.py's matched pair
both used to publish straight to a single, shared shard inbox subject -
fine with exactly one Shard replica, but with more than one, every replica
subscribing to the same subject would each independently create their own
copy of "the same" room (plain NATS pub/sub fanout, not a queue group).

This service instead reads every Shard's own heartbeat
(`shard:heartbeat:{instance_id}` -> its current active-room count, written
by server/shard.py's own tick()) and picks a target via power-of-two-
choices: two candidates at random, whichever reported fewer rooms wins -
see Server_Design.md for why that's treated as good enough versus asking
Redis for the single least-loaded instance outright. It then reserves that
room_id's ownership lease in Redis (`room_owner:{room_id}` -> instance_id,
a `SET NX EX` - atomically claims the id and starts its lease in the same
step, so a collision with an existing room_id is detected by the NX
itself, not a separate check-then-set race) before ever telling the chosen
Shard to create anything - that Shard's own subsequent tick()s just renew
a lease this service already started, they don't originate it.

A "need_room" request (one player, from ROOM CREATE; two, from a
Matchmaker-found match) arrives as {"players": [{"connection_id",
"username", "rating"}, ...]} on INBOX_SUBJECT. Once a shard and room_id
are chosen, this publishes the exact "create_room" envelope server/
shard.py's GameShard.handle_message already expects on that instance's own
inbox subject (SHARD_INBOX_SUBJECT_TEMPLATE) - shard.py needed no further
changes for this beyond receiving that kind instead of "match"/ROOM_CREATE
directly (see that module's own docstring/history for the split).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import secrets
from typing import Callable

from server.db import build_redis_client, decode_redis_value
from server.health import start_health_server
from server.inbox import handle_inbox_message
from server.logging_config import configure_server_logging
from server.nats_connection import NatsConnectionProxy
from server.protocol import encode_error

logger = logging.getLogger(__name__)

INBOX_SUBJECT = "allocator.inbox"

# Internal only, same reasoning as server/ws_server.py's own HEALTH_PORT.
HEALTH_PORT = 9100

# Same constant as server/shard.py's own INBOX_SUBJECT_TEMPLATE - duplicated
# deliberately rather than imported, so this service never pulls in
# shard.py's GameEngine/Room import chain (same reasoning server/
# ws_server.py's own docstring gives for its copies of other services'
# subject constants).
SHARD_INBOX_SUBJECT_TEMPLATE = "shard.inbox.{instance_id}"

# Same TTL server/shard.py's own PRESENCE_TTL_SECONDS uses for its lease
# renewals - this service only ever sets it once, for the instant between
# "room_id chosen" and the owning Shard's first tick() renewing it for
# real, so a small drift between the two constants wouldn't matter in
# practice, but they're kept equal for clarity.
PRESENCE_TTL_SECONDS = 10


class AllocatorService:
    def __init__(self, nats_client: object, redis_client: object) -> None:
        self._nats = nats_client
        self._redis = redis_client

    def _proxy_for(self, connection_id: str) -> NatsConnectionProxy:
        return NatsConnectionProxy(self._nats, self._redis, connection_id)

    def _pick_shard_instance(self) -> str | None:
        """Power-of-two-choices over every Shard currently heartbeating -
        see this module's own docstring. Returns None if no Shard is
        reachable at all (nothing heartbeating in Redis right now)."""
        keys = [decode_redis_value(key) for key in self._redis.keys("shard:heartbeat:*")]
        instance_ids = [key[len("shard:heartbeat:"):] for key in keys]
        if not instance_ids:
            return None
        if len(instance_ids) == 1:
            return instance_ids[0]

        candidates = random.sample(instance_ids, 2)
        loads = [(int(self._redis.get(f"shard:heartbeat:{cid}") or 0), cid) for cid in candidates]
        loads.sort(key=lambda pair: pair[0])
        return loads[0][1]

    async def handle_message(self, msg: object) -> None:
        """The NATS subscription callback for INBOX_SUBJECT - one envelope
        per need_room request. Fire-and-forget delivery, same reasoning as
        server/shard.py's own handle_message: a bad envelope must not
        crash the whole Allocator over one bad message - see server/
        inbox.py's shared handle_inbox_message for that try/parse/
        dispatch/except shape."""
        await handle_inbox_message(msg, self._dispatch, "allocator inbox message", logger)

    async def _dispatch(self, envelope: dict) -> None:
        await self._handle_need_room(envelope["players"])

    async def _handle_need_room(self, players: list[dict]) -> None:
        instance_id = self._pick_shard_instance()
        if instance_id is None:
            # No Shard is currently reachable at all - nothing sensible to
            # allocate to. This can't happen in the deployed topology
            # (docker-compose.yml's ws-server/matchmaker both depend_on
            # game-shard), but the player(s) who asked for a room still
            # need to hear *something* instead of waiting forever with no
            # signal at all - same reasoning as server/matchmaker_service.py's
            # own timeout path back through NatsConnectionProxy.
            logger.warning("no Game Server Shard is reachable - dropping a room request for %s",
                            [player["username"] for player in players])
            message = json.dumps(encode_error("No game server available right now - please try again"))
            for player in players:
                await self._proxy_for(player["connection_id"]).send(message)
            return

        room_id = secrets.token_hex(3)
        while not self._redis.set(f"room_owner:{room_id}", instance_id, nx=True, ex=PRESENCE_TTL_SECONDS):
            room_id = secrets.token_hex(3)

        logger.info("allocated room %s to shard %s for %s",
                    room_id, instance_id, [player["username"] for player in players])
        await self._nats.publish(SHARD_INBOX_SUBJECT_TEMPLATE.format(instance_id=instance_id), json.dumps({
            "kind": "create_room", "room_id": room_id, "players": players,
        }).encode("utf-8"))


async def run_forever(
    nats_client: object, redis_client: object, on_ready: Callable | None = None, health_port: int = HEALTH_PORT,
) -> None:
    """Runs the Allocator until cancelled. `on_ready(service, health_runner)`
    mirrors server/shard.py's own run_forever - mainly so tests can reach
    the service instance without a module-level global. No periodic work
    of its own (unlike the Shard/Matchmaker's own tick loops) - it's purely
    reactive to need_room requests, so this just has to stay alive.
    `health_port=0` is how tests avoid colliding on the fixed default
    HEALTH_PORT across separate test runs. No custom metrics (see
    server/health.py's own default) - this service is stateless/reactive,
    with nothing per-instance worth gauging beyond bare liveness."""
    service = AllocatorService(nats_client, redis_client)
    await nats_client.subscribe(INBOX_SUBJECT, cb=service.handle_message)
    health_runner = await start_health_server("0.0.0.0", health_port)
    if on_ready is not None:
        on_ready(service, health_runner)
    await asyncio.Future()


def main():  # pragma: no cover
    configure_server_logging()
    redis_client = build_redis_client()

    async def _main():
        import nats

        nats_client = await nats.connect(os.environ["NATS_URL"])
        logger.info("starting KungFu Chess Allocator, connected to %s", os.environ["NATS_URL"])
        await run_forever(nats_client, redis_client)

    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
