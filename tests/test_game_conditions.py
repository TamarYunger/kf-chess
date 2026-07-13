from config import settings
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion


def test_king_capture_ends_game():
    win = KingCaptureWinCondition()
    assert win.is_game_over("bK") is True


def test_non_king_capture_does_not_end_game():
    win = KingCaptureWinCondition()
    assert win.is_game_over("bQ") is False


def test_no_capture_does_not_end_game():
    win = KingCaptureWinCondition()
    assert win.is_game_over(None) is False


def test_pawn_promotes_at_last_rank():
    promotion = LastRankPromotion(settings.PAWN_DIRECTION)
    assert promotion.promote("wP", 0, board_height=8) == "wQ"
    assert promotion.promote("bP", 7, board_height=8) == "bQ"


def test_pawn_does_not_promote_mid_board():
    promotion = LastRankPromotion(settings.PAWN_DIRECTION)
    assert promotion.promote("wP", 3, board_height=8) == "wP"


def test_non_pawn_never_promotes():
    promotion = LastRankPromotion(settings.PAWN_DIRECTION)
    assert promotion.promote("wR", 0, board_height=8) == "wR"


def test_promotion_rank_follows_the_configured_direction():
    # Single source of truth: the promotion rank is derived from the same
    # per-color direction that drives movement. Flip the directions and each
    # color must promote on the opposite (direction-consistent) rank, with no
    # change to LastRankPromotion itself.
    flipped = {"w": 1, "b": -1}  # white now moves down, black up
    promotion = LastRankPromotion(flipped)
    assert promotion.promote("wP", 7, board_height=8) == "wQ"  # white far edge is now the last rank
    assert promotion.promote("wP", 0, board_height=8) == "wP"  # ...and no longer row 0
    assert promotion.promote("bP", 0, board_height=8) == "bQ"  # black far edge is now row 0
