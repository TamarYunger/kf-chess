from dataclasses import dataclass


@dataclass(frozen=True)
class MoveResult:
    """The engine's answer at the public command boundary.

    For an accepted command `reason` is ``Reason.OK``; otherwise it carries a
    stable rejection code (either copied from RuleEngine's MoveValidation or an
    application-level reason such as ``game_over``/``motion_in_progress``). The
    ``Reason`` codes themselves live in ``rules.reasons``.
    """

    is_accepted: bool
    reason: str


@dataclass(frozen=True)
class MoveRecord:
    """One accepted move, kept for the per-color move history.

    Recorded at accept time (`GameEngine.request_move`), not on arrival - it
    logs what was committed, the same moment standard chess notation would.
    """

    piece: str
    start: tuple
    end: tuple
