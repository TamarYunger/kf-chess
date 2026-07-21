from __future__ import annotations

from view.graphics_renderer import GraphicsRenderer, SIDE_PANEL_WIDTH
from view.img import Img
from view.screen_manager import Screen
from view.snapshot_codec import snapshot_from_json

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
    come later): renders whatever snapshot the network client's last
    "snapshot" message carried, and turns clicks/double-clicks into outgoing
    commands instead of calling a local GameEngine directly.

    GraphicsRenderer's own contract - snapshot in, canvas out - is
    untouched; this screen just decodes the wire JSON into the same
    GameSnapshot GraphicsRenderer always took, then copies its output into
    the canvas ScreenManager handed this screen (see Screen.render).
    """

    def __init__(self, config, send, board_x_offset=SIDE_PANEL_WIDTH):
        self._config = config
        self._send = send
        self._board_x_offset = board_x_offset
        self._renderer = GraphicsRenderer(config)
        self._snapshot = None

    def update_snapshot(self, payload):
        """Subscribe this to the bus's "snapshot" event - see main_gui.py."""
        self._snapshot = snapshot_from_json(payload)

    def render(self, canvas):
        if self._snapshot is None:
            self._render_connecting(canvas)
            return
        rendered = self._renderer.render(self._snapshot)
        canvas.img = rendered.img

    def handle_click(self, x, y):
        cell = self._pixel_to_cell(x, y)
        if cell is not None:
            self._send({"type": "select_or_move", "cell": list(cell)})

    def handle_double_click(self, x, y):
        cell = self._pixel_to_cell(x, y)
        if cell is not None:
            self._send({"type": "jump", "cell": list(cell)})

    def _pixel_to_cell(self, x, y):
        if self._snapshot is None:
            return None
        cell_size = self._config.CELL_SIZE
        row, col = y // cell_size, (x - self._board_x_offset) // cell_size
        if 0 <= row < self._snapshot.height and 0 <= col < self._snapshot.width:
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
