class BoardMapper:
    """Translates pixel coordinates into board cells (Coordinate Adapter).

    Kept out of Board and Piece so the model stays free of pixels: only this
    adapter knows the cell size. Returns None for a click that maps outside
    the board bounds.

    `x_offset`/`y_offset` are where the board's own top-left corner actually
    sits in the window - not necessarily (0, 0), since a renderer may draw
    other things (e.g. GraphicsRenderer's side panels) before the board
    itself. They default to 0 for callers with nothing else on-screen.
    """

    def __init__(self, board, cell_size, x_offset=0, y_offset=0):
        self._board = board
        self._cell_size = cell_size
        self._x_offset = x_offset
        self._y_offset = y_offset

    def pixel_to_cell(self, x, y):
        row = (y - self._y_offset) // self._cell_size
        col = (x - self._x_offset) // self._cell_size
        if not self._board.in_bounds(row, col):
            return None
        return row, col
