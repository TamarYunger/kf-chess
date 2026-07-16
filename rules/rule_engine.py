from dataclasses import dataclass

from rules.reasons import Reason
from rules.movement_strategy import MoveContext


@dataclass(frozen=True)
class MoveValidation:
    """Result of a read-only legality check for a requested move.

    `reason` is always present: ``Reason.OK`` for a legal move, or a stable
    rule-level code otherwise.
    """

    is_valid: bool
    reason: str


class RuleEngine:
    """Validates whether a move is legal against the current board (Validation
    Service). Read-only: it inspects board state and returns a MoveValidation
    but never mutates the board, starts motion, or knows about game-over.

    Stateless with respect to the board - the board is passed per call - so it
    can be reused and tested in isolation. The piece-rule registry and config
    are injected.
    """

    def __init__(self, rule_registry, config):
        self._registry = rule_registry
        self._config = config

    def validate_move(self, board, start, end):
        if not board.in_bounds(*start) or not board.in_bounds(*end):
            return MoveValidation(False, Reason.OUTSIDE_BOARD)
        if board.is_empty(*start):
            return MoveValidation(False, Reason.EMPTY_SOURCE)

        piece = board.get(*start)
        target = board.get(*end)
        if target != self._config.EMPTY_CELL and target[0] == piece[0]:
            return MoveValidation(False, Reason.FRIENDLY_DESTINATION)

        strategy = self._registry.get(piece[1])
        dr, dc = end[0] - start[0], end[1] - start[1]
        context = MoveContext(
            board=board,
            color=piece[0],
            start=start,
            end=end,
            target_occupied=not board.is_empty(*end),
        )
        if not strategy.is_legal(dr, dc, context):
            return MoveValidation(False, Reason.ILLEGAL_PIECE_MOVE)

        return MoveValidation(True, Reason.OK)
