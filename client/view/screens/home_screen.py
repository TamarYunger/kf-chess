from __future__ import annotations

import time
from typing import TYPE_CHECKING

from bus.event_types import NO_MATCH
from client.view.button import Button
from client.view.graphics_renderer import draw_centered_banner
from client.view.img import Img
from client.view.screen_manager import Screen
from client.view.screens.room_dialog import RoomDialog

if TYPE_CHECKING:
    from bus.event_bus import EventBus
    from client.session.game_session import GameSession

SCREEN_WIDTH = 480
SCREEN_HEIGHT = 340
BG_COLOR = (40, 40, 40, 255)  # BGRA dark gray, matches LoginScreen/GraphicsRenderer's side panels

TITLE_TEXT = "KungFu Chess"
TITLE_COLOR = (0, 215, 255, 255)  # BGRA amber
TITLE_FONT_SCALE = 0.9
TITLE_Y = 60

PLAY_BUTTON_X, PLAY_BUTTON_Y, BUTTON_WIDTH, BUTTON_HEIGHT = 90, 140, 300, 50
PLAY_BUTTON_COLOR = (0, 130, 0, 255)  # BGRA green
PLAY_BUTTON_LABEL = "Play"

ROOM_BUTTON_X, ROOM_BUTTON_Y = 90, 210
ROOM_BUTTON_COLOR = (150, 90, 0, 255)  # BGRA blue
ROOM_BUTTON_LABEL = "Room"

SEARCHING_LINE_1 = "Searching for opponent..."
SEARCHING_FONT_SCALE_1 = 0.9
SEARCHING_FONT_SCALE_2 = 0.7
SEARCHING_THICKNESS = 2

NO_MATCH_TEXT = "No opponent found - try again"
NO_MATCH_Y = 300
NO_MATCH_TEXT_COLOR = (200, 200, 200, 255)  # BGRA light gray
NO_MATCH_FONT_SCALE = 0.6


class HomeScreen(Screen):
    """Shown after a successful LOGIN, before a game exists: a "Play"
    button that joins the server's matchmaking queue (server.matchmaking.
    find_opponent, rating range +-100), and a "Room" button that opens a
    modal RoomDialog (view/screens/room_dialog.py, drawn as an overlay
    over this same screen - not a native window) to create or join a room
    by id directly.

    Neither button does anything itself beyond submitting a command -
    ScreenManager's own bus-driven transitions (see main_online.py's
    build_screens: transitions={"room": "GAME"}) are what move on to the
    board once the server actually seats this connection somewhere
    (PLAY's match or ROOM CREATE/JOIN both end up publishing the same
    "room" event), so this screen never needs to know what happens next.

    While PLAY is waiting, it shows a "Searching..." overlay (styled after
    GraphicsRenderer's own game-over banner - dim + centered text, per the
    same pattern) with a live, locally-ticking elapsed-time counter; a
    "no_match" event (the search timed out server-side) brings the
    buttons back with a "No opponent found" message instead of a shell
    popup.
    """

    def __init__(self, session: GameSession, events: EventBus) -> None:
        self._session = session
        self._events = events
        self._searching_since: float | None = None  # wall-clock time.time(), or None if not searching
        self._no_match = False
        self._room_dialog = RoomDialog(session)
        self._play_button = Button(
            PLAY_BUTTON_X, PLAY_BUTTON_Y, BUTTON_WIDTH, BUTTON_HEIGHT, PLAY_BUTTON_LABEL, PLAY_BUTTON_COLOR,
        )
        self._room_button = Button(
            ROOM_BUTTON_X, ROOM_BUTTON_Y, BUTTON_WIDTH, BUTTON_HEIGHT, ROOM_BUTTON_LABEL, ROOM_BUTTON_COLOR,
        )
        events.subscribe(NO_MATCH, self._on_no_match)

    def on_enter(self) -> None:
        self._searching_since = None
        self._no_match = False
        self._room_dialog.close()

    def render(self, canvas: Img) -> None:
        canvas.img = Img.create(SCREEN_WIDTH, SCREEN_HEIGHT, color=BG_COLOR).img
        text_w, _ = canvas.text_size(TITLE_TEXT, TITLE_FONT_SCALE, 2)
        canvas.put_text(TITLE_TEXT, (SCREEN_WIDTH - text_w) // 2, TITLE_Y, TITLE_FONT_SCALE, TITLE_COLOR, 2)

        if self._searching_since is not None:
            self._draw_searching_overlay(canvas)
        else:
            self._play_button.draw(canvas)
            self._room_button.draw(canvas)
            if self._no_match:
                self._draw_no_match_message(canvas)

        self._room_dialog.render(canvas)  # drawn last, on top of everything else, only if open

    def handle_click(self, x: int, y: int) -> None:
        if self._room_dialog.is_open:
            self._room_dialog.handle_click(x, y)
            return
        if self._searching_since is not None:
            return  # already searching - buttons aren't shown/clickable
        if self._play_button.contains(x, y):
            self._start_search()
        elif self._room_button.contains(x, y):
            self._room_dialog.open()

    def handle_key(self, key: int) -> None:
        self._room_dialog.handle_key(key)

    # -- internal ------------------------------------------------------

    def _start_search(self) -> None:
        self._no_match = False
        self._searching_since = time.time()
        self._session.submit_command("PLAY")

    def _on_no_match(self, payload: object) -> None:
        self._searching_since = None
        self._no_match = True

    def _draw_no_match_message(self, canvas: Img) -> None:
        text_w, _ = canvas.text_size(NO_MATCH_TEXT, NO_MATCH_FONT_SCALE, 2)
        canvas.put_text(
            NO_MATCH_TEXT, (SCREEN_WIDTH - text_w) // 2, NO_MATCH_Y, NO_MATCH_FONT_SCALE, NO_MATCH_TEXT_COLOR, 2,
        )

    def _draw_searching_overlay(self, canvas: Img) -> None:
        elapsed_seconds = int(time.time() - self._searching_since)
        draw_centered_banner(canvas, [
            (SEARCHING_LINE_1, SEARCHING_FONT_SCALE_1, SEARCHING_THICKNESS),
            (f"({elapsed_seconds}s)", SEARCHING_FONT_SCALE_2, SEARCHING_THICKNESS),
        ])
