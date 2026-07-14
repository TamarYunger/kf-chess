from pathlib import Path

import cv2

from view.img import Img
from view.piece_assets import load_all_piece_configs, sprite_path
from view.animation import compute_piece_views

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SELECTION_COLOR = (0, 255, 255, 255)  # BGRA yellow
SELECTION_THICKNESS = 4


class GraphicsRenderer:
    """Renders a GameSnapshot onto a cv2/numpy canvas (an Img), the
    graphical counterpart to BoardRenderer.render's plain text. Consumes
    only the read-only snapshot - never a live Board or arbiter - matching
    how the text renderer is kept isolated from the model.
    """

    def __init__(self, config, assets_dir=None):
        self._config = config
        root = Path(assets_dir) if assets_dir is not None else PROJECT_ROOT / config.ASSETS_DIR
        self._pieces_root = root / "pieces"
        self._board_image_path = root / "board.png"
        self._piece_configs = load_all_piece_configs(self._pieces_root)
        self._sprite_cache = {}
        self._board_base = None
        self._board_base_size = None

    def render(self, snapshot):
        canvas = self._board_canvas(snapshot.width, snapshot.height)
        if snapshot.selected is not None:
            self._draw_selection(canvas, snapshot.selected)
        for view in compute_piece_views(snapshot, self._piece_configs, self._config):
            sprite = self._sprite(view.folder, view.state, view.frame_index)
            sprite.draw_on(canvas, int(view.x), int(view.y))
        return canvas

    def _board_canvas(self, width, height):
        cell = self._config.CELL_SIZE
        size = (width * cell, height * cell)
        if self._board_base is None or self._board_base_size != size:
            self._board_base = Img().read(str(self._board_image_path), size=size)
            self._board_base_size = size
        canvas = Img()
        canvas.img = self._board_base.img.copy()
        return canvas

    def _sprite(self, folder, state, frame_index):
        key = (folder, state, frame_index)
        sprite = self._sprite_cache.get(key)
        if sprite is None:
            cell = self._config.CELL_SIZE
            path = sprite_path(folder, state, frame_index, self._pieces_root)
            sprite = Img().read(str(path), size=(cell, cell))
            self._sprite_cache[key] = sprite
        return sprite

    def _draw_selection(self, canvas, cell):
        cell_size = self._config.CELL_SIZE
        row, col = cell
        top_left = (col * cell_size, row * cell_size)
        bottom_right = ((col + 1) * cell_size, (row + 1) * cell_size)
        cv2.rectangle(canvas.img, top_left, bottom_right, SELECTION_COLOR, SELECTION_THICKNESS)
