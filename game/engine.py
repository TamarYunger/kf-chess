from game.models import MoveResult
from rules.reasons import Reason
from view.snapshot import GameSnapshot


class GameEngine:
    """Application-service coordinator and public command boundary.

    It owns none of the details it coordinates: legality lives in RuleEngine,
    real-time motion in RealTimeArbiter, the win rule in an injected
    WinCondition, and selection/pixel handling in the Controller. The engine
    only sequences them - applying application-level guards (game over, one
    motion at a time), delegating validation, starting validated motions,
    advancing time, and exposing a read-only snapshot.

    All collaborators are injected through the constructor - no module-level
    state, no hidden globals - so the engine is straightforward to unit test
    with fakes/stubs instead of monkeypatching.
    """

    def __init__(self, board, rule_engine, arbiter, win_condition, config):
        self._board = board
        self._rule_engine = rule_engine
        self._arbiter = arbiter
        self._win_condition = win_condition
        self._config = config
        self._game_over = False

    @property
    def game_over(self):
        return self._game_over

    @property
    def clock(self):
        return self._arbiter.clock

    def is_busy(self, cell):
        return (
            self._arbiter.is_moving_from(cell)
            or self._arbiter.is_jumping_on(cell)
            or self._arbiter.is_resting(cell)
        )

    def can_select(self, cell):
        """Whether `cell` can be picked as a move source right now."""
        self._apply_events(self._arbiter.resolve())
        if self._game_over:
            return False
        return not self.is_busy(cell) and not self._board.is_empty(*cell)

    def request_move(self, start, end):
        self._apply_events(self._arbiter.resolve())
        if self._game_over:
            return MoveResult(False, Reason.GAME_OVER)
        if self.is_busy(start):
            return MoveResult(False, Reason.BUSY_SOURCE)

        validation = self._rule_engine.validate_move(self._board, start, end)
        if not validation.is_valid:
            return MoveResult(False, validation.reason)

        # Real-time policy: only one move may be in flight at a time, so a
        # second move is rejected while any move is active and the piece that
        # started first wins a contested route. Flip ALLOW_CONCURRENT_MOVES in
        # config to lift this restriction.
        if not self._config.ALLOW_CONCURRENT_MOVES and self._arbiter.has_active_motion():
            return MoveResult(False, Reason.MOTION_IN_PROGRESS)

        self._arbiter.start_move(self._board.get(*start), start, end)
        return MoveResult(True, Reason.OK)

    def request_jump(self, cell):
        self._apply_events(self._arbiter.resolve())
        if self._game_over:
            return MoveResult(False, Reason.GAME_OVER)
        if self.is_busy(cell):
            return MoveResult(False, Reason.BUSY_CELL)
        if self._board.is_empty(*cell):
            return MoveResult(False, Reason.EMPTY_CELL)

        self._arbiter.start_jump(self._board.get(*cell), cell)
        return MoveResult(True, Reason.OK)

    def wait(self, dt):
        self._apply_events(self._arbiter.advance_time(dt))

    def snapshot(self):
        return GameSnapshot.from_board(
            self._board,
            self._game_over,
            moves=self._arbiter.active_moves,
            jumps=self._arbiter.active_jumps,
            recent_arrivals=self._arbiter.recent_arrivals,
            clock=self._arbiter.clock,
        )

    def render(self, renderer):
        self._apply_events(self._arbiter.resolve())
        return renderer.render(self.snapshot())

    # -- internal helpers -------------------------------------------------

    def _apply_events(self, events):
        """React to arrivals reported by the arbiter. The arbiter reports what
        was captured; the engine owns whether that ends the game."""
        for event in events:
            if self._win_condition.is_game_over(event.captured):
                self._game_over = True
