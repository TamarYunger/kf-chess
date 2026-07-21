from __future__ import annotations

from abc import ABC, abstractmethod


class GameSession(ABC):
    """What the UI (the render loop, every Screen) talks to instead of
    GameEngine or a network client directly - so the same loop and the same
    screens work identically whether the game is running locally
    (LocalGameSession, no server involved at all - "Play Offline") or over
    the network (NetworkGameSession, talking to a real server over
    WebSocket).

    Three operations, deliberately: send a command, advance one frame, read
    the latest state. Which concrete session is in play is decided once, at
    startup (e.g. HOME's "Play Offline" vs "Login" choice) - never switched
    mid-run.
    """

    @abstractmethod
    def submit_command(self, command):
        """Sends `command` (a plain dict, e.g.
        {"type": "click", "cell": (row, col)}) toward whatever is actually
        running the game - a local GameEngine or a remote server."""

    @abstractmethod
    def tick(self):
        """Does this session's own per-frame work - LocalGameSession
        advances its GameEngine's clock by the elapsed wall-clock time;
        NetworkGameSession drains its incoming-message queue and publishes
        every message on the shared bus - and updates whatever
        latest_snapshot() returns next.

        Call exactly once per frame, from the render loop itself
        (main_gui.py) - never from inside a Screen's own render(). A
        Screen has no way to know whether it's the only one that'll be
        shown this session (see the LOGIN/HOME bug this shape replaced:
        when only GAME called this via its own render(), a bus event
        published while LOGIN or HOME was current - e.g. "login" itself -
        never reached anyone, because nothing was draining the queue).
        """

    @abstractmethod
    def latest_snapshot(self):
        """Returns the most up-to-date GameSnapshot as of the last tick()
        call, or None if none is available yet (a network session before
        its first snapshot arrives; never None for a local session - see
        each implementation's constructor). A pure read - safe to call any
        number of times per frame, from any Screen, with no side effects.
        """

    def close(self):
        """Releases whatever this session holds open (a network thread, a
        socket). A no-op by default - LocalGameSession has nothing to
        close."""
