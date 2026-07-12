class BoardMapper:
    """Converts pixel coordinates into board cells (Coordinate Adapter).

    Kept separate from Controller so pixel geometry has its own testable,
    reusable unit: nothing about clicks, selection, or game commands lives
    here, only the pixel<->cell arithmetic and bounds check.
    """

    def __init__(self, board, cell_size):
        self._board = board
        self._cell_size = cell_size

    def pixel_to_cell(self, x, y):
        row = y // self._cell_size
        col = x // self._cell_size
        if not self._board.in_bounds(row, col):
            return None
        return row, col