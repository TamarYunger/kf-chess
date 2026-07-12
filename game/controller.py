class Controller:
    """Translates clicks/jumps into GameEngine commands. Owns selection
    state and pixel mapping; decides nothing about chess legality, never
    mutates Board, and never touches timing directly.

    Talks to GameEngine only through its public API (request_move,
    request_jump, is_cell_busy, game_over, and read-only board access for
    selection-UX decisions like "is this my own piece").
    """

    def __init__(self, engine, board_mapper):
        self._engine = engine
        self._mapper = board_mapper
        self._selected = None

    @property
    def selected(self):
        return self._selected

    def click(self, x, y):
        if self._engine.game_over:
            return

        cell = self._mapper.pixel_to_cell(x, y)
        if cell is None:
            return

        if self._selected is None:
            self._selected = self._select(cell)
            return

        self._act_on_selection(cell)

    def jump(self, x, y):
        self._selected = None
        if self._engine.game_over:
            return

        cell = self._mapper.pixel_to_cell(x, y)
        if cell is None:
            return

        self._engine.request_jump(cell)

    # -- internal helpers -------------------------------------------------

    def _select(self, cell):
        if self._engine.is_cell_busy(cell):
            return None
        board = self._engine.board
        return cell if not board.is_empty(*cell) else None

    def _act_on_selection(self, cell):
        start = self._selected
        board = self._engine.board
        piece = board.get(*start)

        if board.is_empty(*start) or self._engine.is_cell_busy(start):
            self._selected = None
            return

        target = board.get(*cell)
        if not board.is_empty(*cell) and target[0] == piece[0]:
            if not self._engine.is_cell_busy(cell):
                self._selected = cell
            return

        result = self._engine.request_move(start, cell)
        if result.accepted:
            self._selected = None
        # illegal target or a move already in flight: keep current selection