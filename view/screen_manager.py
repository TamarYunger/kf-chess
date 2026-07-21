from __future__ import annotations

from abc import ABC, abstractmethod


class Screen(ABC):
    """One screen in the GUI's state machine (e.g. LOGIN, HOME, ROOM_DIALOG,
    GAME). Owns nothing about how it got shown or which screen comes next -
    ScreenManager decides that, driven by bus events - so a screen only
    needs to know how to draw itself and react to input while it's current.
    """

    def on_enter(self):
        """Called by ScreenManager right after this screen becomes current."""

    def on_exit(self):
        """Called by ScreenManager right before switching away from this screen."""

    @abstractmethod
    def render(self, canvas):
        """Draw onto `canvas` (a view.img.Img). A screen may draw into it in
        place (canvas.rectangle/put_text/...) or replace its `.img` array
        outright (e.g. GameScreen swaps in GraphicsRenderer's own output) -
        whichever fits that screen best."""

    def handle_click(self, x, y):
        """A single left click at window pixel (x, y). No-op by default."""

    def handle_double_click(self, x, y):
        """A double left click at window pixel (x, y). No-op by default."""

    def handle_key(self, key):
        """A key code from view.img.Img.wait_key. No-op by default."""


class ScreenManager:
    """Small state machine over a set of named Screens (Observer pattern).

    Screen transitions are driven by bus events instead of being hardcoded
    in the render loop: `register("HOME", home_screen, transitions=
    {"login_success": "HOME"})` means the manager itself subscribes to
    "login_success" on the injected bus and switches to "HOME" whenever
    it's published - the render loop never needs to know that event exists.
    """

    def __init__(self, events, initial):
        self._events = events
        self._screens = {}
        self._current = initial

    def register(self, name, screen, transitions=None):
        self._screens[name] = screen
        for event_type, target in (transitions or {}).items():
            self._events.subscribe(event_type, self._transition_handler(target))

    def _transition_handler(self, target):
        def handler(payload):
            self.go_to(target)
        return handler

    @property
    def current_name(self):
        return self._current

    @property
    def current(self):
        return self._screens[self._current]

    def go_to(self, name):
        if name == self._current:
            return
        if self._current in self._screens:
            self._screens[self._current].on_exit()
        self._current = name
        if name in self._screens:
            self._screens[name].on_enter()

    def render(self, canvas):
        self.current.render(canvas)

    def handle_click(self, x, y):
        self.current.handle_click(x, y)

    def handle_double_click(self, x, y):
        self.current.handle_double_click(x, y)

    def handle_key(self, key):
        self.current.handle_key(key)
