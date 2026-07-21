"""An audit trail for the client, distinct from game/presentation_stub.py
(a placeholder for a future sound/animation layer, reacting to
GameEngine's own local events): this logs the network/session lifecycle
itself - login attempts, room create/join, matchmaking results, connection
state, a rejected move, a resignation - to whatever handler main_gui.py's
logging setup points at (a local log file), so a session can be debugged
after the fact without reproducing it live.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_LOGGED_EVENTS = (
    "connected", "disconnected", "connection_error",
    "login", "login_rejected",
    "room", "no_match",
    "opponent_disconnected", "opponent_reconnected",
    "resign", "rejected", "error",
)


def attach_session_logging(events):
    for event_type in _LOGGED_EVENTS:
        events.subscribe(event_type, _make_logger(event_type))


def _make_logger(event_type):
    def handler(payload):
        logger.info("%s: %r", event_type, payload)

    return handler
