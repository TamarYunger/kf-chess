from dataclasses import dataclass
from typing import Optional

from realtime.models import Move, Jump


@dataclass(frozen=True)
class ArrivalEvent:
    """Reported by advance_time when a motion resolves at its destination."""

    piece: str
    cell: tuple
    captured: Optional[str]
    king_captured: bool


class RealTimeArbiter:
    """Owns every active Move/Jump and resolves them as time advances.

    Board mutation happens only here, and only at the moment a motion
    actually resolves (interception check, capture, promotion, king-capture
    detection). GameEngine never touches Board directly for movement; it
    only starts motions and advances time through this class.
    """

    def __init__(self, board, win_condition, promotion_rule, config):
        self._board = board
        self._win_condition = win_condition
        self._promotion_rule = promotion_rule
        self._config = config
        self._active_moves = []
        self._active_jumps = []

    def has_active_motion(self):
        return bool(self._active_moves)

    def is_cell_busy(self, cell):
        return self._is_moving_from(cell) or self._is_jumping_on(cell)

    def start_motion(self, piece, start, end, now):
        distance = max(abs(end[0] - start[0]), abs(end[1] - start[1]))
        arrival = now + self._config.MOVE_DURATION * distance
        self._active_moves.append(Move(piece, start, end, arrival))

    def start_jump(self, piece, cell, now):
        self._active_jumps.append(Jump(piece, cell, now + self._config.JUMP_DURATION))

    def advance_time(self, now):
        remaining = []
        events = []
        for move in self._active_moves:
            if now < move.arrival:
                remaining.append(move)
                continue
            event = self._settle_move(move)
            if event is not None:
                events.append(event)
        self._active_moves = remaining
        self._resolve_jumps(now)
        return events

    # -- internal helpers -------------------------------------------------

    def _is_moving_from(self, cell):
        return any(move.start == cell for move in self._active_moves)

    def _is_jumping_on(self, cell):
        return any(jump.cell == cell for jump in self._active_jumps)

    def _settle_move(self, move):
        empty = self._config.EMPTY_CELL

        if self._is_intercepted(move):
            self._board.set(*move.start, empty)
            return None

        r, c = move.end
        target = self._board.get(r, c)
        if target != empty and target[0] == move.piece[0]:
            self._board.set(*move.start, empty)
            return None

        captured = None if target == empty else target
        king_captured = self._win_condition.is_game_over(captured)

        piece = self._promotion_rule.promote(move.piece, r, self._board.height)
        self._board.set(*move.start, empty)
        self._board.set(r, c, piece)

        return ArrivalEvent(piece=piece, cell=(r, c), captured=captured, king_captured=king_captured)

    def _is_intercepted(self, move):
        r, c = move.end
        return any(
            jump.cell == (r, c) and jump.piece[0] != move.piece[0]
            for jump in self._active_jumps
        )

    def _resolve_jumps(self, now):
        self._active_jumps = [j for j in self._active_jumps if now < j.end_time]
