from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_LOGGED_EVENTS = ("game_started", "game_over", "score_changed", "move_log_updated")


def attach_presentation_stub(events):
    """Placeholder for a future sound/animation layer.

    Subscribes no-op handlers - today they only log - to the events a real
    presentation layer would react to, so GameEngine already publishes
    everything that layer will need before any of it exists. Not wired by
    GameEngine itself (it stays presentation-agnostic); call this from a
    composition root (see main.py) once the engine's bus is available.
    """
    for event_type in _LOGGED_EVENTS:
        events.subscribe(event_type, _make_logger(event_type))


def _make_logger(event_type):
    def handler(payload):
        logger.info("%s: %r", event_type, payload)

    return handler
