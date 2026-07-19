from __future__ import annotations

from dataclasses import dataclass

from board.piece import color_of
from realtime.models import Move, Jump, Arrival


def _straight_line_path(start, end):
    """Cells strictly after `start` up to and including `end`, walked one
    step at a time in a straight line or diagonal. Empty for any other
    shape (e.g. a knight's L) - those pieces have no intermediate squares
    to collide along, so they are never subject to path-crossing checks.
    """
    sr, sc = start
    er, ec = end
    dr = (er > sr) - (er < sr)
    dc = (ec > sc) - (ec < sc)
    if dr != 0 and dc != 0 and abs(er - sr) != abs(ec - sc):
        return ()
    r, c = sr + dr, sc + dc
    cells = []
    while (r, c) != (er, ec):
        cells.append((r, c))
        r += dr
        c += dc
    cells.append((er, ec))
    return tuple(cells)


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

    def is_resting(self, cell):
        """Whether `cell` is still within its post-landing cooldown - a
        move-landing rests for LONG_REST_DURATION, a jump-landing for
        SHORT_REST_DURATION. Reuses the same self-pruning lookup as
        `recent_arrivals` (a cell whose occupant has since changed is never
        "resting")."""
        arrival = self._recent_arrivals.get(cell)
        if arrival is None or self._board.get(*cell) != arrival.piece:
            return False
        duration = (
            self._config.SHORT_REST_DURATION if arrival.kind == "jump"
            else self._config.LONG_REST_DURATION
        )
        return self._clock < arrival.at + duration

    def start_move(self, piece, start, end):
        """Registers a move, first checking whether its path crosses a
        same-color move already active. If it does, and this new move would
        reach the shared cell later, it is shortened to stop one cell short
        of the crossing instead of continuing to `end`.

        This only ever shortens the *new* move being registered here - an
        already-active move that turns out to be the later one at some
        future crossing is not (yet) retroactively shortened by this step.
        """
        start_time = self._clock
        original_path = _straight_line_path(start, end)
        path = self._shorten_for_crossings(piece, start_time, original_path) if original_path else ()

        if path:
            actual_end = path[-1]
            arrival = start_time + len(path) * self._config.MOVE_DURATION
        elif original_path:
            # Straight-line move truncated all the way back to its own
            # start - blocked before its first step, so it never actually
            # goes anywhere.
            actual_end, arrival = start, start_time
        else:
            # Not a straight line (e.g. a knight) - has no path to begin
            # with, so it is never affected by path-crossing shortening.
            actual_end, arrival = end, self._arrival_clock(start, end)

        self._active_moves.append(Move(piece, start, actual_end, arrival, path))

    def start_jump(self, piece, cell):
        self._active_jumps.append(Jump(piece, cell, self._clock + self._config.JUMP_DURATION))

    def advance_time(self, dt):
        """Advance simulated time and resolve whatever became due."""
        self._clock += dt
        return self.resolve()

    def resolve(self):
        """Settle any moves whose arrival time has been reached, without
        advancing the clock. Returns the arrival events produced.

        Due moves are settled in arrival order, not registration order: a
        single `resolve` call can find several moves due at once (e.g. after
        a large `advance_time`), and whichever actually arrives earlier must
        be written to the board first, regardless of which `start_move` call
        registered it first.
        """
        due, remaining = [], []
        for move in self._active_moves:
            (due if self._clock >= move.arrival else remaining).append(move)
        due.sort(key=lambda move: move.arrival)

        events = []
        for move in due:
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

    def _shorten_for_crossings(self, piece, start_time, path):
        """Truncates `path` right before the earliest cell where it would
        cross a same-color active move that reaches that shared cell no
        later than this new mover does - that mover keeps going, this one
        stops one cell short instead. Only moves with a non-empty `path` of
        their own (i.e. also straight-line) can be crossed against.
        """
        color = color_of(piece)
        duration = self._config.MOVE_DURATION
        cutoff = None
        for other in self._active_moves:
            if color_of(other.piece) != color or not other.path:
                continue
            other_start_time = other.arrival - len(other.path) * duration
            for i, cell in enumerate(path):
                if cell not in other.path:
                    continue
                j = other.path.index(cell)
                my_time = start_time + (i + 1) * duration
                other_time = other_start_time + (j + 1) * duration
                if my_time > other_time and (cutoff is None or i < cutoff):
                    cutoff = i
        return path if cutoff is None else path[:cutoff]

    def _settle_move(self, move):
        if self._is_intercepted(move):
            # The moving piece is captured mid-flight by the jumping piece,
            # so it is removed from its source rather than surviving there.
            self._board.set(*move.start, self._config.EMPTY_CELL)
            return None

        r, c = move.end
        target = self._board.get(r, c)
        if target != self._config.EMPTY_CELL and color_of(target) == color_of(move.piece):
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
            jump.cell == (r, c) and color_of(jump.piece) != color_of(move.piece)
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
