from __future__ import annotations

import time

from view.graphics_renderer import GAME_OVER_DIM_ALPHA, GAME_OVER_LINE_GAP, GAME_OVER_TEXT_COLOR
from view.graphics_renderer import GraphicsRenderer, SIDE_PANEL_WIDTH
from view.img import Img
from view.screen_manager import Screen

CONNECTING_TEXT = "Connecting to server..."
CONNECTING_TEXT_COLOR = (230, 230, 230, 255)  # BGRA near-white
CONNECTING_BG_COLOR = (30, 30, 30, 255)  # BGRA near-black
CONNECTING_FONT_SCALE = 0.8

# Board size assumed only for the placeholder shown before any snapshot has
# arrived - purely cosmetic (window size while "Connecting..." is on
# screen); the real board dimensions come from the first snapshot and
# GraphicsRenderer sizes its own canvas from those, same as before.
DEFAULT_BOARD_SIZE = 8

DISCONNECT_LINE_1 = "Opponent disconnected"
DISCONNECT_FONT_SCALE_1 = 0.9
DISCONNECT_FONT_SCALE_2 = 0.7
DISCONNECT_THICKNESS = 2


class GameScreen(Screen):
    """The board screen: renders whatever GameSnapshot its GameSession
    currently has, and turns clicks/double-clicks into commands submitted
    through that same session - it never knows or cares whether the
    session is local (LocalGameSession) or networked (NetworkGameSession).

    GraphicsRenderer's own contract - snapshot in, canvas out - is
    untouched; this screen just copies its output into the canvas
    ScreenManager handed this screen (see Screen.render), then layers a
    disconnect-countdown overlay on top when relevant (see
    "opponent_disconnected"/"opponent_reconnected" below) - styled after
    GraphicsRenderer's own game-over banner, the same pattern
    view/screens/home_screen.py's "Searching..." overlay reuses.

    `events` is the same bus NetworkGameSession publishes server messages
    on (harmless to subscribe to for a LocalGameSession, which never
    publishes these - there's simply never an opponent to disconnect).
    """

    def __init__(self, config, session, events, board_x_offset=SIDE_PANEL_WIDTH):
        self._config = config
        self._session = session
        self._board_x_offset = board_x_offset
        self._renderer = GraphicsRenderer(config)
        self._last_snapshot = None
        self._disconnect_deadline = None  # wall-clock time.time(), or None if no countdown is active
        events.subscribe("opponent_disconnected", self._on_opponent_disconnected)
        events.subscribe("opponent_reconnected", self._on_opponent_reconnected)

    def render(self, canvas):
        # The one call per frame that lets the session do its own
        # per-frame work (advance a local clock / drain a network queue) -
        # see GameSession.latest_snapshot. Cached for handle_click/
        # handle_double_click, which run from the mouse callback, not this
        # per-frame render call, and must not themselves trigger that work.
        self._last_snapshot = self._session.latest_snapshot()
        if self._last_snapshot is None:
            self._render_connecting(canvas)
            return
        rendered = self._renderer.render(self._last_snapshot)
        canvas.img = rendered.img
        if self._disconnect_deadline is not None and not self._last_snapshot.game_over:
            self._draw_disconnect_overlay(canvas)

    def handle_click(self, x, y):
        cell = self._pixel_to_cell(x, y)
        if cell is not None:
            self._session.submit_command({"type": "click", "cell": cell})

    def handle_double_click(self, x, y):
        cell = self._pixel_to_cell(x, y)
        if cell is not None:
            self._session.submit_command({"type": "jump", "cell": cell})

    def _pixel_to_cell(self, x, y):
        if self._last_snapshot is None:
            return None
        cell_size = self._config.CELL_SIZE
        row, col = y // cell_size, (x - self._board_x_offset) // cell_size
        if 0 <= row < self._last_snapshot.height and 0 <= col < self._last_snapshot.width:
            return row, col
        return None

    def _render_connecting(self, canvas):
        cell_size = self._config.CELL_SIZE
        width = DEFAULT_BOARD_SIZE * cell_size + 2 * SIDE_PANEL_WIDTH
        height = DEFAULT_BOARD_SIZE * cell_size
        canvas.img = Img.create(width, height, color=CONNECTING_BG_COLOR).img
        text_w, text_h = canvas.text_size(CONNECTING_TEXT, CONNECTING_FONT_SCALE, 2)
        canvas.put_text(
            CONNECTING_TEXT, (width - text_w) // 2, (height + text_h) // 2,
            CONNECTING_FONT_SCALE, CONNECTING_TEXT_COLOR, 2,
        )

    # -- opponent disconnect countdown ----------------------------------

    def _on_opponent_disconnected(self, payload):
        self._disconnect_deadline = time.time() + payload["grace_period_seconds"]

    def _on_opponent_reconnected(self, payload):
        self._disconnect_deadline = None

    def _draw_disconnect_overlay(self, canvas):
        # Mirrors GraphicsRenderer._draw_game_over_banner's own pattern -
        # dim the whole canvas, then stack centered lines of text - reusing
        # its exact color/gap constants for visual consistency.
        remaining_seconds = max(0, int(self._disconnect_deadline - time.time()))
        h, w = canvas.img.shape[:2]
        canvas.blend_rect(0, 0, h, w, (0, 0, 0), GAME_OVER_DIM_ALPHA)

        lines = [DISCONNECT_LINE_1, f"Auto-resign in {remaining_seconds}s"]
        styles = [(DISCONNECT_FONT_SCALE_1, DISCONNECT_THICKNESS), (DISCONNECT_FONT_SCALE_2, DISCONNECT_THICKNESS)]
        sizes = [canvas.text_size(text, scale, thickness) for text, (scale, thickness) in zip(lines, styles)]

        total_height = sum(size[1] for size in sizes) + GAME_OVER_LINE_GAP * (len(lines) - 1)
        y = (h - total_height) // 2
        for text, (scale, thickness), (text_w, text_h) in zip(lines, styles, sizes):
            x = (w - text_w) // 2
            y += text_h
            canvas.put_text(text, x, y, scale, GAME_OVER_TEXT_COLOR, thickness)
            y += GAME_OVER_LINE_GAP
