from __future__ import annotations

import time

from view.graphics_renderer import GAME_OVER_DIM_ALPHA, GAME_OVER_LINE_GAP, GAME_OVER_TEXT_COLOR
from view.img import Img
from view.screen_manager import Screen

SCREEN_WIDTH = 480
SCREEN_HEIGHT = 340
BG_COLOR = (40, 40, 40, 255)  # BGRA dark gray, matches LoginScreen/GraphicsRenderer's side panels

TITLE_TEXT = "KungFu Chess"
TITLE_COLOR = (0, 215, 255, 255)  # BGRA amber
TITLE_FONT_SCALE = 0.9
TITLE_Y = 60

BUTTON_X, BUTTON_Y, BUTTON_WIDTH, BUTTON_HEIGHT = 90, 150, 300, 50
BUTTON_COLOR = (0, 130, 0, 255)  # BGRA green
BUTTON_TEXT_COLOR = (255, 255, 255, 255)  # BGRA white
BUTTON_FONT_SCALE = 0.7
BUTTON_LABEL = "Play"
BUTTON_FILLED = -1  # cv2.FILLED, drawn ourselves rather than a native widget

SEARCHING_LINE_1 = "Searching for opponent..."
SEARCHING_FONT_SCALE_1 = 0.9
SEARCHING_FONT_SCALE_2 = 0.7
SEARCHING_THICKNESS = 2

NO_MATCH_TEXT = "No opponent found - try again"
NO_MATCH_Y = 240
NO_MATCH_TEXT_COLOR = (200, 200, 200, 255)  # BGRA light gray
NO_MATCH_FONT_SCALE = 0.6


class HomeScreen(Screen):
    """Shown after a successful LOGIN, before a game exists: a single
    "Play" button that joins the server's matchmaking queue (server.
    matchmaking.find_opponent, rating range +-100 - see server/protocol.py
    and server/ws_server.py's PLAY handling).

    Submitting sends "PLAY" through the session and otherwise does nothing
    itself - ScreenManager's own bus-driven transitions (see main_gui.py's
    build_screens: transitions={"matched": "GAME"}) are what move on to
    the board once the server finds an opponent, so this screen never
    needs to know what screen comes after it. While waiting, it shows a
    "Searching..." overlay (styled after GraphicsRenderer's own game-over
    banner - dim + centered text, per the same pattern) with a live,
    locally-ticking elapsed-time counter; a "no_match" event (the search
    timed out server-side) brings the button back with a "No opponent
    found" message instead of a shell popup.
    """

    def __init__(self, session, events):
        self._session = session
        self._events = events
        self._searching_since = None  # wall-clock time.time(), or None if not searching
        self._no_match = False
        events.subscribe("no_match", self._on_no_match)

    def on_enter(self):
        self._searching_since = None
        self._no_match = False

    def render(self, canvas):
        canvas.img = Img.create(SCREEN_WIDTH, SCREEN_HEIGHT, color=BG_COLOR).img
        text_w, _ = canvas.text_size(TITLE_TEXT, TITLE_FONT_SCALE, 2)
        canvas.put_text(TITLE_TEXT, (SCREEN_WIDTH - text_w) // 2, TITLE_Y, TITLE_FONT_SCALE, TITLE_COLOR, 2)

        if self._searching_since is not None:
            self._draw_searching_overlay(canvas)
            return

        self._draw_play_button(canvas)
        if self._no_match:
            self._draw_no_match_message(canvas)

    def handle_click(self, x, y):
        if self._searching_since is not None:
            return  # already searching - button isn't shown/clickable
        if self._button_contains(x, y):
            self._start_search()

    # -- internal ------------------------------------------------------

    def _start_search(self):
        self._no_match = False
        self._searching_since = time.time()
        self._session.submit_command("PLAY")

    def _on_no_match(self, payload):
        self._searching_since = None
        self._no_match = True

    def _button_contains(self, x, y):
        return BUTTON_X <= x <= BUTTON_X + BUTTON_WIDTH and BUTTON_Y <= y <= BUTTON_Y + BUTTON_HEIGHT

    def _draw_play_button(self, canvas):
        canvas.rectangle(
            (BUTTON_X, BUTTON_Y), (BUTTON_X + BUTTON_WIDTH, BUTTON_Y + BUTTON_HEIGHT), BUTTON_COLOR, BUTTON_FILLED,
        )
        text_w, text_h = canvas.text_size(BUTTON_LABEL, BUTTON_FONT_SCALE, 2)
        text_x = BUTTON_X + (BUTTON_WIDTH - text_w) // 2
        text_y = BUTTON_Y + (BUTTON_HEIGHT + text_h) // 2
        canvas.put_text(BUTTON_LABEL, text_x, text_y, BUTTON_FONT_SCALE, BUTTON_TEXT_COLOR, 2)

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
