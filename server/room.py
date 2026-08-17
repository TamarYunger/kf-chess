"""server/room.py: one game - a GameEngine, its seated players ("white"/
"black", whichever two colors config.COLORS names) and anyone else
connected to it as a viewer.

This is the exact seat/disconnect-grace-period/Elo-update mechanism a
single, server-wide GameServer used to own directly, before rooms
existed - lifted out and parametrized by room_id so GameServer can host
many of these concurrently. It is deliberately the *only* place that
mechanism lives: a room created by ROOM CREATE and a game found through
PLAY's matchmaking (server/ws_server.py) both end up as a Room, seated via
the same seat_or_view() - not two different seat-tracking structures for
"a matched game" vs "a room".
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Callable

from board.piece import color_of
from bus.event_types import ARRIVAL, GAME_OVER, RESIGN, VIEWER
from server.elo import update_ratings
from server.protocol import (
    Command, ProtocolError, encode_arrival, encode_error, encode_game_over, encode_legal_destinations,
    encode_opponent_disconnected, encode_opponent_reconnected, encode_rejected, encode_resign,
    encode_room, encode_room_started, encode_snapshot, encode_waiting_for_opponent, resolve_cells,
)
from server.safe_send import Connection, safe_send

if TYPE_CHECKING:
    from game.engine import GameEngine
    from server.db import AccountStore

logger = logging.getLogger(__name__)

# How long a seated player has to reconnect (re-LOGIN, then rejoin this
# room with the same username) after dropping connection before they're
# auto-resigned.
DISCONNECT_GRACE_SECONDS = 20


class Room:
    def __init__(self, room_id: str, engine: GameEngine, colors: tuple[str, ...], accounts: AccountStore) -> None:
        self.room_id = room_id
        self._engine = engine
        self._board_height = engine.snapshot().height
        self._colors = tuple(colors)
        self._accounts = accounts
        self._viewers: set[Connection] = set()  # connections watching, never seated
        self._seats: dict[Connection, str] = {}  # connection -> color (currently connected AND seated)
        # color -> {"username", "rating"} - populated once seated and kept
        # for the life of the room (even across a disconnect); both the
        # Elo update on game_over and a reconnect's reclaim check need it
        # after the original connection is long gone.
        self._seat_info: dict[str, dict] = {}
        self._disconnected: dict[str, float] = {}  # color -> monotonic deadline (grace period pending)
        # Latches True the first time both colors are ever seated - stays
        # True even through a later disconnect (that's handle_disconnect's
        # grace-period/auto-resign job, not this). Before that first time
        # (a freshly created room with only its creator seated), no move
        # is accepted - see handle_command.
        self._started = len(self._colors) < 2
        self._last_tick = time.monotonic()
        # GameEngine's own events fire synchronously, mid-call, from deep
        # inside whichever engine method is running (see resolve()'s
        # docstring: several engine methods settle anything already due
        # before doing their own work) - too early to `await` a network
        # send from. These subscribers only ever queue a message;
        # _call_engine is what actually flushes the queue, right after the
        # engine call that might have triggered it returns. handle_command
        # and tick also flush once more before returning, as a backstop -
        # but every engine call that can settle a motion should go through
        # _call_engine so a future addition can't forget to flush on its
        # own (see _call_engine's docstring).
        self._pending_events: list[dict] = []
        self._engine.events.subscribe(GAME_OVER, self._on_game_over)
        self._engine.events.subscribe(GAME_OVER, self._on_game_over_for_clients)
        self._engine.events.subscribe(ARRIVAL, self._on_arrival)
        # Fires (only for an auto-resign - see _resolve_disconnect_timeouts)
        # right before the "game_over" above, so a client sees this queued
        # message first - resign() itself publishes "resign" then
        # "game_over" in that order (see GameEngine.resign's docstring).
        self._engine.events.subscribe(RESIGN, self._on_resign_for_clients)

    @property
    def started(self) -> bool:
        return self._started

    def seat_or_view(self, connection: Connection, username: str, rating: int) -> str:
        """The single way any connection becomes part of this room -
        reused for a room's creator, a joiner, a reconnect within the
        disconnect grace period, and a matched PLAY pair (see
        server/ws_server.py - all four call this, none of them touch
        self._seats directly). Returns the seated color, or "viewer" once
        both colors are already taken by someone else.
        """
        reclaimed = self._reclaimable_color(username)
        if reclaimed is not None:
            del self._disconnected[reclaimed]
            self._seats[connection] = reclaimed
            self._seat_info[reclaimed] = {"username": username, "rating": rating}
            logger.info("room %s: %s reconnected as %s", self.room_id, username, reclaimed)
            return reclaimed

        color = self._next_open_color()
        if color is not None:
            self._seats[connection] = color
            self._seat_info[color] = {"username": username, "rating": rating}
            logger.info("room %s: %s seated as %s", self.room_id, username, color)
            if not self._started and len(self._seat_info) == len(self._colors):
                self._started = True
            return color

        self._viewers.add(connection)
        logger.info("room %s: %s joined as a viewer", self.room_id, username)
        return VIEWER

    def is_reclaimable(self, username: str) -> bool:
        """True if `username` has a disconnect grace period pending on some
        color right now - checked by GameServer *before* calling
        seat_or_view, so it knows afterwards whether that call just resolved
        a reconnect (and the opponent needs an opponent_reconnected notice)
        or seated/viewed someone fresh."""
        return self._reclaimable_color(username) is not None

    def _reclaimable_color(self, username: str) -> str | None:
        for color in self._disconnected:
            if self._seat_info.get(color, {}).get("username") == username:
                return color
        return None

    def _next_open_color(self) -> str | None:
        for color in self._colors:
            if color not in self._seat_info:
                return color
        return None

    async def welcome(self, connection: Connection, role: str) -> None:
        """Sent once, right after seat_or_view, to that connection alone -
        confirms its room/role (see view.game_screen's persistent header),
        tells it to wait if it's the room's sole occupant so far (a fresh
        ROOM CREATE - never true for a PLAY match, which always seats both
        sides in the same seat_or_view pair), and gives it the room's
        current state immediately."""
        await self._safe_send(connection, json.dumps(encode_room(self.room_id, role)))
        if role != VIEWER and not self._started:
            await self._safe_send(connection, json.dumps(encode_waiting_for_opponent()))
        await self._safe_send(connection, json.dumps(encode_snapshot(self._engine)))

    async def notify_reconnected(self, color: str) -> None:
        """Called by GameServer right after a seat_or_view() call that just
        reclaimed a disconnected seat (is_reclaimable was True beforehand) -
        tells everyone else in the room that color's disconnect countdown is
        off; the reconnecting connection's own welcome() already covers
        everything it needs, so this excludes no one but also isn't sent to
        it specifically - a stale opponent_reconnected for its own color is
        harmless and simpler than threading an exclude through here too."""
        logger.info("room %s: %s reconnected, notifying room", self.room_id, color)
        await self._notify_all(encode_opponent_reconnected(color))

    async def notify_room_started(self, exclude: Connection) -> None:
        """Called by GameServer right after a seat_or_view() call that just
        flipped `started` True for the first time (a ROOM JOIN completing
        a room a creator has been waiting alone in) - clears that waiting
        state on whoever else is already in the room. `exclude` is the
        connection that just joined - their own welcome() already covers
        everything they need to know, without this extra message too."""
        connections = (set(self._seats) | self._viewers) - {exclude}
        if not connections:
            return
        message = json.dumps(encode_room_started())
        await asyncio.gather(*(self._safe_send(c, message) for c in connections))

    async def handle_command(self, connection: Connection, command: Command) -> None:
        """MOVE/JUMP/SELECT only - LOGIN/PLAY/ROOM are lobby-level, handled
        by GameServer before a command ever reaches a specific room. A
        viewer's attempt is rejected and logged - the client itself
        (GameScreen) already doesn't submit these for a viewer, so
        reaching here at all means something bypassed that (e.g. a raw
        handle_key-driven command).

        Wrapped so every exit path - accepted, rejected, malformed, not
        this connection's turn to speak at all - still flushes whatever
        _on_arrival/_on_game_over_for_clients queued: SELECT/MOVE/JUMP all
        end up calling an engine method that settles anything already due
        first (see GameEngine.legal_destinations/request_move/request_jump
        each calling resolve() before their own work), so an unrelated
        earlier move can land - and need forwarding - even on a command
        that itself gets rejected.
        """
        try:
            await self._handle_command(connection, command)
        finally:
            await self._flush_pending_events()

    async def _handle_command(self, connection: Connection, command: Command) -> None:
        if connection not in self._seats:
            logger.warning("room %s: rejected %s from a non-seated connection", self.room_id, command.verb)
            await self._safe_send(connection, json.dumps(encode_error("Only seated players can make moves")))
            return

        if command.verb == "SELECT":
            # Read-only: answered even before both seats are filled, and
            # never rejected/logged as a game action - see _handle_select.
            try:
                cell = resolve_cells(command, self._board_height)[0]
            except ProtocolError as error:
                await self._safe_send(connection, json.dumps(encode_error(str(error))))
                return
            await self._handle_select(connection, cell)
            return

        if not self._started:
            logger.info("room %s: %s rejected (waiting_for_opponent)", self.room_id, command.verb)
            await self._safe_send(connection, json.dumps(encode_rejected("waiting_for_opponent")))
            return

        try:
            cells = resolve_cells(command, self._board_height)
        except ProtocolError as error:
            await self._safe_send(connection, json.dumps(encode_error(str(error))))
            return

        # A seated player may only move their own color - GameEngine itself
        # has no notion of turns or ownership (see its own docstring: "no
        # turns, so the two lists advance independently" - by design, for
        # LocalGameSession's offline hotseat play, both colors are one
        # person). Over the network that has to be enforced here, per
        # connection, the same way viewer-vs-seated already is above:
        # empty-source is left to GameEngine's own EMPTY_SOURCE rejection,
        # not duplicated here.
        source_row, source_col = cells[0]
        source_piece = self._engine.snapshot().cells[source_row][source_col]
        if source_piece != "." and color_of(source_piece) != self._seats[connection]:
            logger.info(
                "room %s: %s by %s rejected (not_your_piece)", self.room_id, command.verb, self._seats[connection],
            )
            await self._safe_send(connection, json.dumps(encode_rejected("not_your_piece")))
            return

        if command.verb == "MOVE":
            result = await self._call_engine(self._engine.request_move, cells[0], cells[1])
        else:  # JUMP - the only other verb protocol.parse_command accepts here
            result = await self._call_engine(self._engine.request_jump, cells[0])

        if not result.is_accepted:
            logger.info("room %s: %s by %s rejected (%s)", self.room_id, command.verb, self._seats[connection], result.reason)
            await self._safe_send(connection, json.dumps(encode_rejected(result.reason)))
            return

        logger.info("room %s: %s by %s accepted", self.room_id, command.verb, self._seats[connection])
        await self.broadcast()

    async def _handle_select(self, connection: Connection, cell: tuple[int, int]) -> None:
        """A client's first click on a piece, asking what its legal
        destinations are right now (for the highlight NetworkGameSession
        shows before its second click sends an actual MOVE) - answered with
        GameEngine.legal_destinations, the exact same read the engine
        itself relies on, so a highlighted square is never one MOVE would
        then refuse. Empty for a cell that isn't the requester's own piece
        (mirrors handle_command's own not_your_piece guard above, just
        without the rejection message - this isn't a move attempt)."""
        row, col = cell
        piece = self._engine.snapshot().cells[row][col]
        if piece != "." and color_of(piece) == self._seats[connection]:
            destinations = await self._call_engine(self._engine.legal_destinations, cell)
        else:
            destinations = frozenset()
        await self._safe_send(connection, json.dumps(encode_legal_destinations(cell, destinations)))

    async def handle_disconnect(self, connection: Connection) -> None:
        self._viewers.discard(connection)
        color = self._seats.pop(connection, None)
        if color is None or self._engine.game_over:
            return
        self._disconnected[color] = time.monotonic() + DISCONNECT_GRACE_SECONDS
        username = self._seat_info.get(color, {}).get("username")
        logger.info("room %s: %s (%s) disconnected - %ss to reconnect", self.room_id, username, color, DISCONNECT_GRACE_SECONDS)
        await self._notify_all(encode_opponent_disconnected(color, DISCONNECT_GRACE_SECONDS))

    async def tick(self, now: float) -> None:
        dt_ms = int((now - self._last_tick) * 1000)
        self._last_tick = now
        await self._call_engine(self._engine.wait, dt_ms)
        await self._resolve_disconnect_timeouts(now)
        await self._flush_pending_events()
        await self.broadcast()

    async def _resolve_disconnect_timeouts(self, now: float) -> None:
        for color, deadline in list(self._disconnected.items()):
            if now >= deadline:
                del self._disconnected[color]
                logger.info("room %s: %s auto-resigning (no reconnect)", self.room_id, color)
                # publishes "resign" then "game_over" - see _on_game_over
                await self._call_engine(self._engine.resign, color)

    def _on_game_over(self, payload: dict) -> None:
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
        logger.info(
            "room %s: game over, winner=%s (%s -> %s, %s -> %s)",
            self.room_id, payload.get("winner"), info_a["username"], new_a, info_b["username"], new_b,
        )

    def _on_arrival(self, event: object) -> None:
        self._pending_events.append(encode_arrival(event))

    def _on_game_over_for_clients(self, payload: dict) -> None:
        self._pending_events.append(encode_game_over(payload.get("winner")))

    def _on_resign_for_clients(self, payload: dict) -> None:
        self._pending_events.append(encode_resign(payload["color"]))

    async def _call_engine(self, method: Callable, *args: object) -> object:
        """Call an engine method that may settle a pending motion (i.e.
        anything but a plain read like `snapshot()`) and immediately flush
        whatever that triggered - so flushing lives right next to the call
        that can need it, instead of depending on whichever caller further
        up remembers to do it separately. Every new Room method that needs
        to invoke a mutating GameEngine method should go through here
        (`await self._call_engine(self._engine.some_method, ...)`) rather
        than calling `self._engine.some_method(...)` directly."""
        result = method(*args)
        await self._flush_pending_events()
        return result

    async def _flush_pending_events(self) -> None:
        pending, self._pending_events = self._pending_events, []
        for message in pending:
            await self._notify_all(message)

    async def broadcast(self) -> None:
        await self._notify_all(encode_snapshot(self._engine))

    async def _notify_all(self, message_dict: dict) -> None:
        connections = set(self._seats) | self._viewers
        if not connections:
            return
        message = json.dumps(message_dict)
        await asyncio.gather(*(self._safe_send(c, message) for c in connections))

    async def _safe_send(self, connection: Connection, message: str) -> None:
        # A client can disconnect between being read and actually being
        # sent to - that's not this room's problem to raise about;
        # handle_disconnect is what removes it from _seats/_viewers.
        await safe_send(connection, message)
