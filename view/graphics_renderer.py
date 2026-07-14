from pathlib import Path

import cv2
import numpy as np

from view.img import Img
from view.piece_assets import load_all_piece_configs, sprite_path
from view.animation import compute_piece_views

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SELECTION_COLOR = (0, 255, 255, 255)  # BGRA yellow
SELECTION_THICKNESS = 4

REST_OVERLAY_COLOR = (0, 165, 255)  # BGR amber
REST_OVERLAY_MAX_ALPHA = 0.55

GAME_OVER_DIM_ALPHA = 0.55
GAME_OVER_TEXT_COLOR = (255, 255, 255, 255)  # BGRA white
GAME_OVER_LINE_GAP = 30
COLOR_NAMES = {"w": "WHITE", "b": "BLACK"}


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
            if view.rest_fraction:
                self._draw_rest_overlay(canvas, view.cell, view.rest_fraction)
            sprite = self._sprite(view.folder, view.state, view.frame_index)
            sprite.draw_on(canvas, int(view.x), int(view.y))
        if snapshot.game_over:
            self._draw_game_over_banner(canvas, snapshot)
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

    def _draw_rest_overlay(self, canvas, cell, rest_fraction):
        """Colors the resting piece's cell, receding from the top down as
        the cooldown counts down - full cell coloured right on landing,
        nothing left once the piece is free to act again."""
        cell_size = self._config.CELL_SIZE
        row, col = cell
        height = int(round(rest_fraction * cell_size))
        if height <= 0:
            return

        left = col * cell_size
        right = left + cell_size
        top = row * cell_size + (cell_size - height)
        bottom = row * cell_size + cell_size

        region = canvas.img[top:bottom, left:right, :3]
        color = np.array(REST_OVERLAY_COLOR, dtype=np.float32)
        blended = region.astype(np.float32) * (1 - REST_OVERLAY_MAX_ALPHA) + color * REST_OVERLAY_MAX_ALPHA
        region[:] = blended.astype(region.dtype)

    def _draw_game_over_banner(self, canvas, snapshot):
        img = canvas.img
        h, w = img.shape[:2]

        dim_region = img[:, :, :3]
        dim_region[:] = (dim_region.astype(np.float32) * (1 - GAME_OVER_DIM_ALPHA)).astype(dim_region.dtype)

        lines = ["GAME OVER"]
        if snapshot.winner is not None:
            name = COLOR_NAMES.get(snapshot.winner, snapshot.winner.upper())
            lines.append(f"{name} WINS")

        font = cv2.FONT_HERSHEY_SIMPLEX
        styles = [(2.0, 5) if i == 0 else (1.1, 3) for i in range(len(lines))]
        sizes = [cv2.getTextSize(text, font, scale, thickness)[0]
                 for text, (scale, thickness) in zip(lines, styles)]

        total_height = sum(size[1] for size in sizes) + GAME_OVER_LINE_GAP * (len(lines) - 1)
        y = (h - total_height) // 2
        for text, (scale, thickness), (text_w, text_h) in zip(lines, styles, sizes):
            x = (w - text_w) // 2
            y += text_h
            cv2.putText(img, text, (x, y), font, scale, GAME_OVER_TEXT_COLOR, thickness, cv2.LINE_AA)
            y += GAME_OVER_LINE_GAP
