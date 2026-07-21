"""NetworkGameSession: a GameSession backed by a WebSocket connection to a
real server (see view/network_client.py). No GameEngine import here at
all - the server owns every rule; this session only forwards commands and
decodes whatever it's told.
"""
from __future__ import annotations

from view.game_session import GameSession
from view.network_client import NetworkClient
from view.snapshot_codec import snapshot_from_json


class NetworkGameSession(GameSession):
    """`events` is the same EventBus the rest of the UI (ScreenManager's
    transitions, a future login screen) shares - every incoming message is
    republished there by its own "type", not just "snapshot", so any
    screen can react to server messages this session doesn't otherwise
    know or care about."""

    def __init__(self, url, events, network_client=None):
        self._events = events
        self._client = network_client if network_client is not None else NetworkClient(url)
        self._snapshot = None
        self._client.start()

    def submit_command(self, command):
        self._client.send(command)

    def latest_snapshot(self):
        for message in self._client.drain():
            self._events.publish(message["type"], message.get("payload"))
            if message["type"] == "snapshot":
                self._snapshot = snapshot_from_json(message["payload"])
        return self._snapshot

    def close(self):
        self._client.stop()
