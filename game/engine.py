from game.models import MoveResult, JumpResult
from board_io.snapshot import GameSnapshot


class GameEngine:
    """Application-service coordinator: game-over guard, validation
    delegation, starting legal motions, wait delegation, and snapshots.

    GameEngine does not contain piece-specific movement logic (RuleEngine),
    pixel mapping or selection state (Controller), or arrival/capture/timing
    mechanics (RealTimeArbiter). It only sequences calls between them.

    All collaborators are injected through the constructor - no module-level
    state, no hidden globals. That makes the engine straightforward to unit
    test with fakes/stubs instead of monkeypatching.
    """

    def __init__(self, board, rule_engine, real_time_arbiter, config):
        self._board = board
        self._rule_engine = rule_engine
        self._real_time_arbiter = real_time_arbiter
        self._config = config
        self._clock = 0
        self._game_over = False

    @property
    def game_over(self):
        return self._game_over

    @property
    def clock(self):
        return self._clock

    @property
    def board(self):
        """Read-only board access for Controller/Renderer. Mutation only
        ever happens through RealTimeArbiter, at arrival time."""
        return self._board

    def is_cell_busy(self, cell):
        return self._real_time_arbiter.is_cell_busy(cell)

    def request_move(self, start, end):
        if self._game_over:
            return MoveResult(False, "game_over")

        if self._real_time_arbiter.has_active_motion():
            return MoveResult(False, "motion_in_progress")

        validation = self._rule_engine.validate_move(self._board, start, end)
        if not validation.is_valid:
            return MoveResult(False, validation.reason)

        piece = self._board.get(*start)
        self._real_time_arbiter.start_motion(piece, start, end, self._clock)
        return MoveResult(True, "ok")

    def request_jump(self, cell):
        if self._game_over:
            return JumpResult(False, "game_over")

        if self._real_time_arbiter.is_cell_busy(cell):
            return JumpResult(False, "cell_busy")

        if self._board.is_empty(*cell):
            return JumpResult(False, "empty_source")

        piece = self._board.get(*cell)
        self._real_time_arbiter.start_jump(piece, cell, self._clock)
        return JumpResult(True, "ok")

    def wait(self, dt):
        self._clock += dt
        events = self._real_time_arbiter.advance_time(self._clock)
        if any(event.king_captured for event in events):
            self._game_over = True

    def snapshot(self):
        return GameSnapshot.from_board(self._board, self._game_over)

    def render(self, renderer):
        return renderer.render(self.snapshot())