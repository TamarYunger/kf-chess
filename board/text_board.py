from board.board_interface import BoardRepresentation


class TextBoardRepresentation(BoardRepresentation):
    """Stores each cell as a text token (e.g. 'wK', '.').

    Internal storage (`_cells`) is a private implementation detail fully
    encapsulated behind the BoardRepresentation interface. Nothing outside
    this class ever touches `_cells` directly.
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
        return [row.copy() for row in self._cells]
