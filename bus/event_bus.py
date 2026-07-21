from __future__ import annotations


class EventBus:
    """Minimal in-process publish/subscribe hub (Observer pattern).

    Lets a publisher announce that something happened without knowing who -
    if anyone - is listening. Always constructed explicitly and passed in by
    whoever needs it (e.g. `GameEngine(..., events=EventBus())`) rather than
    reached as a global/singleton, so tests can inject a fake bus and assert
    on exactly what was published.
    """

    def __init__(self):
        self._subscribers: dict[str, list] = {}

    def subscribe(self, event_type, handler):
        """Register `handler(payload)` to be called on every future
        `publish(event_type, ...)`. Multiple handlers may subscribe to the
        same event type; they run in subscription order."""
        self._subscribers.setdefault(event_type, []).append(handler)

    def publish(self, event_type, payload=None):
        """Call every handler subscribed to `event_type` with `payload`.
        A no-op if nobody has subscribed."""
        for handler in self._subscribers.get(event_type, ()):
            handler(payload)
