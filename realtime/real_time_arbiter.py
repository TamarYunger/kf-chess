from __future__ import annotations

from dataclasses import dataclass

from realtime.models import Move, Jump, Arrival


@dataclass(frozen=True)
class ArrivalEvent:
    """What the arbiter reports back when a moving piece arrives.

    The arbiter mutates the board itself, but it does not decide the win
    condition - it only reports which token (if any) was captured, so the
    GameEngine can apply its injected WinCondition. `piece` is the token as
    placed at the destination (already promoted if a promotion applied).
    """

    piece: str
    destination: tuple
    captured: str | None


class RealTimeArbiter:
    """Owns all real-time motion: active Moves/Jumps, the simulated clock,
    arrival timing, and arrival/interception resolution.

    Kept separate from GameEngine so the real-time model can be tested in
    isolation, and so Board keeps representing only logical occupancy while
    in-flight motion state lives here. Time never advances from the wall
    clock: it only moves when `advance_time` is called with a delta.

    Promotion happens on arrival, so the promotion rule is injected here
    (into the layer that owns arrival), not into the engine.
    """

    def __init__(self, board, promotion_rule, config):
        self._board = board
        self._promotion_rule = promotion_rule
        self._config = config
        self._clock = 0
        self._active_moves = []
        self._active_jumps = []
        self._recent_arrivals = {}

    @property
    def clock(self):
        return self._clock

    @property
    def active_moves(self):
        return tuple(self._active_moves)

    @property
    def active_jumps(self):
        return tuple(self._active_jumps)

    @property
    def recent_arrivals(self):
        """Landings recorded for cells that still hold the piece that
        landed there - self-pruning, so a piece that moves away or gets
        captured makes its own stale entry unreadable on the next access,
        with no explicit cleanup pass needed."""
        return tuple(
            arrival for cell, arrival in self._recent_arrivals.items()
            if self._board.get(*cell) == arrival.piece
        )

    def has_active_motion(self):
        return bool(self._active_moves)

    def is_moving_from(self, cell):
        return any(move.start == cell for move in self._active_moves)

    def is_jumping_on(self, cell):
        return any(jump.cell == cell for jump in self._active_jumps)

    def start_move(self, piece, start, end):
        self._active_moves.append(Move(piece, start, end, self._arrival_clock(start, end)))

    def start_jump(self, piece, cell):
        self._active_jumps.append(Jump(piece, cell, self._clock + self._config.JUMP_DURATION))

    def advance_time(self, dt):
        """Advance simulated time and resolve whatever became due."""
        self._clock += dt
        return self.resolve()

    def resolve(self):
        """Settle any moves whose arrival time has been reached, without
        advancing the clock. Returns the arrival events produced."""
        remaining = []
        events = []
        for move in self._active_moves:
            if self._clock < move.arrival:
                remaining.append(move)
                continue
            event = self._settle_move(move)
            if event is not None:
                events.append(event)
        self._active_moves = remaining
        self._resolve_jumps()
        return events

    # -- internal helpers -------------------------------------------------

    def _arrival_clock(self, start, end):
        """A move takes MOVE_DURATION per square travelled; distance is the
        number of squares on a straight/diagonal path (Chebyshev metric)."""
        distance = max(abs(end[0] - start[0]), abs(end[1] - start[1]))
        return self._clock + distance * self._config.MOVE_DURATION

    def _settle_move(self, move):
        if self._is_intercepted(move):
            # The moving piece is captured mid-flight by the jumping piece,
            # so it is removed from its source rather than surviving there.
            self._board.set(*move.start, self._config.EMPTY_CELL)
            return None

        r, c = move.end
        target = self._board.get(r, c)
        if target != self._config.EMPTY_CELL and target[0] == move.piece[0]:
            return None

        captured = None if target == self._config.EMPTY_CELL else target
        piece = self._promotion_rule.promote(move.piece, r, self._board.height)
        # The piece stays visible at its source while in flight; it leaves the
        # source only now, on arrival. (A same-color piece blocking the target
        # returns above, so the mover survives in place in that case.)
        self._board.set(*move.start, self._config.EMPTY_CELL)
        self._board.set(r, c, piece)
        self._record_arrival(piece, (r, c), kind="move")
        return ArrivalEvent(piece=piece, destination=(r, c), captured=captured)

    def _is_intercepted(self, move):
        r, c = move.end
        return any(
            jump.cell == (r, c) and jump.piece[0] != move.piece[0]
            for jump in self._active_jumps
        )

    def _resolve_jumps(self):
        remaining = []
        for jump in self._active_jumps:
            if self._clock < jump.end_time:
                remaining.append(jump)
            else:
                self._record_arrival(jump.piece, jump.cell, kind="jump")
        self._active_jumps = remaining

    def _record_arrival(self, piece, cell, kind):
        self._recent_arrivals[cell] = Arrival(piece=piece, cell=cell, at=self._clock, kind=kind)
