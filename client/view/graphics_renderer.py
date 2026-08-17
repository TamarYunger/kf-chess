from __future__ import annotations

import logging
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

from board.notation import move_notation
from client.view.animation import compute_piece_views
from client.view.img import Img
from client.view.piece_assets import load_all_piece_configs, sprite_path

if TYPE_CHECKING:
    from game.snapshot import GameSnapshot

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# What a missing/corrupt sprite frame renders as instead - loud (magenta,
# the traditional "missing texture" color) so it's obviously wrong rather
# than silently invisible, but it lets the render loop - and the game
# session it's serving - keep going instead of crashing mid-game the first
# time a rarely-hit animation frame is actually needed (see _sprite()).
MISSING_SPRITE_COLOR = (255, 0, 255, 255)  # BGRA magenta

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
# Plain string values, matching rules.reasons.Reason's own wire values
# (Reason is a str Enum) - kept as bare strings rather than importing
# Reason itself, so this Presentation-layer module has no dependency on
# the Model layer at all (see CLAUDE.md's layering rule).
REJECTION_MESSAGES = {
    "outside_board": "Outside the board",
    "empty_source": "No piece there",
    "friendly_destination": "Your own piece is already there",
    "illegal_piece_move": "Illegal move for that piece",
    "game_over": "The game is over",
    "busy_source": "That piece is already moving",
    "motion_in_progress": "Another move is already in progress",
    "busy_cell": "That cell is busy",
    "empty_cell": "No piece there to jump",
    "destination_contested": "Another of your pieces is already headed there",
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


def draw_centered_banner(
    canvas: Img,
    lines: list[tuple[str, float, int]],
    dim_alpha: float = GAME_OVER_DIM_ALPHA,
    text_color: tuple = GAME_OVER_TEXT_COLOR,
    line_gap: int = GAME_OVER_LINE_GAP,
) -> None:
    """Dims the whole canvas, then stacks `lines` (each a (text, font_scale,
    thickness) triple) centered both ways - the shared shape behind
    GraphicsRenderer's own game-over banner and every screen-level
    "waiting"/"searching"/"disconnected" overlay (home_screen.py's
    _draw_searching_overlay, game_screen.py's _draw_waiting_overlay/
    _draw_disconnect_overlay), which used to each carry their own copy of
    this dim+stack+center logic."""
    h, w = canvas.img.shape[:2]
    canvas.blend_rect(0, 0, h, w, (0, 0, 0), dim_alpha)

    sizes = [canvas.text_size(text, scale, thickness) for text, scale, thickness in lines]
    total_height = sum(size[1] for size in sizes) + line_gap * (len(lines) - 1)
    y = (h - total_height) // 2
    for (text, scale, thickness), (text_w, text_h) in zip(lines, sizes):
        x = (w - text_w) // 2
        y += text_h
        canvas.put_text(text, x, y, scale, text_color, thickness)
        y += line_gap


def draw_bottom_banner(
    canvas: Img, message: str, font_scale: float, thickness: int, padding: int,
    text_color: tuple, bar_color: tuple, bar_alpha: float,
) -> None:
    """A bottom bar sized to `message`, its text centered on it - the shared
    shape behind GraphicsRenderer's own move-rejection banner and
    LoginScreen's identically-styled error banner, which used to each carry
    their own copy of this exact layout."""
    h, w = canvas.img.shape[:2]
    text_w, text_h = canvas.text_size(message, font_scale, thickness)
    bar_h = text_h + 2 * padding
    top = h - bar_h
    canvas.blend_rect(top, 0, h, w, bar_color, bar_alpha)
    x = (w - text_w) // 2
    y = h - padding - 2
    canvas.put_text(message, x, y, font_scale, text_color, thickness)


class GraphicsRenderer:
    """Renders a GameSnapshot onto an Img canvas, the graphical counterpart
    to BoardRenderer.render's plain text. Consumes
    only the read-only snapshot - never a live Board or arbiter - matching
    how the text renderer is kept isolated from the model.
    """

    def __init__(self, config: ModuleType, assets_dir: str | Path | None = None) -> None:
        self._config = config
        root = Path(assets_dir) if assets_dir is not None else PROJECT_ROOT / config.ASSETS_DIR
        self._pieces_root = root / "pieces"
        self._board_image_path = root / "board.png"
        self._piece_configs = load_all_piece_configs(self._pieces_root)
        self._sprite_cache: dict[tuple, Img] = {}
        self._board_base: Img | None = None
        self._board_base_size: tuple[int, int] | None = None

    def render(self, snapshot: GameSnapshot) -> Img:
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

    def _board_canvas(self, width: int, height: int) -> Img:
        cell = self._config.CELL_SIZE
        size = (width * cell, height * cell)
        if self._board_base is None or self._board_base_size != size:
            self._board_base = Img().read(str(self._board_image_path), size=size)
            self._board_base.to_bgra()
            self._board_base_size = size
        canvas = Img()
        canvas.img = self._board_base.img.copy()
        return canvas

    def _sprite(self, folder: str, state: str, frame_index: int) -> Img:
        key = (folder, state, frame_index)
        sprite = self._sprite_cache.get(key)
        if sprite is None:
            cell = self._config.CELL_SIZE
            path = sprite_path(folder, state, frame_index, self._pieces_root)
            try:
                sprite = Img().read(str(path), size=(cell, cell))
            except FileNotFoundError:
                # Missing or unreadable (cv2 also raises this for a corrupt
                # file - see Img.read) - a live game shouldn't crash over
                # one bad sprite frame that only gets requested this late.
                logger.warning("missing or unreadable sprite %s - using a placeholder", path)
                sprite = Img.create(cell, cell, color=MISSING_SPRITE_COLOR)
            self._sprite_cache[key] = sprite
        return sprite

    def _cell_rect(self, row: int, col: int) -> tuple[tuple[int, int], tuple[int, int]]:
        """(top_left, bottom_right) pixel corners of board cell (row, col) -
        shared by every draw method that outlines or fills a whole cell,
        instead of each recomputing the same col*cell_size/row*cell_size
        math on its own."""
        cell_size = self._config.CELL_SIZE
        top_left = (col * cell_size, row * cell_size)
        bottom_right = (top_left[0] + cell_size, top_left[1] + cell_size)
        return top_left, bottom_right

    def _draw_selection(self, canvas: Img, cell: tuple[int, int]) -> None:
        top_left, bottom_right = self._cell_rect(*cell)
        canvas.rectangle(top_left, bottom_right, SELECTION_COLOR, SELECTION_THICKNESS)

    def _draw_legal_destination(self, canvas: Img, snapshot: GameSnapshot, cell: tuple[int, int]) -> None:
        row, col = cell
        if snapshot.cells[row][col] == self._config.EMPTY_CELL:
            self._draw_legal_move_dot(canvas, row, col)
        else:
            self._draw_legal_capture_ring(canvas, row, col)

    def _draw_legal_move_dot(self, canvas: Img, row: int, col: int) -> None:
        cell_size = self._config.CELL_SIZE
        radius = max(1, int(cell_size * LEGAL_MOVE_DOT_RADIUS_FRACTION))
        cx = col * cell_size + cell_size // 2
        cy = row * cell_size + cell_size // 2
        canvas.blend_circle(cx, cy, radius, LEGAL_MOVE_DOT_COLOR, LEGAL_MOVE_DOT_ALPHA)

    def _draw_legal_capture_ring(self, canvas: Img, row: int, col: int) -> None:
        top_left, bottom_right = self._cell_rect(row, col)
        canvas.rectangle(top_left, bottom_right, LEGAL_CAPTURE_RING_COLOR, LEGAL_CAPTURE_RING_THICKNESS)

    def _draw_rest_overlay(self, canvas: Img, cell: tuple[int, int], rest_fraction: float) -> None:
        """Colors the resting piece's cell, receding from the top down as
        the cooldown counts down - full cell coloured right on landing,
        nothing left once the piece is free to act again."""
        cell_size = self._config.CELL_SIZE
        row, col = cell
        height = int(round(rest_fraction * cell_size))
        if height <= 0:
            return

        (left, _), (right, bottom) = self._cell_rect(row, col)
        top = bottom - height
        canvas.blend_rect(top, left, bottom, right, REST_OVERLAY_COLOR, REST_OVERLAY_MAX_ALPHA)

    def _draw_game_over_banner(self, canvas: Img, snapshot: GameSnapshot) -> None:
        lines = [("GAME OVER", 2.0, 5)]
        if snapshot.winner is not None:
            name = COLOR_NAMES.get(snapshot.winner, snapshot.winner.upper())
            lines.append((f"{name} WINS", 1.1, 3))
        draw_centered_banner(canvas, lines)

    def _draw_rejection_banner(self, canvas: Img, message: str) -> None:
        draw_bottom_banner(
            canvas, message, REJECTION_FONT_SCALE, REJECTION_THICKNESS, REJECTION_PADDING,
            REJECTION_TEXT_COLOR, REJECTION_BAR_COLOR, REJECTION_BAR_ALPHA,
        )

    def _with_side_panels(self, board_canvas: Img, snapshot: GameSnapshot) -> Img:
        """Returns a new, wider canvas: a panel for the first color on the
        left, the board unchanged in the middle, and a panel for every
        other color on the right - a two-color game (the normal case) gets
        one full panel per side; any extra colors just add columns to the
        right panel instead of a third side."""
        board_h, board_w = board_canvas.img.shape[:2]
        colors = self._config.COLORS
        left_colors, right_colors = (colors[:1], colors[1:]) if colors else ((), ())

        total_w = SIDE_PANEL_WIDTH + board_w + SIDE_PANEL_WIDTH
        canvas = Img.create(total_w, board_h, color=SIDE_PANEL_BG_COLOR)
        board_canvas.draw_on(canvas, SIDE_PANEL_WIDTH, 0)

        self._draw_color_panel(canvas, snapshot, left_colors, 0, SIDE_PANEL_WIDTH, board_h)
        self._draw_color_panel(canvas, snapshot, right_colors, SIDE_PANEL_WIDTH + board_w, SIDE_PANEL_WIDTH, board_h)
        return canvas

    def _draw_color_panel(
        self,
        canvas: Img,
        snapshot: GameSnapshot,
        colors: tuple[str, ...],
        x_offset: int,
        panel_width: int,
        panel_height: int,
    ) -> None:
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
