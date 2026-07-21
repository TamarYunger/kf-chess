from __future__ import annotations

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


class GameScreen(Screen):
    """The board screen (the GUI's only screen for now - login/room screens
    come later): renders whatever GameSnapshot its GameSession currently
    has, and turns clicks/double-clicks into commands submitted through
    that same session - it never knows or cares whether the session is
    local (LocalGameSession) or networked (NetworkGameSession).

    GraphicsRenderer's own contract - snapshot in, canvas out - is
    untouched; this screen just copies its output into the canvas
    ScreenManager handed this screen (see Screen.render).
    """

    def __init__(self, config, session, board_x_offset=SIDE_PANEL_WIDTH):
        self._config = config
        self._session = session
        self._board_x_offset = board_x_offset
        self._renderer = GraphicsRenderer(config)
        self._last_snapshot = None

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
