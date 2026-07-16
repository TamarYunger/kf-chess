from __future__ import annotations

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

    `promoted_to` is filled in later, if at all - only once the piece
    actually arrives and `PromotionRule` transforms it - so it starts as
    None on every record and is patched in place by the engine when the
    matching arrival reports a different final piece.
    """

    piece: str
    start: tuple
    end: tuple
    promoted_to: str | None = None
