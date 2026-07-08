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
    promotion = LastRankPromotion()
    assert promotion.promote("wP", 0, board_height=8) == "wQ"
    assert promotion.promote("bP", 7, board_height=8) == "bQ"


def test_pawn_does_not_promote_mid_board():
    promotion = LastRankPromotion()
    assert promotion.promote("wP", 3, board_height=8) == "wP"


def test_non_pawn_never_promotes():
    promotion = LastRankPromotion()
    assert promotion.promote("wR", 0, board_height=8) == "wR"
