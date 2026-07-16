from rules.reasons import Reason


class Controller:
    """Translates user clicks/jumps into GameEngine commands and owns the
    selected-cell state. It decides nothing about chess legality - it only
    turns pixels into cells (via BoardMapper) and drives the engine's public
    command path, then updates its selection from the engine's MoveResult.

    Both collaborators are injected. Selection is deliberately kept here (not
    on the engine) so the engine stays a pure application service.
    """

    def __init__(self, engine, board_mapper):
        self._engine = engine
        self._mapper = board_mapper
        self._selected = None
        self._last_rejection = None

    @property
    def selected(self):
        return self._selected

    @property
    def last_rejection(self):
        """The Reason a move/jump was most recently rejected for, or None if
        the last attempted command succeeded (or nothing has been attempted
        yet) - purely UI feedback, cleared on the next successful command."""
        return self._last_rejection

    def click(self, x, y):
        cell = self._mapper.pixel_to_cell(x, y)
        if cell is None:
            # Outside the board: leave selection untouched (a no-op click).
            return

        if self._selected is None:
            # First click selects a piece if that cell can be a move source.
            # can_select() settles pending arrivals and refuses after game over.
            if self._engine.can_select(cell):
                self._selected = cell
            return

        # Second click: ask the engine to move, then update selection.
        result = self._engine.request_move(self._selected, cell)
        self._resolve_selection(result, cell)

    def jump(self, x, y):
        # A jump always ends any pending selection first (matches the engine's
        # historical order: selection is cleared before the jump is attempted).
        self._selected = None
        cell = self._mapper.pixel_to_cell(x, y)
        if cell is None:
            return
        result = self._engine.request_jump(cell)
        self._last_rejection = None if result.is_accepted else result.reason

    def _resolve_selection(self, result, cell):
        # Clicking another of your own pieces re-selects it (unless that piece
        # is busy). Every other second click clears the selection: the move
        # started, or the target was not a legal destination (illegal, blocked
        # by another motion, off-limits after game over, or an unusable source).
        if result.reason == Reason.FRIENDLY_DESTINATION and self._engine.can_select(cell):
            self._selected = cell
            self._last_rejection = None
        else:
            self._selected = None
            self._last_rejection = None if result.is_accepted else result.reason
