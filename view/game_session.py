from __future__ import annotations

from abc import ABC, abstractmethod


class GameSession(ABC):
    """What the UI (the render loop, every Screen) talks to instead of
    GameEngine or a network client directly - so the same loop and the same
    screens work identically whether the game is running locally
    (LocalGameSession, no server involved at all - "Play Offline") or over
    the network (NetworkGameSession, talking to a real server over
    WebSocket).

    Exactly two operations, deliberately: send a command, read the latest
    state. Which concrete session is in play is decided once, at startup
    (e.g. a future home screen's "Play Offline" vs "Login" choice) - never
    switched mid-run.
    """

    @abstractmethod
    def submit_command(self, command):
        """Sends `command` (a plain dict, e.g.
        {"type": "click", "cell": (row, col)}) toward whatever is actually
        running the game - a local GameEngine or a remote server."""

    @abstractmethod
    def latest_snapshot(self):
        """Returns the most up-to-date GameSnapshot this session knows
        about, or None if none is available yet (a network session before
        its first message arrives; never None for a local session).

        Call exactly once per frame: this is also each implementation's one
        chance to do its own per-frame work - LocalGameSession advances its
        GameEngine's clock by the elapsed wall-clock time,
        NetworkGameSession drains its incoming-message queue - so the
        caller never needs to know which kind of work that is.
        """

    def close(self):
        """Releases whatever this session holds open (a network thread, a
        socket). A no-op by default - LocalGameSession has nothing to
        close."""
