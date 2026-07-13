class BoardMapper:
    """Translates pixel coordinates into board cells (Coordinate Adapter).

    Kept out of Board and Piece so the model stays free of pixels: only this
    adapter knows the cell size. Returns None for a click that maps outside
    the board bounds.
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
