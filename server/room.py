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

import websockets.exceptions

from board.piece import color_of
from server.elo import update_ratings
from server.protocol import (
    ProtocolError, encode_error, encode_opponent_disconnected, encode_opponent_reconnected, encode_rejected,
    encode_room, encode_room_started, encode_snapshot, encode_waiting_for_opponent, resolve_cells,
)

logger = logging.getLogger(__name__)

# How long a seated player has to reconnect (re-LOGIN, then rejoin this
# room with the same username) after dropping connection before they're
# auto-resigned.
DISCONNECT_GRACE_SECONDS = 20


class Room:
    def __init__(self, room_id, engine, colors, accounts):
        self.room_id = room_id
        self._engine = engine
        self._board_height = engine.snapshot().height
        self._colors = tuple(colors)
        self._accounts = accounts
        self._viewers = set()  # connections watching, never seated
        self._seats = {}  # connection -> color (currently connected AND seated)
        # color -> {"username", "rating"} - populated once seated and kept
        # for the life of the room (even across a disconnect); both the
        # Elo update on game_over and a reconnect's reclaim check need it
        # after the original connection is long gone.
        self._seat_info = {}
        self._disconnected = {}  # color -> monotonic deadline (grace period pending)
        # Latches True the first time both colors are ever seated - stays
        # True even through a later disconnect (that's handle_disconnect's
        # grace-period/auto-resign job, not this). Before that first time
        # (a freshly created room with only its creator seated), no move
        # is accepted - see handle_command.
        self._started = len(self._colors) < 2
        self._last_tick = time.monotonic()
        self._engine.events.subscribe("game_over", self._on_game_over)

    @property
    def started(self):
        return self._started

    def seat_or_view(self, connection, username, rating):
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
        return "viewer"

    def role_of(self, connection):
        if connection in self._seats:
            return self._seats[connection]
        if connection in self._viewers:
            return "viewer"
        return None

    def _reclaimable_color(self, username):
        for color in self._disconnected:
            if self._seat_info.get(color, {}).get("username") == username:
                return color
        return None

    def _next_open_color(self):
        for color in self._colors:
            if color not in self._seat_info:
                return color
        return None

    async def welcome(self, connection, role):
        """Sent once, right after seat_or_view, to that connection alone -
        confirms its room/role (see view.game_screen's persistent header),
        tells it to wait if it's the room's sole occupant so far (a fresh
        ROOM CREATE - never true for a PLAY match, which always seats both
        sides in the same seat_or_view pair), and gives it the room's
        current state immediately."""
        await self._safe_send(connection, json.dumps(encode_room(self.room_id, role)))
        if role != "viewer" and not self._started:
            await self._safe_send(connection, json.dumps(encode_waiting_for_opponent()))
        await self._safe_send(connection, json.dumps(encode_snapshot(self._engine)))

    async def notify_room_started(self, exclude):
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

    async def handle_command(self, connection, command):
        """MOVE/JUMP only - LOGIN/PLAY/ROOM are lobby-level, handled by
        GameServer before a command ever reaches a specific room. A
        viewer's attempt is rejected and logged - the client itself
        (GameScreen) already doesn't submit these for a viewer, so
        reaching here at all means something bypassed that (e.g. a raw
        handle_key-driven command)."""
        if connection not in self._seats:
            logger.warning("room %s: rejected %s from a non-seated connection", self.room_id, command.verb)
            await self._safe_send(connection, json.dumps(encode_error("Only seated players can make moves")))
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
            result = self._engine.request_move(cells[0], cells[1])
        else:  # JUMP - the only other verb protocol.parse_command accepts here
            result = self._engine.request_jump(cells[0])

        if not result.is_accepted:
            logger.info("room %s: %s by %s rejected (%s)", self.room_id, command.verb, self._seats[connection], result.reason)
            await self._safe_send(connection, json.dumps(encode_rejected(result.reason)))
            return

        logger.info("room %s: %s by %s accepted", self.room_id, command.verb, self._seats[connection])
        await self.broadcast()

    async def handle_disconnect(self, connection):
        self._viewers.discard(connection)
        color = self._seats.pop(connection, None)
        if color is None or self._engine.game_over:
            return
        self._disconnected[color] = time.monotonic() + DISCONNECT_GRACE_SECONDS
        username = self._seat_info.get(color, {}).get("username")
        logger.info("room %s: %s (%s) disconnected - %ss to reconnect", self.room_id, username, color, DISCONNECT_GRACE_SECONDS)
        await self._notify_all(encode_opponent_disconnected(color, DISCONNECT_GRACE_SECONDS))

    async def tick(self, now):
        dt_ms = int((now - self._last_tick) * 1000)
        self._last_tick = now
        self._engine.wait(dt_ms)
        await self._resolve_disconnect_timeouts(now)
        await self.broadcast()

    async def _resolve_disconnect_timeouts(self, now):
        for color, deadline in list(self._disconnected.items()):
            if now >= deadline:
                del self._disconnected[color]
                logger.info("room %s: %s auto-resigning (no reconnect)", self.room_id, color)
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
        logger.info(
            "room %s: game over, winner=%s (%s -> %s, %s -> %s)",
            self.room_id, payload.get("winner"), info_a["username"], new_a, info_b["username"], new_b,
        )

    async def broadcast(self):
        connections = set(self._seats) | self._viewers
        if not connections:
            return
        message = json.dumps(encode_snapshot(self._engine))
        await asyncio.gather(*(self._safe_send(c, message) for c in connections))

    async def _notify_all(self, message_dict):
        connections = set(self._seats) | self._viewers
        if not connections:
            return
        message = json.dumps(message_dict)
        await asyncio.gather(*(self._safe_send(c, message) for c in connections))

    async def _safe_send(self, connection, message):
        # A client can disconnect between being read and actually being
        # sent to - that's not this room's problem to raise about;
        # handle_disconnect is what removes it from _seats/_viewers.
        try:
            await connection.send(message)
        except websockets.exceptions.ConnectionClosed:
            pass
