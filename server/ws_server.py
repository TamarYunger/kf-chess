"""A WebSocket server wrapping a single GameEngine, broadcasting its state
to every connected client - players and, in the future, spectators; no
distinction between the two is made yet - and applying whatever text
commands they send (see server/protocol.py for the wire format).

This is the third place in the codebase that wires up a GameEngine, next
to main.py's run() (the batch/script CLI) and view/local_game_session.py
(the offline GUI path) - each is its own composition root for its own
entry point, so a small amount of duplicated wiring here is expected
rather than a shortcut worth removing.
"""
from __future__ import annotations

import asyncio
import json
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
from server.elo import update_ratings
from server.protocol import (
    ProtocolError, encode_error, encode_login, encode_login_rejected, encode_rejected, encode_snapshot,
    parse_command, resolve_cells,
)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765
DEFAULT_DB_PATH = str(Path(__file__).resolve().parent / "accounts.db")

# How often the server ticks GameEngine.wait() and broadcasts, even with no
# incoming command - real-time motion (a move landing, a rest cooldown
# expiring) has to reach clients without waiting for someone to move.
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
    """`events` is optional and otherwise unused by this function itself -
    passing one in is how a caller (see main()) gets to hear GameEngine's
    own events (e.g. "game_over", which GameServer subscribes to for
    rating updates) instead of GameEngine creating and keeping its own
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
    """Owns one GameEngine, every currently-connected client, and seat
    assignment. Not itself aware of websockets.serve's lifecycle (see
    serve_forever) - so it's testable by driving handle_connection/tick
    directly, without a real socket.

    Only `len(config.COLORS)` connections can be seated at a time (2 for
    the default w/b config) - the first to LOGIN gets colors[0], the next
    colors[1], and so on; anyone past that gets login_rejected instead. A
    connection's seat is freed when it disconnects, and LOGIN is otherwise
    open to any client at any time - there's no restriction yet tying a
    MOVE/JUMP to the color that's actually seated for it (see the open
    follow-up in server/protocol.py's module docstring).

    `accounts` (server.db.AccountStore) is where LOGIN's username/password
    is checked and where ratings are read/written - defaults to an
    in-memory store so a GameServer is usable standalone (e.g. in tests)
    without a real database file. `events` should be the same EventBus
    `engine` itself publishes on (see build_engine) - if given, this
    server listens for "game_over" to update both seated players' Elo
    ratings (server.elo) once a game actually ends; if omitted, ratings are
    simply never updated (fine for tests that don't care about that).
    """

    def __init__(self, engine, config=settings, accounts=None, events=None):
        self._engine = engine
        self._board_height = engine.snapshot().height
        self._colors = tuple(config.COLORS)
        self._accounts = accounts if accounts is not None else AccountStore()
        self._clients = set()
        self._seats = {}  # connection -> assigned color
        self._players = {}  # connection -> {"username": str, "rating": int}
        self._last_tick = time.monotonic()
        if events is not None:
            events.subscribe("game_over", self._on_game_over)

    async def handle_connection(self, connection):
        """The per-connection coroutine websockets.serve runs for as long
        as that connection is open - registers the client, sends it the
        current state immediately (so joining mid-game still shows the
        real board, not a blank one), then applies whatever commands it
        sends until it disconnects."""
        self._clients.add(connection)
        try:
            await connection.send(self._encode_snapshot_json())
            async for raw in connection:
                await self._handle_message(connection, raw)
        finally:
            self._clients.discard(connection)
            self._seats.pop(connection, None)
            self._players.pop(connection, None)

    async def tick(self):
        """Advances the engine's clock by real elapsed wall-clock time and
        broadcasts - called on a fixed interval independent of any client
        command (see serve_forever), so in-flight motion (arrivals, rest
        cooldowns finishing) reaches clients as it happens, not only when
        someone happens to send another move."""
        now = time.monotonic()
        dt_ms = int((now - self._last_tick) * 1000)
        self._last_tick = now
        self._engine.wait(dt_ms)
        await self.broadcast()

    async def broadcast(self):
        if not self._clients:
            return
        message = self._encode_snapshot_json()
        await asyncio.gather(*(self._safe_send(client, message) for client in list(self._clients)))

    async def _handle_message(self, connection, raw):
        try:
            command = parse_command(raw)
        except ProtocolError as error:
            await self._safe_send(connection, json.dumps(encode_error(str(error))))
            return

        if command.verb == "LOGIN":
            await self._handle_login(connection, command.args[0], command.args[1])
            return

        try:
            cells = resolve_cells(command, self._board_height)
        except ProtocolError as error:
            await self._safe_send(connection, json.dumps(encode_error(str(error))))
            return

        if command.verb == "MOVE":
            result = self._engine.request_move(cells[0], cells[1])
        else:  # JUMP - the only other verb protocol.parse_command accepts
            result = self._engine.request_jump(cells[0])

        if not result.is_accepted:
            await self._safe_send(connection, json.dumps(encode_rejected(result.reason)))
            return

        await self.broadcast()

    async def _handle_login(self, connection, username, password):
        # Re-login from a connection that already holds a seat just
        # confirms the same color again, rather than re-authenticating or
        # consuming a second seat for the same connection.
        color = self._seats.get(connection)
        if color is not None:
            await self._safe_send(connection, json.dumps(encode_login(color, username)))
            return

        ok, rating, error = self._accounts.authenticate(username, password)
        if not ok:
            await self._safe_send(connection, json.dumps(encode_login_rejected(error)))
            return

        if len(self._seats) >= len(self._colors):
            await self._safe_send(connection, json.dumps(encode_login_rejected("Room is full")))
            return

        color = self._colors[len(self._seats)]
        self._seats[connection] = color
        self._players[connection] = {"username": username, "rating": rating}
        await self._safe_send(connection, json.dumps(encode_login(color, username)))

    def _on_game_over(self, payload):
        """Updates both seated players' Elo ratings once GameEngine reports
        the game ended - a plain (synchronous) EventBus subscriber, not a
        coroutine, since EventBus.publish calls its handlers directly.
        A no-op if either seat was never actually logged in (nothing to
        rate) or config.COLORS isn't exactly the two-player case Elo
        assumes.
        """
        if len(self._colors) != 2:
            return
        player_a = self._player_for_color(self._colors[0])
        player_b = self._player_for_color(self._colors[1])
        if player_a is None or player_b is None:
            return

        score_a = 1.0 if payload.get("winner") == self._colors[0] else 0.0
        new_a, new_b = update_ratings(player_a["rating"], player_b["rating"], score_a)
        player_a["rating"], player_b["rating"] = new_a, new_b
        self._accounts.update_rating(player_a["username"], new_a)
        self._accounts.update_rating(player_b["username"], new_b)

    def _player_for_color(self, color):
        for connection, seat_color in self._seats.items():
            if seat_color == color:
                return self._players.get(connection)
        return None

    async def _safe_send(self, connection, message):
        # A client can disconnect between being read from self._clients and
        # actually being sent to (e.g. mid-broadcast) - that's not this
        # server's problem to raise about; handle_connection's own loop
        # ending is what removes it from self._clients.
        try:
            await connection.send(message)
        except websockets.exceptions.ConnectionClosed:
            pass

    def _encode_snapshot_json(self):
        return json.dumps(encode_snapshot(self._engine))


async def serve_forever(engine, host=DEFAULT_HOST, port=DEFAULT_PORT, on_ready=None, accounts=None, events=None):
    """Runs the server until cancelled. `on_ready(bound_server, game_server)`
    is called once the socket is actually listening - mainly so tests can
    ask for an OS-assigned port (port=0) and learn what it became; not
    otherwise needed to run the server for real. `accounts`/`events` are
    forwarded to GameServer as-is - see its own docstring."""
    game_server = GameServer(engine, accounts=accounts, events=events)
    async with websockets.serve(game_server.handle_connection, host, port) as bound_server:
        if on_ready is not None:
            on_ready(bound_server, game_server)
        while True:
            await asyncio.sleep(TICK_INTERVAL_SECONDS)
            await game_server.tick()


def main():  # pragma: no cover
    events = EventBus()
    engine = build_engine(STANDARD_BOARD_TEXT, settings, events=events)
    accounts = AccountStore(DEFAULT_DB_PATH)
    asyncio.run(serve_forever(engine, accounts=accounts, events=events))


if __name__ == "__main__":  # pragma: no cover
    main()
