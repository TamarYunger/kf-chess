from __future__ import annotations

import time

from view.graphics_renderer import GAME_OVER_DIM_ALPHA, GAME_OVER_LINE_GAP, GAME_OVER_TEXT_COLOR
from view.img import Img
from view.screen_manager import Screen
from view.screens.room_dialog import RoomDialog

SCREEN_WIDTH = 480
SCREEN_HEIGHT = 340
BG_COLOR = (40, 40, 40, 255)  # BGRA dark gray, matches LoginScreen/GraphicsRenderer's side panels

TITLE_TEXT = "KungFu Chess"
TITLE_COLOR = (0, 215, 255, 255)  # BGRA amber
TITLE_FONT_SCALE = 0.9
TITLE_Y = 60

PLAY_BUTTON_X, PLAY_BUTTON_Y, BUTTON_WIDTH, BUTTON_HEIGHT = 90, 140, 300, 50
PLAY_BUTTON_COLOR = (0, 130, 0, 255)  # BGRA green
BUTTON_TEXT_COLOR = (255, 255, 255, 255)  # BGRA white
BUTTON_FONT_SCALE = 0.7
PLAY_BUTTON_LABEL = "Play"
BUTTON_FILLED = -1  # cv2.FILLED, drawn ourselves rather than a native widget

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
    ScreenManager's own bus-driven transitions (see main_gui.py's
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

    def __init__(self, session, events):
        self._session = session
        self._events = events
        self._searching_since = None  # wall-clock time.time(), or None if not searching
        self._no_match = False
        self._room_dialog = RoomDialog(session)
        events.subscribe("no_match", self._on_no_match)

    def on_enter(self):
        self._searching_since = None
        self._no_match = False
        self._room_dialog.close()

    def render(self, canvas):
        canvas.img = Img.create(SCREEN_WIDTH, SCREEN_HEIGHT, color=BG_COLOR).img
        text_w, _ = canvas.text_size(TITLE_TEXT, TITLE_FONT_SCALE, 2)
        canvas.put_text(TITLE_TEXT, (SCREEN_WIDTH - text_w) // 2, TITLE_Y, TITLE_FONT_SCALE, TITLE_COLOR, 2)

        if self._searching_since is not None:
            self._draw_searching_overlay(canvas)
        else:
            self._draw_button(canvas, PLAY_BUTTON_X, PLAY_BUTTON_Y, PLAY_BUTTON_LABEL, PLAY_BUTTON_COLOR)
            self._draw_button(canvas, ROOM_BUTTON_X, ROOM_BUTTON_Y, ROOM_BUTTON_LABEL, ROOM_BUTTON_COLOR)
            if self._no_match:
                self._draw_no_match_message(canvas)

        self._room_dialog.render(canvas)  # drawn last, on top of everything else, only if open

    def handle_click(self, x, y):
        if self._room_dialog.is_open:
            self._room_dialog.handle_click(x, y)
            return
        if self._searching_since is not None:
            return  # already searching - buttons aren't shown/clickable
        if self._button_contains(PLAY_BUTTON_X, PLAY_BUTTON_Y, x, y):
            self._start_search()
        elif self._button_contains(ROOM_BUTTON_X, ROOM_BUTTON_Y, x, y):
            self._room_dialog.open()

    def handle_key(self, key):
        self._room_dialog.handle_key(key)

    # -- internal ------------------------------------------------------

    def _start_search(self):
        self._no_match = False
        self._searching_since = time.time()
        self._session.submit_command("PLAY")

    def _on_no_match(self, payload):
        self._searching_since = None
        self._no_match = True

    def _button_contains(self, button_x, button_y, x, y):
        return button_x <= x <= button_x + BUTTON_WIDTH and button_y <= y <= button_y + BUTTON_HEIGHT

    def _draw_button(self, canvas, x, y, label, color):
        canvas.rectangle((x, y), (x + BUTTON_WIDTH, y + BUTTON_HEIGHT), color, BUTTON_FILLED)
        text_w, text_h = canvas.text_size(label, BUTTON_FONT_SCALE, 2)
        text_x = x + (BUTTON_WIDTH - text_w) // 2
        text_y = y + (BUTTON_HEIGHT + text_h) // 2
        canvas.put_text(label, text_x, text_y, BUTTON_FONT_SCALE, BUTTON_TEXT_COLOR, 2)

    def _draw_no_match_message(self, canvas):
        text_w, _ = canvas.text_size(NO_MATCH_TEXT, NO_MATCH_FONT_SCALE, 2)
        canvas.put_text(
            NO_MATCH_TEXT, (SCREEN_WIDTH - text_w) // 2, NO_MATCH_Y, NO_MATCH_FONT_SCALE, NO_MATCH_TEXT_COLOR, 2,
        )

    def _draw_searching_overlay(self, canvas):
        # Mirrors GraphicsRenderer._draw_game_over_banner's own pattern -
        # dim the whole canvas, then stack centered lines of text - reusing
        # its exact color/gap constants for visual consistency.
        elapsed_seconds = int(time.time() - self._searching_since)
        h, w = canvas.img.shape[:2]
        canvas.blend_rect(0, 0, h, w, (0, 0, 0), GAME_OVER_DIM_ALPHA)

        lines = [SEARCHING_LINE_1, f"({elapsed_seconds}s)"]
        styles = [(SEARCHING_FONT_SCALE_1, SEARCHING_THICKNESS), (SEARCHING_FONT_SCALE_2, SEARCHING_THICKNESS)]
        sizes = [canvas.text_size(text, scale, thickness) for text, (scale, thickness) in zip(lines, styles)]

        total_height = sum(size[1] for size in sizes) + GAME_OVER_LINE_GAP * (len(lines) - 1)
        y = (h - total_height) // 2
        for text, (scale, thickness), (text_w, text_h) in zip(lines, styles, sizes):
            x = (w - text_w) // 2
            y += text_h
            canvas.put_text(text, x, y, scale, GAME_OVER_TEXT_COLOR, thickness)
            y += GAME_OVER_LINE_GAP
