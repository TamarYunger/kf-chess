class Board:
    """The single in-memory board that all game logic works with: a grid of
    string tokens (e.g. 'wK', '.').

    There is deliberately one internal representation. Support for other
    *input* formats (binary, FEN, ...) is not added by subclassing this
    class, but by writing a loader that converts the external format into a
    Board (see board/loaders.py). That keeps the variation at the input
    boundary - where it actually lives - so no game-logic module changes when
    a new input format is supported; only a new loader is written.

    Internal storage (`_cells`) is a private implementation detail: nothing
    outside this class touches it directly.
    """

    def __init__(self, rows, empty_token="."):
        self._cells = [list(row) for row in rows]
        self._empty_token = empty_token
        self._height = len(self._cells)
        self._width = len(self._cells[0]) if self._cells else 0

    @property
    def width(self):
        return self._width

    @property
    def height(self):
        return self._height

    def in_bounds(self, row, col):
        return 0 <= row < self._height and 0 <= col < self._width

    def get(self, row, col):
        return self._cells[row][col]

    def set(self, row, col, value):
        self._cells[row][col] = value

    def is_empty(self, row, col):
        return self._cells[row][col] == self._empty_token

    def snapshot(self):
        """Return a read-only copy of the grid for rendering, so callers can
        never mutate the board through the value they get back."""
        return [row.copy() for row in self._cells]
