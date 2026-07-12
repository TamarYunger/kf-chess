from dataclasses import dataclass

from rules.movement_strategy import MoveContext


@dataclass(frozen=True)
class MoveValidation:
    """Result of RuleEngine.validate_move.

    `reason` is always present: "ok" for a legal move, otherwise a stable
    machine-readable code ("empty_source", "friendly_destination",
    "illegal_piece_move") that callers and tests can assert on directly,
    instead of inferring legality from board state alone.
    """

    is_valid: bool
    reason: str


class RuleEngine:
    """Answers "is this move legal right now?" - nothing else.

    Read-only with respect to the board: it inspects state and returns a
    MoveValidation, but never mutates Board, starts motions, or knows about
    game-over. Those are GameEngine/RealTimeArbiter responsibilities.
    """

    def __init__(self, rule_registry, config):
        self._registry = rule_registry
        self._empty_cell = config.EMPTY_CELL

    def validate_move(self, board, start, end):
        piece = board.get(*start)
        if piece == self._empty_cell:
            return MoveValidation(False, "empty_source")

        target = board.get(*end)
        if target != self._empty_cell and target[0] == piece[0]:
            return MoveValidation(False, "friendly_destination")

        strategy = self._registry.get(piece[1])
        dr, dc = end[0] - start[0], end[1] - start[1]
        context = MoveContext(
            board=board,
            color=piece[0],
            start=start,
            end=end,
            target_occupied=target != self._empty_cell,
        )
        if not strategy.is_legal(dr, dc, context):
            return MoveValidation(False, "illegal_piece_move")

        return MoveValidation(True, "ok")
