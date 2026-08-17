"""server/shard.py: a Game Server Shard - hosts every live server.room.Room
(and its GameEngine, the sole source of truth for game rules) on this one
process, exactly like server.ws_server.GameServer used to before the
split. Commands arrive as NATS messages instead of directly from a
websockets connection (see server/ws_server.py, now the WS Gateway - it
holds the real sockets, this process never does), and every reply/
broadcast goes out through a server.nats_connection.NatsConnectionProxy
instead of a real connection - Room itself (server/room.py) is completely
unaware any of this happened; it still just calls connection.send(...).

Unlike server/ws_server.py's shared outbox-per-instance scheme, each Shard
subscribes to its *own* inbox subject (INBOX_SUBJECT_TEMPLATE, keyed by
`instance_id`) rather than one subject every replica would otherwise all
receive - see server/allocator_service.py's own docstring for why: once
more than one Shard replica exists, "which one" a new room lands on is a
real decision (the Allocator's job), not something every replica can just
independently decide for itself off a shared subject anymore.

This Shard also periodically reports its own liveness/capacity to Redis
(`shard:heartbeat:{instance_id}` -> its current room count, the Allocator's
power-of-two-choices input) and renews a lease on every room_id it
currently hosts (`room_owner:{room_id}` -> instance_id, both under
PRESENCE_TTL_SECONDS) - see tick(). That lease is what lets
server/ws_server.py route ROOM_JOIN/MOVE/JUMP/SELECT/disconnect to the
right Shard instance, and what keeps that routing table from pointing at
a Shard that's actually crashed forever (the TTL simply lapses instead).

Envelopes arriving on this instance's own inbox subject are one of:
  {"kind": "command", "connection_id": str, "username": str, "rating": int,
   "room_id": str | None, "raw": str}
      - `raw` is an ordinary server.protocol.py wire command ("MOVE a3 c3",
        "ROOM JOIN abc123", ...) - the same text a client would have sent
        directly before this split existed. `room_id` is only needed for
        MOVE/JUMP/SELECT (ws_server.py already tracks which room a
        connection is in); ROOM_JOIN carries `username`/`rating` instead,
        since the joiner might be a reconnect the room needs to reclaim.
  {"kind": "create_room", "room_id": str,
   "players": [{"connection_id", "username", "rating"}, ...]}
      - server/allocator_service.py has already picked *this* instance and
        reserved `room_id`'s ownership lease in Redis - just create the
        Room and seat everyone in `players` (one, for ROOM CREATE; two,
        for a Matchmaker-found match).
  {"kind": "disconnect", "connection_id": str, "room_id": str}
      - the real socket for connection_id dropped (ws_server.py's
        handle_connection loop ending) - Room.handle_disconnect starts the
        reconnect grace period exactly as it always has.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from types import ModuleType
from typing import Callable

from bus.event_bus import EventBus
from config import settings
from game.engine_factory import build_engine
from server.db import AccountStore, PostgresAccountStore, build_redis_client
from server.health import start_health_server
from server.logging_config import configure_server_logging
from server.nats_connection import NatsConnectionProxy
from server.protocol import Command, ProtocolError, encode_error, parse_command
from server.room import Room

logger = logging.getLogger(__name__)

# Keyed by instance_id, not a plain subject string like server/
# matchmaker_service.py's or server/allocator_service.py's own INBOX_SUBJECT
# - see this module's own docstring for why.
INBOX_SUBJECT_TEMPLATE = "shard.inbox.{instance_id}"

# Internal only, same reasoning as server/ws_server.py's own HEALTH_PORT -
# curled from inside this container by docker-compose.yml's healthcheck:,
# never mapped to the host (each game-shard replica binds this same
# number inside its own isolated container, no collision).
HEALTH_PORT = 9100

# Same cadence as ws_server.py's own TICK_INTERVAL_SECONDS - real-time
# motion (a move landing, a rest cooldown expiring) has to reach clients
# without waiting for someone to send another command, exactly as before
# the split.
TICK_INTERVAL_SECONDS = 0.05

# TTL for both this Shard's heartbeat and every room_id lease it renews
# (see tick()) - long enough that renewing once per TICK_INTERVAL_SECONDS
# tolerates a brief Redis hiccup without a spurious expiry, short enough
# that a genuinely crashed Shard's entries clear out in a few seconds
# rather than lingering forever.
PRESENCE_TTL_SECONDS = 10

STANDARD_BOARD_TEXT = [
    "bR bN bB bQ bK bB bN bR",
    "bP bP bP bP bP bP bP bP",
    ". . . . . . . .",
    ". . . . . . . .",
    ". . . . . . . .",
    ". . . . . . . .",
    "wP wP wP wP wP wP wP wP",
    "wR wN wB wQ wK wB wN wR",
]


class GameShard:
    """Owns every Room, exactly like GameServer used to before the split.
    `accounts` is only needed by Room itself (Elo updates on game_over) -
    this class never checks a password (see server/api_gateway.py) or a
    token (see server/ws_server.py's own _handle_auth) - both already
    happened before a command ever reaches here. `instance_id` identifies
    *this* Shard process/container - same role and default
    (socket.gethostname()) as server/ws_server.py's GameServer, used both
    for this instance's own inbox subject (see run_forever) and as the
    value it heartbeats/leases into Redis (see tick()).
    """

    def __init__(
        self,
        nats_client: object,
        redis_client: object,
        config: ModuleType = settings,
        accounts: AccountStore | None = None,
        board_lines: list[str] | None = None,
        instance_id: str | None = None,
    ) -> None:
        self._nats = nats_client
        self._redis = redis_client
        self._config = config
        self._instance_id = instance_id or socket.gethostname()
        self._board_lines = board_lines or STANDARD_BOARD_TEXT
        self._colors = tuple(config.COLORS)
        self._accounts = accounts if accounts is not None else AccountStore()
        self._rooms: dict[str, Room] = {}  # room_id -> Room
        self._proxies: dict[str, NatsConnectionProxy] = {}  # connection_id -> proxy (one per connection, reused)

    def _proxy_for(self, connection_id: str) -> NatsConnectionProxy:
        proxy = self._proxies.get(connection_id)
        if proxy is None:
            proxy = NatsConnectionProxy(self._nats, self._redis, connection_id)
            self._proxies[connection_id] = proxy
        return proxy

    def _new_room(self, room_id: str) -> Room:
        events = EventBus()
        engine = build_engine(self._board_lines, self._config, events=events)
        room = Room(room_id, engine, self._colors, self._accounts)
        self._rooms[room_id] = room
        return room

    def metrics(self) -> dict:
        """Fed to server/health.py's GET /metrics by run_forever - see
        that module's own docstring for the format."""
        return {"kf_chess_shard_active_rooms": len(self._rooms)}

    async def tick(self) -> None:
        """Advances every Room's real-time clock, then reports this
        instance's own liveness/capacity and renews every room_id lease it
        currently holds - see this module's own docstring for why both
        matter once more than one Shard replica exists.

        Also prunes any room that just finished: nothing else can happen in
        a Room once its engine reports game over (no new move, no new
        disconnect grace period), so it would otherwise sit in self._rooms
        - and keep having its lease renewed below - for the rest of this
        process's life. A finished room's own final broadcast already went
        out from the room.tick() call above, before it's dropped here.
        """
        now = time.monotonic()
        for room_id, room in list(self._rooms.items()):
            await room.tick(now)
            if room.game_over:
                del self._rooms[room_id]
        # self._redis is the plain synchronous redis.Redis client - run each
        # round-trip in a worker thread so it doesn't block this whole
        # Shard's event loop (every room/connection it's holding) while
        # Redis answers.
        await asyncio.to_thread(
            self._redis.setex, f"shard:heartbeat:{self._instance_id}", PRESENCE_TTL_SECONDS, len(self._rooms),
        )
        for room_id in self._rooms:
            await asyncio.to_thread(
                self._redis.setex, f"room_owner:{room_id}", PRESENCE_TTL_SECONDS, self._instance_id,
            )

    async def handle_message(self, msg: object) -> None:
        """The NATS subscription callback for this instance's own inbox
        subject - one envelope per room-creation instruction, client
        command, or disconnect, forwarded here by server/ws_server.py or
        server/allocator_service.py. This is fire-and-forget delivery (see
        the module docstring - not NATS request/reply), so there's no
        caller waiting on this to propagate an exception to; a malformed
        envelope or a bug here must not crash the whole shard process over
        one bad message."""
        try:
            envelope = json.loads(msg.data)
            kind = envelope.get("kind")
            if kind == "create_room":
                await self._handle_create_room(envelope["room_id"], envelope["players"])
            elif kind == "disconnect":
                await self._handle_disconnect(envelope)
            else:
                await self._handle_command(envelope)
        except Exception:
            logger.exception("failed to handle shard inbox message")

    async def _handle_create_room(self, room_id: str, players: list[dict]) -> None:
        # server/allocator_service.py has already picked this instance and
        # reserved room_id's lease - just create the Room and seat
        # everyone (one player for ROOM CREATE, two for a Matchmaker-found
        # match). Every player is seated *before* welcoming any of them -
        # welcome() checks room.started to decide whether to send
        # "waiting_for_opponent", and seating only one side first would
        # make it True too early for a 2-player match, sending that
        # message to whoever got welcomed first even though their
        # opponent is about to be seated a moment later.
        room = self._new_room(room_id)
        proxies_and_roles = []
        for player in players:
            proxy = self._proxy_for(player["connection_id"])
            role = room.seat_or_view(proxy, player["username"], player["rating"])
            proxies_and_roles.append((proxy, role))
        for proxy, role in proxies_and_roles:
            await room.welcome(proxy, role)

    async def _handle_disconnect(self, envelope: dict) -> None:
        room = self._rooms.get(envelope["room_id"])
        # Drop the cached proxy along with handling the disconnect itself -
        # connection_ids are never reused (server/ws_server.py mints a fresh
        # one, secrets.token_hex(8), per socket), so nothing will ever look
        # this one up again; leaving it in self._proxies would just grow
        # that dict for as long as this process runs. _proxy_for recreates
        # one on demand if anything unexpected still asks for it.
        proxy = self._proxies.pop(envelope["connection_id"], None)
        if room is not None and proxy is not None:
            await room.handle_disconnect(proxy)

    async def _handle_command(self, envelope: dict) -> None:
        proxy = self._proxy_for(envelope["connection_id"])
        try:
            command = parse_command(envelope["raw"])
        except ProtocolError as error:
            await proxy.send(json.dumps(encode_error(str(error))))
            return

        if command.verb == "ROOM_JOIN":
            await self._handle_room_join(proxy, envelope, command.args[0])
            return

        # MOVE / JUMP / SELECT - the only verbs left; route to the room
        # ws_server.py already knows this connection is in.
        room = self._rooms.get(envelope.get("room_id"))
        if room is None:
            await proxy.send(json.dumps(encode_error("Not in a room")))
            return
        await room.handle_command(proxy, command)

    async def _handle_room_join(self, proxy: NatsConnectionProxy, envelope: dict, room_id: str) -> None:
        room = self._rooms.get(room_id)
        if room is None:
            await proxy.send(json.dumps(encode_error(f"Room {room_id!r} not found")))
            return

        was_started = room.started
        was_reconnecting = room.is_reclaimable(envelope["username"])
        role = room.seat_or_view(proxy, envelope["username"], envelope["rating"])
        await room.welcome(proxy, role)
        if was_reconnecting:
            await room.notify_reconnected(role)
        if room.started and not was_started:
            await room.notify_room_started(exclude=proxy)


async def run_forever(
    nats_client: object,
    redis_client: object,
    config: ModuleType = settings,
    accounts: AccountStore | None = None,
    board_lines: list[str] | None = None,
    on_ready: Callable | None = None,
    instance_id: str | None = None,
    health_port: int = HEALTH_PORT,
) -> None:
    """Runs the shard until cancelled. `on_ready(shard, health_runner)` is
    called once the NATS subscription is actually active - mirrors
    server/ws_server.py's serve_forever's own on_ready, mainly so tests can
    reach the shard instance without a module-level global. `instance_id`
    is resolved once here (rather than read back off `shard._instance_id`)
    since it's also needed to build the subscription subject itself.
    `health_port=0` is how tests avoid colliding on the fixed default
    HEALTH_PORT across separate test runs."""
    instance_id = instance_id or socket.gethostname()
    shard = GameShard(nats_client, redis_client, config=config, accounts=accounts, board_lines=board_lines,
                       instance_id=instance_id)
    await nats_client.subscribe(INBOX_SUBJECT_TEMPLATE.format(instance_id=instance_id), cb=shard.handle_message)
    health_runner = await start_health_server("0.0.0.0", health_port, shard.metrics)
    if on_ready is not None:
        on_ready(shard, health_runner)
    while True:
        await asyncio.sleep(TICK_INTERVAL_SECONDS)
        await shard.tick()


def main():  # pragma: no cover
    configure_server_logging()

    # Same DB_BACKEND choice as server/ws_server.py's and server/
    # api_gateway.py's own main() - duplicated deliberately, not shared,
    # for the same reason given there: each service is its own
    # composition root.
    if os.environ.get("DB_BACKEND", "sqlite") == "postgres":
        dsn = (
            f"host={os.environ['POSTGRES_HOST']} "
            f"port={os.environ['POSTGRES_PORT']} "
            f"dbname={os.environ['POSTGRES_DB']} "
            f"user={os.environ['POSTGRES_USER']} "
            f"password={os.environ['POSTGRES_PASSWORD']}"
        )
        accounts = PostgresAccountStore(dsn)
    else:
        from pathlib import Path
        accounts = AccountStore(str(Path(__file__).resolve().parent / "accounts.db"))

    redis_client = build_redis_client()

    async def _main():
        import nats

        nats_client = await nats.connect(os.environ["NATS_URL"])
        logger.info("starting KungFu Chess Game Shard, connected to %s", os.environ["NATS_URL"])
        await run_forever(nats_client, redis_client, accounts=accounts)

    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
