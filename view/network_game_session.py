"""NetworkGameSession: a GameSession backed by a WebSocket connection to a
real server (see view/network_client.py). No GameEngine import here at
all - the server owns every rule; this session only forwards commands and
decodes whatever it's told.
"""
from __future__ import annotations

import dataclasses

from view.game_session import GameSession
from view.network_client import NetworkClient
from view.notation import square_name
from view.snapshot_codec import snapshot_from_json


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
        self._rejection_reason = None
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
            self._rejection_reason = None
            self._client.send(f"JUMP {self._square(cell)}")

    def _handle_click(self, cell):
        if self._pending_start is None:
            # A first click: matches Controller.click's own behaviour -
            # clears any stale rejection banner, this is a fresh attempt.
            self._rejection_reason = None
            self._pending_start = cell
            return
        start, end = self._pending_start, cell
        self._pending_start = None
        if start == end:
            return  # clicking the same cell again just deselects it
        self._client.send(f"MOVE {self._square(start)} {self._square(end)}")

    def _square(self, cell):
        return square_name(cell, self._snapshot.height)

    def latest_snapshot(self):
        for message in self._client.drain():
            self._events.publish(message["type"], message.get("payload"))
            if message["type"] == "snapshot":
                self._snapshot = snapshot_from_json(message["payload"])
            elif message["type"] == "rejected":
                self._rejection_reason = message["payload"]["reason"]

        if self._snapshot is None:
            return None
        return dataclasses.replace(
            self._snapshot, selected=self._pending_start, rejection_reason=self._rejection_reason,
        )

    def close(self):
        self._client.stop()
