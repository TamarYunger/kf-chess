"""The lobby: a WebSocket server that authenticates connections (LOGIN)
and gets them into a server.room.Room - either automatically, matched by
rating (PLAY, server.matchmaking), or manually by id (ROOM CREATE/JOIN) -
then routes their MOVE/JUMP commands to whichever room they're in. Every
room owns its own GameEngine; this class owns none directly.

This is the third place in the codebase that wires up a GameEngine, next
to main.py's run() (the batch/script CLI) and view/local_game_session.py
(the offline GUI path) - each is its own composition root for its own
entry point, so a small amount of duplicated wiring here is expected
rather than a shortcut worth removing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from pathlib import Path

import websockets
import websockets.exceptions

from board.loaders import load_text_board
from bus.event_bus import EventBus
from config import settings
from game.engine import GameEngine
from realtime.real_time_arbiter import RealTimeArbiter
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion
from rules.rule_engine import RuleEngine
from rules.rule_registry import build_default_registry
from server.db import AccountStore
from server.logging_config import configure_server_logging
from server.matchmaking import find_opponent
from server.protocol import (
    ProtocolError, encode_error, encode_login, encode_login_rejected, encode_no_match, parse_command,
)
from server.room import Room

logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765
DEFAULT_DB_PATH = str(Path(__file__).resolve().parent / "accounts.db")

# How often GameServer ticks every room's GameEngine.wait() and broadcasts,
# even with no incoming command - real-time motion (a move landing, a rest
# cooldown expiring) has to reach clients without waiting for someone to
# move. Also the resolution at which matchmaking timeouts are checked.
TICK_INTERVAL_SECONDS = 0.05

# How long a PLAY request waits for a compatible opponent before the
# player gets "No opponent found" instead.
MATCHMAKING_TIMEOUT_SECONDS = 60

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
    """`events` is optional and otherwise unused by this function itself -
    passing one in is how a caller (see GameServer._new_room) gets to hear
    GameEngine's own events (e.g. "game_over", which Room subscribes to
    for rating updates) instead of GameEngine creating and keeping its own
    private bus, which nothing outside it could ever observe."""
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


class GameServer:
    """The lobby. Owns no GameEngine itself - every game lives on its own
    server.room.Room (see server/room.py), created here and never
    afterwards touched directly; this class only decides *which* room (if
    any) a connection belongs to and routes accordingly.

    Collaborators:
      - `accounts` (server.db.AccountStore): LOGIN's username/password is
        checked here, and ratings are read/written by each Room. Defaults
        to an in-memory store so a GameServer is usable standalone (e.g.
        in tests) without a real database file.
      - server.matchmaking.find_opponent (pure logic): LOGIN only
        authenticates - it does NOT put anyone in a room. PLAY joins the
        matchmaking queue and creates a fresh Room, seating both sides,
        once matched against another PLAY-ing connection within rating
        range - or times out after MATCHMAKING_TIMEOUT_SECONDS with
        "no_match". ROOM CREATE/JOIN reach a Room the same way (see
        _new_room/seat_or_view) without going through the queue at all.

    `board_lines`/`config` describe the board every new Room's GameEngine
    starts from - the same for every room today (no per-room board choice
    yet).
    """

    def __init__(self, config=settings, accounts=None, board_lines=None):
        self._config = config
        self._board_lines = board_lines or STANDARD_BOARD_TEXT
        self._colors = tuple(config.COLORS)
        self._accounts = accounts if accounts is not None else AccountStore()
        self._clients = set()
        self._players = {}  # connection -> {"username", "rating"} (authenticated, connected)
        self._queue = {}  # connection -> {"username", "rating", "queued_at"} (searching)
        self._rooms = {}  # room_id -> Room
        self._connection_room = {}  # connection -> room_id
        self._last_tick = time.monotonic()

    async def handle_connection(self, connection):
        """The per-connection coroutine websockets.serve runs for as long
        as that connection is open. Unlike the pre-rooms server, nothing
        is sent immediately on connect - there's no default game to show
        until LOGIN, then PLAY/ROOM CREATE/ROOM JOIN, actually put this
        connection in a room (see Room.welcome, which sends the first
        snapshot once that happens)."""
        self._clients.add(connection)
        try:
            async for raw in connection:
                await self._handle_message(connection, raw)
        finally:
            self._clients.discard(connection)
            self._queue.pop(connection, None)
            self._players.pop(connection, None)
            room_id = self._connection_room.pop(connection, None)
            if room_id is not None:
                room = self._rooms.get(room_id)
                if room is not None:
                    await room.handle_disconnect(connection)

    async def tick(self):
        """Ticks every active room's GameEngine clock and resolves
        matchmaking timeouts - on a fixed interval independent of any
        client command (see serve_forever), so time-driven state reaches
        clients as it happens."""
        now = time.monotonic()
        for room in list(self._rooms.values()):
            await room.tick(now)
        await self._resolve_matchmaking_timeouts(now)

    async def _handle_message(self, connection, raw):
        try:
            command = parse_command(raw)
        except ProtocolError as error:
            await self._safe_send(connection, json.dumps(encode_error(str(error))))
            return

        if command.verb == "LOGIN":
            await self._handle_login(connection, command.args[0], command.args[1])
            return
        if command.verb == "PLAY":
            await self._handle_play(connection)
            return
        if command.verb == "ROOM_CREATE":
            await self._handle_room_create(connection)
            return
        if command.verb == "ROOM_JOIN":
            await self._handle_room_join(connection, command.args[0])
            return

        # MOVE / JUMP - the only verbs left; route to this connection's
        # current room, if it has one.
        room_id = self._connection_room.get(connection)
        if room_id is None:
            await self._safe_send(connection, json.dumps(encode_error("Not in a room")))
            return
        await self._rooms[room_id].handle_command(connection, command)

    # -- LOGIN: authentication only, no room -------------------------------

    async def _handle_login(self, connection, username, password):
        if connection in self._players:
            # Re-login from an already-authenticated connection just
            # confirms the same identity again.
            await self._safe_send(connection, json.dumps(encode_login(username, self._players[connection]["rating"])))
            return

        ok, rating, error = self._accounts.authenticate(username, password)
        if not ok:
            logger.warning("login failed for %r", username)
            await self._safe_send(connection, json.dumps(encode_login_rejected(error)))
            return

        self._players[connection] = {"username": username, "rating": rating}
        logger.info("%s logged in (rating=%s)", username, rating)
        await self._safe_send(connection, json.dumps(encode_login(username, rating)))

    # -- PLAY / matchmaking -------------------------------------------------

    async def _handle_play(self, connection):
        player = self._players.get(connection)
        if player is None:
            await self._safe_send(connection, json.dumps(encode_error("Must LOGIN before PLAY")))
            return
        if connection in self._connection_room or connection in self._queue:
            return  # already in a room or already searching - PLAY is a no-op

        waiting = [(conn, info["rating"]) for conn, info in self._queue.items()]
        opponent_connection = find_opponent(player["rating"], waiting)
        if opponent_connection is None:
            self._queue[connection] = {
                "username": player["username"], "rating": player["rating"], "queued_at": time.monotonic(),
            }
            return

        opponent = self._queue.pop(opponent_connection)
        room = self._new_room()
        role_mine = room.seat_or_view(connection, player["username"], player["rating"])
        role_theirs = room.seat_or_view(opponent_connection, opponent["username"], opponent["rating"])
        self._connection_room[connection] = room.room_id
        self._connection_room[opponent_connection] = room.room_id
        logger.info("matched %s vs %s in room %s", player["username"], opponent["username"], room.room_id)
        await room.welcome(connection, role_mine)
        await room.welcome(opponent_connection, role_theirs)

    async def _resolve_matchmaking_timeouts(self, now):
        for connection, info in list(self._queue.items()):
            if now - info["queued_at"] >= MATCHMAKING_TIMEOUT_SECONDS:
                del self._queue[connection]
                logger.info("%s's matchmaking search timed out", info["username"])
                await self._safe_send(connection, json.dumps(encode_no_match()))

    # -- ROOM CREATE / JOIN --------------------------------------------------

    async def _handle_room_create(self, connection):
        player = self._players.get(connection)
        if player is None:
            await self._safe_send(connection, json.dumps(encode_error("Must LOGIN before ROOM CREATE")))
            return

        room = self._new_room()
        role = room.seat_or_view(connection, player["username"], player["rating"])
        self._connection_room[connection] = room.room_id
        logger.info("%s created room %s", player["username"], room.room_id)
        await room.welcome(connection, role)

    async def _handle_room_join(self, connection, room_id):
        player = self._players.get(connection)
        if player is None:
            await self._safe_send(connection, json.dumps(encode_error("Must LOGIN before ROOM JOIN")))
            return

        room = self._rooms.get(room_id)
        if room is None:
            await self._safe_send(connection, json.dumps(encode_error(f"Room {room_id!r} not found")))
            return

        was_started = room.started
        role = room.seat_or_view(connection, player["username"], player["rating"])
        self._connection_room[connection] = room.room_id
        logger.info("%s joined room %s as %s", player["username"], room.room_id, role)
        await room.welcome(connection, role)
        if room.started and not was_started:
            await room.notify_room_started(exclude=connection)

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

    async def _safe_send(self, connection, message):
        # A client can disconnect between being read from self._clients and
        # actually being sent to (e.g. mid-broadcast) - that's not this
        # server's problem to raise about; handle_connection's own loop
        # ending is what removes it from self._clients.
        try:
            await connection.send(message)
        except websockets.exceptions.ConnectionClosed:
            pass


async def serve_forever(host=DEFAULT_HOST, port=DEFAULT_PORT, on_ready=None, accounts=None, config=settings,
                         board_lines=None):
    """Runs the lobby until cancelled. `on_ready(bound_server, game_server)`
    is called once the socket is actually listening - mainly so tests can
    ask for an OS-assigned port (port=0) and learn what it became; not
    otherwise needed to run the server for real."""
    game_server = GameServer(config=config, accounts=accounts, board_lines=board_lines)
    async with websockets.serve(game_server.handle_connection, host, port) as bound_server:
        if on_ready is not None:
            on_ready(bound_server, game_server)
        while True:
            await asyncio.sleep(TICK_INTERVAL_SECONDS)
            await game_server.tick()


def main():  # pragma: no cover
    configure_server_logging()
    accounts = AccountStore(DEFAULT_DB_PATH)
    logger.info("starting KungFu Chess server on %s:%s", DEFAULT_HOST, DEFAULT_PORT)
    asyncio.run(serve_forever(accounts=accounts))


if __name__ == "__main__":  # pragma: no cover
    main()
