from abc import ABC, abstractmethod


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
        return captured_piece is not None and captured_piece[1] == "K"


class PromotionRule(ABC):
    """Decides whether/how a piece transforms after moving (Strategy pattern)."""

    @abstractmethod
    def promote(self, piece, row, board_height):
        """Return the (possibly unchanged) piece token after promotion rules apply."""


class LastRankPromotion(PromotionRule):
    def __init__(self, promotable_kind="P", promote_to="Q"):
        self._promotable_kind = promotable_kind
        self._promote_to = promote_to

    def promote(self, piece, row, board_height):
        color, kind = piece[0], piece[1]
        if kind != self._promotable_kind:
            return piece
        last_rank = 0 if color == "w" else board_height - 1
        if row == last_rank:
            return color + self._promote_to
        return piece
