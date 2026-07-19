from abc import ABC, abstractmethod

from board.piece import color_of, kind_of, make_piece


class WinCondition(ABC):
    """Decides whether a capture ends the game (Strategy pattern).

    Swappable so custom variants can define a different win condition
    (e.g. capture-the-flag, last-piece-standing) without touching the
    engine.
    """

    @abstractmethod
    def is_game_over(self, captured_piece):
        """captured_piece is the token that was just captured, or None."""


class KingCaptureWinCondition(WinCondition):
    def is_game_over(self, captured_piece):
        return captured_piece is not None and kind_of(captured_piece) == "K"


class PromotionRule(ABC):
    """Decides whether/how a piece transforms after moving (Strategy pattern)."""

    @abstractmethod
    def promote(self, piece, row, board_height):
        """Return the (possibly unchanged) piece token after promotion rules apply."""


class LastRankPromotion(PromotionRule):
    """Promotes a pawn that reaches the far edge in its direction of travel.

    The promotion rank is derived from the same per-color advance direction
    that drives movement (`config.PAWN_DIRECTION`), so there is a single source
    of truth for "which way each color goes": a color moving up (direction < 0)
    promotes on row 0, a color moving down promotes on the last row. Flipping
    the configured direction therefore moves promotion along with movement,
    instead of the two silently disagreeing.
    """

    def __init__(self, directions, promotable_kind="P", promote_to="Q"):
        self._directions = directions
        self._promotable_kind = promotable_kind
        self._promote_to = promote_to

    def promote(self, piece, row, board_height):
        color, kind = color_of(piece), kind_of(piece)
        if kind != self._promotable_kind:
            return piece
        last_rank = 0 if self._directions[color] < 0 else board_height - 1
        if row == last_rank:
            return make_piece(color, self._promote_to)
        return piece
