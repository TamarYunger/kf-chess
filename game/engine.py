from game.models import Move, Jump
from rules.movement_strategy import MoveContext


class GameEngine:
    """Orchestrates KungFu Chess turns: clicks, jumps, waiting, and move
    resolution.

    All collaborators (board, rule registry, win condition, promotion
    rule, config) are injected through the constructor - no module-level
    state, no hidden globals. That makes the engine straightforward to
    unit test with fakes/stubs instead of monkeypatching.
    """

    def __init__(self, board, rule_registry, win_condition, promotion_rule, config):
        self._board = board
        self._registry = rule_registry
        self._win_condition = win_condition
        self._promotion_rule = promotion_rule
        self._config = config
        self._clock = 0
        self._selected = None
        self._active_moves = []
        self._active_jumps = []
        self._game_over = False

    @property
    def game_over(self):
        return self._game_over

    @property
    def clock(self):
        return self._clock

    @property
    def selected(self):
        return self._selected

    def wait(self, dt):
        self._clock += dt
        self._resolve_moves()

    def render(self, renderer):
        self._resolve_moves()
        return renderer.render(self._board)

    def handle_click(self, x, y):
        self._resolve_moves()
        if self._game_over:
            return

        cell = self._pixel_to_cell(x, y)
        if cell is None:
            return

        if self._selected is None:
            self._selected = self._select(cell)
            return

        self._act_on_selection(cell)

    def handle_jump(self, x, y):
        self._resolve_moves()
        self._selected = None
        if self._game_over:
            return

        cell = self._pixel_to_cell(x, y)
        if cell is None:
            return

        if self._is_busy(cell):
            return

        piece = self._board.get(*cell)
        if piece == self._config.EMPTY_CELL:
            return

        self._active_jumps.append(Jump(piece, cell, self._clock + self._config.JUMP_DURATION))

    # -- internal helpers -------------------------------------------------

    def _pixel_to_cell(self, x, y):
        row = y // self._config.CELL_SIZE
        col = x // self._config.CELL_SIZE
        if not self._board.in_bounds(row, col):
            return None
        return row, col

    def _select(self, cell):
        if self._is_busy(cell):
            return None
        return cell if self._board.get(*cell) != self._config.EMPTY_CELL else None

    def _act_on_selection(self, cell):
        start = self._selected
        piece = self._board.get(*start)

        if piece == self._config.EMPTY_CELL or self._is_busy(start):
            self._selected = None
            return

        target = self._board.get(*cell)
        if target != self._config.EMPTY_CELL and target[0] == piece[0]:
            if not self._is_busy(cell):
                self._selected = cell
            return

        if not self._is_legal_move(piece, start, cell):
            return  # illegal target: keep current selection

        self._board.set(*start, self._config.EMPTY_CELL)
        self._active_moves.append(
            Move(piece, start, cell, self._clock + self._config.MOVE_DURATION)
        )
        self._selected = None

    def _is_legal_move(self, piece, start, end):
        strategy = self._registry.get(piece[1])
        dr, dc = end[0] - start[0], end[1] - start[1]
        context = MoveContext(
            board=self._board,
            color=piece[0],
            start=start,
            end=end,
            target_occupied=not self._board.is_empty(*end),
        )
        return strategy.is_legal(dr, dc, context)

    def _is_busy(self, cell):
        return self._is_moving_from(cell) or self._is_jumping_on(cell)

    def _is_moving_from(self, cell):
        return any(move.start == cell for move in self._active_moves)

    def _is_jumping_on(self, cell):
        return any(jump.cell == cell for jump in self._active_jumps)

    def _resolve_moves(self):
        remaining = []
        for move in self._active_moves:
            if self._clock < move.arrival:
                remaining.append(move)
                continue
            self._settle_move(move)
        self._active_moves = remaining
        self._resolve_jumps()

    def _settle_move(self, move):
        if self._is_intercepted(move):
            return

        r, c = move.end
        target = self._board.get(r, c)
        if target != self._config.EMPTY_CELL and target[0] == move.piece[0]:
            return

        captured = None if target == self._config.EMPTY_CELL else target
        if self._win_condition.is_game_over(captured):
            self._game_over = True

        piece = self._promotion_rule.promote(move.piece, r, self._board.height)
        self._board.set(r, c, piece)

    def _is_intercepted(self, move):
        r, c = move.end
        return any(
            jump.cell == (r, c) and jump.piece[0] != move.piece[0]
            for jump in self._active_jumps
        )

    def _resolve_jumps(self):
        self._active_jumps = [j for j in self._active_jumps if self._clock < j.end_time]
