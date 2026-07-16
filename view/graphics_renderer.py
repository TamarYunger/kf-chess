from pathlib import Path

import cv2
import numpy as np

from rules.reasons import Reason
from view.img import Img
from view.piece_assets import load_all_piece_configs, sprite_path
from view.animation import compute_piece_views
from view.notation import move_notation

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SELECTION_COLOR = (0, 255, 255, 255)  # BGRA yellow
SELECTION_THICKNESS = 4

REST_OVERLAY_COLOR = (0, 165, 255)  # BGR amber
REST_OVERLAY_MAX_ALPHA = 0.55

GAME_OVER_DIM_ALPHA = 0.55
GAME_OVER_TEXT_COLOR = (255, 255, 255, 255)  # BGRA white
GAME_OVER_LINE_GAP = 30
COLOR_NAMES = {"w": "WHITE", "b": "BLACK"}

# Highlights for the selected piece's legal destinations: a dot centered on
# an empty cell it could move to, or a ring around a cell it could capture
# on - a centered dot would be invisible under that cell's piece sprite,
# since sprites are drawn after this.
LEGAL_MOVE_DOT_COLOR = (0, 200, 0)  # BGR green
LEGAL_MOVE_DOT_ALPHA = 0.55
LEGAL_MOVE_DOT_RADIUS_FRACTION = 0.16
LEGAL_CAPTURE_RING_COLOR = (0, 120, 255, 255)  # BGRA orange
LEGAL_CAPTURE_RING_THICKNESS = 4

# A transient bar along the bottom of the board explaining why the last
# click/jump did nothing - cleared as soon as any command succeeds (see
# Controller.last_rejection). Never shown together with the game-over
# banner (see render()): once the game is over that's the only message
# that matters.
REJECTION_BAR_COLOR = (0, 0, 180)  # BGR dark red
REJECTION_BAR_ALPHA = 0.75
REJECTION_TEXT_COLOR = (255, 255, 255, 255)  # BGRA white
REJECTION_FONT_SCALE = 0.6
REJECTION_THICKNESS = 2
REJECTION_PADDING = 8
REJECTION_MESSAGES = {
    Reason.OUTSIDE_BOARD: "Outside the board",
    Reason.EMPTY_SOURCE: "No piece there",
    Reason.FRIENDLY_DESTINATION: "Your own piece is already there",
    Reason.ILLEGAL_PIECE_MOVE: "Illegal move for that piece",
    Reason.GAME_OVER: "The game is over",
    Reason.BUSY_SOURCE: "That piece is already moving",
    Reason.MOTION_IN_PROGRESS: "Another move is already in progress",
    Reason.BUSY_CELL: "That cell is busy",
    Reason.EMPTY_CELL: "No piece there to jump",
    Reason.DESTINATION_CONTESTED: "Another of your pieces is already headed there",
}

# Per-color move-history + score panel, one flanking each side of the
# board: the first color in config.COLORS on the left, every other color
# on the right (as extra columns, for the rare case of more than two).
SIDE_PANEL_WIDTH = 220
SIDE_PANEL_BG_COLOR = (40, 40, 40, 255)  # BGRA dark gray
SIDE_PANEL_PADDING = 14
SIDE_PANEL_COLUMN_GAP = 10
SIDE_PANEL_HEADER_COLOR = (0, 215, 255, 255)  # BGRA amber
SIDE_PANEL_HEADER_FONT_SCALE = 0.6
SIDE_PANEL_HEADER_HEIGHT = 34
SIDE_PANEL_TEXT_COLOR = (230, 230, 230, 255)  # BGRA near-white
SIDE_PANEL_TEXT_FONT_SCALE = 0.5
SIDE_PANEL_LINE_HEIGHT = 22


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
        for cell in snapshot.legal_destinations:
            self._draw_legal_destination(canvas, snapshot, cell)
        for view in compute_piece_views(snapshot, self._piece_configs, self._config):
            if view.rest_fraction:
                self._draw_rest_overlay(canvas, view.cell, view.rest_fraction)
            sprite = self._sprite(view.folder, view.state, view.frame_index)
            sprite.draw_on(canvas, int(view.x), int(view.y))
        if snapshot.game_over:
            self._draw_game_over_banner(canvas, snapshot)
        elif snapshot.rejection_reason is not None:
            message = REJECTION_MESSAGES.get(snapshot.rejection_reason, str(snapshot.rejection_reason))
            self._draw_rejection_banner(canvas, message)
        return self._with_side_panels(canvas, snapshot)

    def _board_canvas(self, width, height):
        cell = self._config.CELL_SIZE
        size = (width * cell, height * cell)
        if self._board_base is None or self._board_base_size != size:
            self._board_base = Img().read(str(self._board_image_path), size=size)
            if self._board_base.img.shape[2] == 3:
                self._board_base.img = cv2.cvtColor(self._board_base.img, cv2.COLOR_BGR2BGRA)
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

    def _draw_legal_destination(self, canvas, snapshot, cell):
        row, col = cell
        if snapshot.cells[row][col] == self._config.EMPTY_CELL:
            self._draw_legal_move_dot(canvas, row, col)
        else:
            self._draw_legal_capture_ring(canvas, row, col)

    def _draw_legal_move_dot(self, canvas, row, col):
        cell_size = self._config.CELL_SIZE
        radius = max(1, int(cell_size * LEGAL_MOVE_DOT_RADIUS_FRACTION))
        cx = col * cell_size + cell_size // 2
        cy = row * cell_size + cell_size // 2

        region = canvas.img[cy - radius:cy + radius, cx - radius:cx + radius, :3]
        overlay = region.copy()
        cv2.circle(overlay, (radius, radius), radius, LEGAL_MOVE_DOT_COLOR, -1)
        blended = region.astype(np.float32) * (1 - LEGAL_MOVE_DOT_ALPHA) + overlay.astype(np.float32) * LEGAL_MOVE_DOT_ALPHA
        region[:] = blended.astype(region.dtype)

    def _draw_legal_capture_ring(self, canvas, row, col):
        cell_size = self._config.CELL_SIZE
        top_left = (col * cell_size, row * cell_size)
        bottom_right = ((col + 1) * cell_size, (row + 1) * cell_size)
        cv2.rectangle(canvas.img, top_left, bottom_right, LEGAL_CAPTURE_RING_COLOR, LEGAL_CAPTURE_RING_THICKNESS)

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
            canvas.put_text(text, x, y, scale, GAME_OVER_TEXT_COLOR, thickness)
            y += GAME_OVER_LINE_GAP

    def _draw_rejection_banner(self, canvas, message):
        img = canvas.img
        h, w = img.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX
        (text_w, text_h), _ = cv2.getTextSize(message, font, REJECTION_FONT_SCALE, REJECTION_THICKNESS)

        bar_h = text_h + 2 * REJECTION_PADDING
        top = h - bar_h
        region = img[top:h, :, :3]
        color = np.array(REJECTION_BAR_COLOR, dtype=np.float32)
        blended = region.astype(np.float32) * (1 - REJECTION_BAR_ALPHA) + color * REJECTION_BAR_ALPHA
        region[:] = blended.astype(region.dtype)

        x = (w - text_w) // 2
        y = h - REJECTION_PADDING - 2
        canvas.put_text(message, x, y, REJECTION_FONT_SCALE, REJECTION_TEXT_COLOR, REJECTION_THICKNESS)

    def _with_side_panels(self, board_canvas, snapshot):
        """Returns a new, wider canvas: a panel for the first color on the
        left, the board unchanged in the middle, and a panel for every
        other color on the right - a two-color game (the normal case) gets
        one full panel per side; any extra colors just add columns to the
        right panel instead of a third side."""
        board_h, board_w = board_canvas.img.shape[:2]
        colors = self._config.COLORS
        left_colors, right_colors = (colors[:1], colors[1:]) if colors else ((), ())

        canvas = Img()
        total_w = SIDE_PANEL_WIDTH + board_w + SIDE_PANEL_WIDTH
        canvas.img = np.full((board_h, total_w, 4), SIDE_PANEL_BG_COLOR, dtype=board_canvas.img.dtype)
        canvas.img[:, SIDE_PANEL_WIDTH:SIDE_PANEL_WIDTH + board_w] = board_canvas.img

        self._draw_color_panel(canvas, snapshot, left_colors, 0, SIDE_PANEL_WIDTH, board_h)
        self._draw_color_panel(canvas, snapshot, right_colors, SIDE_PANEL_WIDTH + board_w, SIDE_PANEL_WIDTH, board_h)
        return canvas

    def _draw_color_panel(self, canvas, snapshot, colors, x_offset, panel_width, panel_height):
        if not colors:
            return

        column_width = (panel_width - 2 * SIDE_PANEL_PADDING
                         - (len(colors) - 1) * SIDE_PANEL_COLUMN_GAP) // len(colors)
        max_lines = max(0, (panel_height - SIDE_PANEL_HEADER_HEIGHT - SIDE_PANEL_PADDING) // SIDE_PANEL_LINE_HEIGHT)

        for i, color in enumerate(colors):
            col_x = x_offset + SIDE_PANEL_PADDING + i * (column_width + SIDE_PANEL_COLUMN_GAP)
            name = COLOR_NAMES.get(color, color.upper())
            points = snapshot.score.get(color, 0)
            canvas.put_text(f"{name}  {points}", col_x, SIDE_PANEL_PADDING + 16,
                             SIDE_PANEL_HEADER_FONT_SCALE, SIDE_PANEL_HEADER_COLOR, 2)

            records = snapshot.move_history.get(color, ())[-max_lines:] if max_lines else ()
            y = SIDE_PANEL_HEADER_HEIGHT + SIDE_PANEL_PADDING
            for record in records:
                text = move_notation(record, snapshot.height)
                canvas.put_text(text, col_x, y, SIDE_PANEL_TEXT_FONT_SCALE, SIDE_PANEL_TEXT_COLOR, 1)
                y += SIDE_PANEL_LINE_HEIGHT
