from dataclasses import dataclass


@dataclass(frozen=True)
class MoveResult:
    """Outcome of GameEngine.request_move.

    `reason` is always present and machine-readable: "ok" for an accepted
    command, otherwise a stable code such as "game_over",
    "motion_in_progress", or a RuleEngine reason (e.g. "illegal_piece_move").
    """

    accepted: bool
    reason: str


@dataclass(frozen=True)
class JumpResult:
    accepted: bool
    reason: str
