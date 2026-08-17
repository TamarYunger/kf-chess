from __future__ import annotations

import logging
from typing import Callable

from bus.event_bus import EventBus
from bus.event_types import GAME_OVER, GAME_STARTED, MOVE_LOG_UPDATED, SCORE_CHANGED

logger = logging.getLogger(__name__)

_LOGGED_EVENTS = (GAME_STARTED, GAME_OVER, SCORE_CHANGED, MOVE_LOG_UPDATED)


def attach_presentation_stub(events: EventBus) -> None:
    """Placeholder for a future sound/animation layer.

    Subscribes no-op handlers - today they only log - to the events a real
    presentation layer would react to, so GameEngine already publishes
    everything that layer will need before any of it exists. Not wired by
    GameEngine itself (it stays presentation-agnostic); call this from a
    composition root (see main.py) once the engine's bus is available.
    """
    for event_type in _LOGGED_EVENTS:
        events.subscribe(event_type, _make_logger(event_type))


def _make_logger(event_type: str) -> Callable[[object], None]:
    def handler(payload: object) -> None:
        logger.info("%s: %r", event_type, payload)

    return handler
