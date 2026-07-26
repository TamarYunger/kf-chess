"""An audit trail for the client, distinct from game/presentation_stub.py
(a placeholder for a future sound/animation layer, reacting to
GameEngine's own local events): this logs the network/session lifecycle
itself - login attempts, room create/join, matchmaking results, connection
state, a rejected move, a resignation - to whatever handler main_online.py's
logging setup points at (a local log file), so a session can be debugged
after the fact without reproducing it live. Only main_online.py attaches
this - every event it logs is network-only, so a LocalGameSession's bus
never publishes any of them.
"""
from __future__ import annotations

import logging

from bus.event_types import (
    CONNECTED, CONNECTION_ERROR, DISCONNECTED, ERROR, LOGIN, LOGIN_REJECTED, NO_MATCH,
    OPPONENT_DISCONNECTED, OPPONENT_RECONNECTED, REJECTED, RESIGN, ROOM,
)

logger = logging.getLogger(__name__)

_LOGGED_EVENTS = (
    CONNECTED, DISCONNECTED, CONNECTION_ERROR,
    LOGIN, LOGIN_REJECTED,
    ROOM, NO_MATCH,
    OPPONENT_DISCONNECTED, OPPONENT_RECONNECTED,
    RESIGN, REJECTED, ERROR,
)


def attach_session_logging(events):
    for event_type in _LOGGED_EVENTS:
        events.subscribe(event_type, _make_logger(event_type))


def _make_logger(event_type):
    def handler(payload):
        logger.info("%s: %r", event_type, payload)

    return handler
