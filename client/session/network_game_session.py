"""NetworkGameSession: a GameSession backed by a WebSocket connection to a
real server (see session/network_client.py). No GameEngine import here at
all - the server owns every rule; this session only forwards commands and
decodes whatever it's told.
"""
from __future__ import annotations

import dataclasses

from board.notation import square_name
from client.session.game_session import GameSession
from client.session.network_client import NetworkClient
from client.session.snapshot_codec import snapshot_from_json


class NetworkGameSession(GameSession):
    """`events` is the same EventBus the rest of the UI (ScreenManager's
    transitions, LoginScreen) shares - every incoming message is
    republished there by its own "type", not just "snapshot", so any
    screen can react to server messages this session doesn't otherwise
    know or care about.

    GameScreen sends the same cell-shaped commands regardless of session
    type ({"type": "click"/"jump", "cell": (row, col)}) - see
    GameSession's own docstring. server/protocol.py's wire format needs a
    MOVE command to carry both squares at once, though, so *this* session
    is what accumulates a first click into a pending selection and only
    sends "MOVE <start> <end>" once a second click arrives - mirroring
    exactly what game.controller.Controller does for LocalGameSession, just
    producing a server command instead of calling GameEngine directly.
    Plain string commands (e.g. LoginScreen's "LOGIN <username>") are
    forwarded to the server as-is - they need no such translation.
    """

    def __init__(self, url, events, network_client=None):
        self._events = events
        self._client = network_client if network_client is not None else NetworkClient(url)
        self._snapshot = None
        self._pending_start = None  # a cell selected by a first click, awaiting a second
        self._legal_destinations = frozenset()  # reply to that click's own SELECT, once it arrives
        self._rejection_reason = None
        self._latest_snapshot = None
        self._client.start()

    def submit_command(self, command):
        if isinstance(command, str):
            self._client.send(command)
            return
        if self._snapshot is None:
            return  # no board height known yet to turn a cell into a square
        cell = tuple(command["cell"])
        if command["type"] == "click":
            self._handle_click(cell)
        elif command["type"] == "jump":
            self._pending_start = None
            self._legal_destinations = frozenset()
            self._rejection_reason = None
            self._client.send(f"JUMP {self._square(cell)}")

    def _handle_click(self, cell):
        if self._pending_start is None:
            # A first click: matches Controller.click's own behaviour -
            # clears any stale rejection banner, this is a fresh attempt.
            # The highlight itself arrives asynchronously as a
            # "legal_destinations" reply (see tick()) - the server, not
            # this session, decides what's legal, same as an actual MOVE.
            self._rejection_reason = None
            self._pending_start = cell
            self._legal_destinations = frozenset()
            self._client.send(f"SELECT {self._square(cell)}")
            return
        start, end = self._pending_start, cell
        self._pending_start = None
        self._legal_destinations = frozenset()
        if start == end:
            return  # clicking the same cell again just deselects it
        self._client.send(f"MOVE {self._square(start)} {self._square(end)}")

    def _square(self, cell):
        return square_name(cell, self._snapshot.height)

    def tick(self):
        for message in self._client.drain():
            self._events.publish(message["type"], message.get("payload"))
            if message["type"] == "snapshot":
                self._snapshot = snapshot_from_json(message["payload"])
            elif message["type"] == "rejected":
                self._rejection_reason = message["payload"]["reason"]
            elif message["type"] == "legal_destinations":
                self._apply_legal_destinations(message["payload"])

        if self._snapshot is None:
            self._latest_snapshot = None
        else:
            self._latest_snapshot = dataclasses.replace(
                self._snapshot, selected=self._pending_start, rejection_reason=self._rejection_reason,
                legal_destinations=self._legal_destinations,
            )

    def _apply_legal_destinations(self, payload):
        # A reply to a SELECT that's since been superseded (a second click
        # already sent the MOVE, or a new SELECT for a different cell is
        # already pending) arrives here too late to matter - only apply it
        # while it still answers the click currently pending.
        if self._pending_start is None or list(self._pending_start) != payload["start"]:
            return
        self._legal_destinations = frozenset(tuple(cell) for cell in payload["destinations"])

    def latest_snapshot(self):
        return self._latest_snapshot

    def close(self):
        self._client.stop()
