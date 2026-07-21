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
from server.matchmaking import find_opponent
from server.protocol import (
    ProtocolError, encode_error, encode_login, encode_login_rejected, encode_matched, encode_no_match,
    encode_opponent_disconnected, encode_opponent_reconnected, encode_rejected, encode_snapshot,
    parse_command, resolve_cells,
)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765
DEFAULT_DB_PATH = str(Path(__file__).resolve().parent / "accounts.db")

# How often the server ticks GameEngine.wait() and broadcasts, even with no
# incoming command - real-time motion (a move landing, a rest cooldown
# expiring) has to reach clients without waiting for someone to move. Also
# the resolution at which matchmaking/disconnect timeouts are checked.
TICK_INTERVAL_SECONDS = 0.05

# How long a PLAY request waits for a compatible opponent before the
# player gets "No opponent found" instead.
MATCHMAKING_TIMEOUT_SECONDS = 60

# How long a seated player has to reconnect (re-LOGIN with the same
# username) after dropping connection before they're auto-resigned.
DISCONNECT_GRACE_SECONDS = 20

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
    """Owns one GameEngine and every currently-connected client. Not itself
    aware of websockets.serve's lifecycle (see serve_forever) - so it's
    testable by driving handle_connection/tick directly, without a real
    socket.

    Collaborators:
      - `accounts` (server.db.AccountStore): LOGIN's username/password is
        checked here, and ratings are read/written here. Defaults to an
        in-memory store so a GameServer is usable standalone (e.g. in
        tests) without a real database file.
      - `events` should be the same EventBus `engine` itself publishes on
        (see build_engine) - if given, this server listens for "game_over"
        to update both seated players' Elo ratings (server.elo) once a
        game actually ends; if omitted, ratings are simply never updated
        (a valid, tested configuration for tests that don't care).
      - server.matchmaking.find_opponent (pure logic): LOGIN only
        authenticates - it does NOT seat a color. PLAY joins the
        matchmaking queue and only seats a color once matched against
        another PLAY-ing connection within rating range, or times out
        after MATCHMAKING_TIMEOUT_SECONDS with "no_match".

    Only `len(config.COLORS)` colors can be seated at a time (2 for the
    default w/b config). A seated player's disconnect doesn't free their
    color outright - it starts a DISCONNECT_GRACE_SECONDS window (see
    _resolve_disconnect_timeouts) during which the same username can
    reclaim it by logging back in (even from a brand new connection);
    letting the window lapse auto-resigns them via GameEngine.resign.
    There's no restriction yet tying a MOVE/JUMP to the color that's
    actually seated for it.
    """

    def __init__(self, engine, config=settings, accounts=None, events=None):
        self._engine = engine
        self._board_height = engine.snapshot().height
        self._colors = tuple(config.COLORS)
        self._accounts = accounts if accounts is not None else AccountStore()
        self._clients = set()
        self._players = {}  # connection -> {"username", "rating"} (authenticated, connected)
        self._queue = {}  # connection -> {"username", "rating", "queued_at"} (searching)
        self._seats = {}  # connection -> color (currently connected AND seated)
        # color -> {"username", "rating"}, populated once matched and kept
        # for the lifetime of this game (even across a disconnect) - both
        # rating updates on game_over and a reconnect's reclaim check need
        # it after the original connection (and its self._players entry)
        # is already gone.
        self._seat_info = {}
        self._disconnected = {}  # color -> monotonic deadline (grace period pending)
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
            self._queue.pop(connection, None)
            self._players.pop(connection, None)
            color = self._seats.pop(connection, None)
            if color is not None and not self._engine.game_over:
                await self._start_disconnect_countdown(color)

    async def tick(self):
        """Advances the engine's clock by real elapsed wall-clock time,
        resolves any matchmaking/disconnect timeouts, and broadcasts - all
        on a fixed interval independent of any client command (see
        serve_forever), so time-driven state (in-flight motion, a search
        that's been waiting too long, a dropped opponent's grace period)
        reaches clients as it happens."""
        now = time.monotonic()
        dt_ms = int((now - self._last_tick) * 1000)
        self._last_tick = now
        self._engine.wait(dt_ms)
        self._resolve_disconnect_timeouts(now)
        await self._resolve_matchmaking_timeouts(now)
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
        if command.verb == "PLAY":
            await self._handle_play(connection)
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

    # -- LOGIN: authentication only, plus reclaiming a disconnected seat --

    async def _handle_login(self, connection, username, password):
        if connection in self._players:
            # Re-login from an already-authenticated connection just
            # confirms the same identity again.
            await self._safe_send(connection, json.dumps(encode_login(username, self._players[connection]["rating"])))
            return

        ok, rating, error = self._accounts.authenticate(username, password)
        if not ok:
            await self._safe_send(connection, json.dumps(encode_login_rejected(error)))
            return

        self._players[connection] = {"username": username, "rating": rating}
        await self._safe_send(connection, json.dumps(encode_login(username, rating)))

        reclaimed_color = self._reclaimable_color(username)
        if reclaimed_color is not None:
            del self._disconnected[reclaimed_color]
            self._seats[connection] = reclaimed_color
            self._seat_info[reclaimed_color] = {"username": username, "rating": rating}
            await self._notify_all(encode_opponent_reconnected(reclaimed_color))

    def _reclaimable_color(self, username):
        for color in self._disconnected:
            if self._seat_info.get(color, {}).get("username") == username:
                return color
        return None

    # -- PLAY / matchmaking -------------------------------------------------

    async def _handle_play(self, connection):
        player = self._players.get(connection)
        if player is None:
            await self._safe_send(connection, json.dumps(encode_error("Must LOGIN before PLAY")))
            return
        if connection in self._seats or connection in self._queue:
            return  # already seated or already searching - PLAY is a no-op

        waiting = [(conn, info["rating"]) for conn, info in self._queue.items()]
        opponent_connection = find_opponent(player["rating"], waiting)
        if opponent_connection is None:
            self._queue[connection] = {
                "username": player["username"], "rating": player["rating"], "queued_at": time.monotonic(),
            }
            return

        opponent = self._queue.pop(opponent_connection)
        color_mine, color_theirs = self._colors[0], self._colors[1]
        self._seats[connection] = color_mine
        self._seats[opponent_connection] = color_theirs
        self._seat_info[color_mine] = {"username": player["username"], "rating": player["rating"]}
        self._seat_info[color_theirs] = {"username": opponent["username"], "rating": opponent["rating"]}
        await self._safe_send(connection, json.dumps(encode_matched(color_mine)))
        await self._safe_send(opponent_connection, json.dumps(encode_matched(color_theirs)))
        await self.broadcast()  # both should see the board immediately, not wait for the next tick

    async def _resolve_matchmaking_timeouts(self, now):
        for connection, info in list(self._queue.items()):
            if now - info["queued_at"] >= MATCHMAKING_TIMEOUT_SECONDS:
                del self._queue[connection]
                await self._safe_send(connection, json.dumps(encode_no_match()))

    # -- Disconnect grace period / auto-resign ------------------------------

    async def _start_disconnect_countdown(self, color):
        self._disconnected[color] = time.monotonic() + DISCONNECT_GRACE_SECONDS
        await self._notify_all(encode_opponent_disconnected(color, DISCONNECT_GRACE_SECONDS))

    def _resolve_disconnect_timeouts(self, now):
        for color, deadline in list(self._disconnected.items()):
            if now >= deadline:
                del self._disconnected[color]
                self._engine.resign(color)  # publishes "resign" then "game_over" - see _on_game_over

    def _on_game_over(self, payload):
        """Updates both seated players' Elo ratings once GameEngine reports
        the game ended - a plain (synchronous) EventBus subscriber, not a
        coroutine, since EventBus.publish calls its handlers directly (this
        runs synchronously even when triggered from inside
        _resolve_disconnect_timeouts's own call to engine.resign).
        A no-op if either color's info isn't known (nothing to rate) or
        config.COLORS isn't exactly the two-player case Elo assumes.
        """
        if len(self._colors) != 2:
            return
        info_a = self._seat_info.get(self._colors[0])
        info_b = self._seat_info.get(self._colors[1])
        if info_a is None or info_b is None:
            return

        score_a = 1.0 if payload.get("winner") == self._colors[0] else 0.0
        new_a, new_b = update_ratings(info_a["rating"], info_b["rating"], score_a)
        info_a["rating"], info_b["rating"] = new_a, new_b
        self._accounts.update_rating(info_a["username"], new_a)
        self._accounts.update_rating(info_b["username"], new_b)

    async def _notify_all(self, message_dict):
        if not self._clients:
            return
        message = json.dumps(message_dict)
        await asyncio.gather(*(self._safe_send(c, message) for c in list(self._clients)))

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
