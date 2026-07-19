from __future__ import annotations


class EventBus:
    """Minimal publish/subscribe hub.

    Lets GameEngine announce "a move was accepted" / "a move arrived"
    without knowing who (if anyone) cares - so a piece actually moving
    (RealTimeArbiter state) and a list reacting to that (e.g. move history)
    stay two separate steps instead of one method doing both.
    """

    def __init__(self):
        self._listeners = {}

    def subscribe(self, event_name, callback):
        self._listeners.setdefault(event_name, []).append(callback)

    def publish(self, event_name, *args, **kwargs):
        for callback in self._listeners.get(event_name, ()):
            callback(*args, **kwargs)
