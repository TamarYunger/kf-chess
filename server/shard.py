"""server/shard.py: a Game Server Shard - hosts every live server.room.Room
(and its GameEngine, the sole source of truth for game rules) on this one
process, exactly like server.ws_server.GameServer used to before the
split. The only thing that changed is *how* it's reached: commands arrive
as NATS messages instead of directly from a websockets connection (see
server/ws_server.py, now the WS Gateway - it holds the real sockets, this
process never does), and every reply/broadcast goes out through a
server.nats_connection.NatsConnectionProxy instead of a real connection -
Room itself (server/room.py) is completely unaware any of this happened;
it still just calls connection.send(...).

Envelopes arriving on INBOX_SUBJECT (published by ws_server.py) are one of:
  {"kind": "command", "connection_id": str, "username": str, "rating": int,
   "room_id": str | None, "raw": str}
      - `raw` is an ordinary server.protocol.py wire command ("MOVE a3 c3",
        "ROOM CREATE", ...) - the same text a client would have sent
        directly before this split existed. `room_id` is only needed for
        MOVE/JUMP/SELECT (ws_server.py already tracks which room a
        connection is in); ROOM_CREATE/ROOM_JOIN carry `username`/`rating`
        instead, since a room might not exist to look either up from yet.
  {"kind": "match", "players": [{"connection_id", "username", "rating"}, ...]}
      - PLAY's matchmaking found a pair (still decided in ws_server.py,
        server.matchmaking.find_opponent is unchanged) - seats both in one
        new room together, same as GameServer._handle_play used to do
        directly.
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
import secrets
import time

from board.loaders import load_text_board
from bus.event_bus import EventBus
from config import settings
from game.engine import GameEngine
from realtime.real_time_arbiter import RealTimeArbiter
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion
from rules.rule_engine import RuleEngine
from rules.rule_registry import build_default_registry
from server.db import AccountStore, PostgresAccountStore, build_redis_client
from server.logging_config import configure_server_logging
from server.nats_connection import NatsConnectionProxy
from server.protocol import ProtocolError, encode_error, parse_command
from server.room import Room

logger = logging.getLogger(__name__)

INBOX_SUBJECT = "shard.inbox"

# Same cadence as ws_server.py's own TICK_INTERVAL_SECONDS - real-time
# motion (a move landing, a rest cooldown expiring) has to reach clients
# without waiting for someone to send another command, exactly as before
# the split.
TICK_INTERVAL_SECONDS = 0.05

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


def build_engine(board_lines, config=settings, events=None):
    registry = build_default_registry(config)
    board = load_text_board(board_lines, registry, config)
    arbiter = RealTimeArbiter(board=board, promotion_rule=LastRankPromotion(config.PAWN_DIRECTION), config=config)
    return GameEngine(
        board=board,
        rule_engine=RuleEngine(rule_registry=registry, config=config),
        arbiter=arbiter,
        win_condition=KingCaptureWinCondition(),
        config=config,
        events=events,
    )


class GameShard:
    """Owns every Room, exactly like GameServer used to before the split.
    `accounts` is only needed by Room itself (Elo updates on game_over) -
    this class never checks a password (see server/api_gateway.py) or a
    token (see server/ws_server.py's own _handle_auth) - both already
    happened before a command ever reaches here.
    """

    def __init__(self, nats_client, redis_client, config=settings, accounts=None, board_lines=None):
        self._nats = nats_client
        self._redis = redis_client
        self._config = config
        self._board_lines = board_lines or STANDARD_BOARD_TEXT
        self._colors = tuple(config.COLORS)
        self._accounts = accounts if accounts is not None else AccountStore()
        self._rooms = {}  # room_id -> Room
        self._proxies = {}  # connection_id -> NatsConnectionProxy (one per connection, reused)

    def _proxy_for(self, connection_id):
        proxy = self._proxies.get(connection_id)
        if proxy is None:
            proxy = NatsConnectionProxy(self._nats, self._redis, connection_id)
            self._proxies[connection_id] = proxy
        return proxy

    def _new_room(self):
        room_id = self._generate_room_id()
        events = EventBus()
        engine = build_engine(self._board_lines, self._config, events=events)
        room = Room(room_id, engine, self._colors, self._accounts)
        self._rooms[room_id] = room
        return room

    def _generate_room_id(self):
        room_id = secrets.token_hex(3)
        while room_id in self._rooms:
            room_id = secrets.token_hex(3)
        return room_id

    async def tick(self):
        now = time.monotonic()
        for room in list(self._rooms.values()):
            await room.tick(now)

    async def handle_message(self, msg):
        """The NATS subscription callback for INBOX_SUBJECT - one envelope
        per client command, matched pair, or disconnect, forwarded here by
        server/ws_server.py. This is fire-and-forget delivery (see the
        module docstring - not NATS request/reply), so there's no caller
        waiting on this to propagate an exception to; a malformed envelope
        or a bug here must not crash the whole shard process over one bad
        message."""
        try:
            envelope = json.loads(msg.data)
            kind = envelope.get("kind")
            if kind == "match":
                await self._handle_match(envelope["players"])
            elif kind == "disconnect":
                await self._handle_disconnect(envelope)
            else:
                await self._handle_command(envelope)
        except Exception:
            logger.exception("failed to handle shard inbox message")

    async def _handle_match(self, players):
        # Seat *both* players before welcoming either - welcome() checks
        # room.started to decide whether to send "waiting_for_opponent",
        # and seating only one side first would make it True too early,
        # sending that message to whoever got welcomed first even though
        # their opponent is about to be seated a moment later (this
        # mirrors the exact ordering server/ws_server.py's old
        # _handle_play used before this split, for the same reason).
        room = self._new_room()
        proxies_and_roles = []
        for player in players:
            proxy = self._proxy_for(player["connection_id"])
            role = room.seat_or_view(proxy, player["username"], player["rating"])
            proxies_and_roles.append((proxy, role))
        for proxy, role in proxies_and_roles:
            await room.welcome(proxy, role)

    async def _handle_disconnect(self, envelope):
        room = self._rooms.get(envelope["room_id"])
        proxy = self._proxies.get(envelope["connection_id"])
        if room is not None and proxy is not None:
            await room.handle_disconnect(proxy)

    async def _handle_command(self, envelope):
        proxy = self._proxy_for(envelope["connection_id"])
        try:
            command = parse_command(envelope["raw"])
        except ProtocolError as error:
            await proxy.send(json.dumps(encode_error(str(error))))
            return

        if command.verb == "ROOM_CREATE":
            room = self._new_room()
            role = room.seat_or_view(proxy, envelope["username"], envelope["rating"])
            await room.welcome(proxy, role)
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

    async def _handle_room_join(self, proxy, envelope, room_id):
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


async def run_forever(nats_client, redis_client, config=settings, accounts=None, board_lines=None, on_ready=None):
    """Runs the shard until cancelled. `on_ready(shard)` is called once the
    NATS subscription is actually active - mirrors server/ws_server.py's
    serve_forever's own on_ready, mainly so tests can reach the shard
    instance without a module-level global."""
    shard = GameShard(nats_client, redis_client, config=config, accounts=accounts, board_lines=board_lines)
    await nats_client.subscribe(INBOX_SUBJECT, cb=shard.handle_message)
    if on_ready is not None:
        on_ready(shard)
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
