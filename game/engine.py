from board.piece import color_of, kind_of
from bus.event_bus import EventBus
from game.models import MoveResult
from game.move_history import MoveHistory
from game.snapshot import GameSnapshot
from rules.reasons import Reason


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

    def __init__(self, board, rule_engine, arbiter, win_condition, config, events=None):
        self._board = board
        self._rule_engine = rule_engine
        self._arbiter = arbiter
        self._win_condition = win_condition
        self._config = config
        self._game_over = False
        self._winner = None
        self._events = events if events is not None else EventBus()
        self._move_history = MoveHistory(config.COLORS)
        self._move_history.subscribe_to(self._events)
        self._score = {color: 0 for color in config.COLORS}
        self._events.publish("game_started", {"colors": tuple(config.COLORS)})

    @property
    def events(self):
        """The engine's EventBus, so outside code (e.g. a server broadcasting
        to clients, or the presentation-stub sound/animation placeholder in
        game.presentation_stub) can subscribe to the same events this engine
        publishes - "game_started", "move_accepted", "arrival",
        "score_changed", "move_log_updated", "game_over" - without polling
        `snapshot()`. Pass one in via the constructor to share a bus across
        several collaborators instead of using this one."""
        return self._events

    @property
    def game_over(self):
        return self._game_over

    @property
    def move_history(self):
        """Accepted moves so far, per color - read-only, in the order each
        color's moves were accepted (there are no turns, so the two lists
        advance independently)."""
        return self._move_history.snapshot()

    @property
    def score(self):
        """Points accumulated so far per color, from captures it made -
        read-only. King captures earn no score (see config.PIECE_VALUES);
        that capture already ends the game via the win condition."""
        return dict(self._score)

    @property
    def winner(self):
        """The color that ended the game in its favour (the other color's
        piece was the one captured), or None while the game is still on."""
        return self._winner

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

    def legal_destinations(self, start):
        """Every cell the piece at `start` could legally move to right now -
        for highlighting once it's selected. Empty once the game is over,
        or (with ALLOW_CONCURRENT_MOVES off) another move is already active
        - the same guards request_move applies before delegating to
        RuleEngine, so every highlighted cell is actually clickable right
        now. Excludes any cell already targeted by another of this piece's
        own color (see DESTINATION_CONTESTED in request_move) for the same
        reason.
        """
        self._apply_events(self._arbiter.resolve())
        if self._game_over:
            return frozenset()
        if not self._config.ALLOW_CONCURRENT_MOVES and self._arbiter.has_active_motion():
            return frozenset()

        piece = self._board.get(*start)
        contested = {move.end for move in self._arbiter.active_moves if color_of(move.piece) == color_of(piece)}
        return frozenset(
            (row, col)
            for row in range(self._board.height)
            for col in range(self._board.width)
            if (row, col) not in contested
            and self._rule_engine.validate_move(self._board, start, (row, col)).is_valid
        )

    def request_move(self, start, end):
        self._apply_events(self._arbiter.resolve())
        if self._game_over:
            return MoveResult(False, Reason.GAME_OVER)
        if self.is_busy(start):
            return MoveResult(False, Reason.BUSY_SOURCE)

        validation = self._rule_engine.validate_move(self._board, start, end)
        if not validation.is_valid:
            return MoveResult(False, validation.reason)

        # ALLOW_CONCURRENT_MOVES defaults True (any number of pieces, either
        # color, may be moving at once - that's the real-time rule). Set
        # False in config to fall back to one-motion-at-a-time instead.
        if not self._config.ALLOW_CONCURRENT_MOVES and self._arbiter.has_active_motion():
            return MoveResult(False, Reason.MOTION_IN_PROGRESS)

        piece = self._board.get(*start)

        # Two of your own pieces racing to the same square is never a real
        # choice - reject the second request outright instead of letting it
        # start and silently fail to land later. An enemy piece is still
        # allowed to target the same cell (that's a legitimate race, not a
        # mistake) - only a same-color contest is rejected here.
        if any(move.end == end and color_of(move.piece) == color_of(piece) for move in self._arbiter.active_moves):
            return MoveResult(False, Reason.DESTINATION_CONTESTED)

        self._arbiter.start_move(piece, start, end)
        self._events.publish("move_accepted", {"piece": piece, "start": start, "end": end})
        return MoveResult(True, Reason.OK)

    def request_jump(self, cell):
        self._apply_events(self._arbiter.resolve())
        if self._game_over:
            return MoveResult(False, Reason.GAME_OVER)
        if not self._board.in_bounds(*cell):
            return MoveResult(False, Reason.OUTSIDE_BOARD)
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
            winner=self._winner,
            move_history=self.move_history,
            score=self.score,
        )

    def render(self, renderer):
        self._apply_events(self._arbiter.resolve())
        return renderer.render(self.snapshot())

    # -- internal helpers -------------------------------------------------

    def _apply_events(self, events):
        """React to arrivals reported by the arbiter. The arbiter reports what
        was captured; the engine owns whether that ends the game (and, for a
        capture, how much it's worth to the capturing color's score).

        Events arrive in chronological order, so the first one that ends the
        game is the true first one - stop right there instead of letting a
        later event in the same batch silently overwrite `_winner`.
        """
        for event in events:
            self._events.publish("arrival", event)
            if event.captured is not None:
                capturer_color = color_of(event.piece)
                self._score[capturer_color] += self._config.PIECE_VALUES[kind_of(event.captured)]
                self._events.publish(
                    "score_changed", {"color": capturer_color, "score": self._score[capturer_color]}
                )
            if self._win_condition.is_game_over(event.captured):
                self._game_over = True
                captured_color = color_of(event.captured)
                self._winner = next(c for c in self._config.COLORS if c != captured_color)
                self._events.publish("game_over", {"winner": self._winner})
                break
