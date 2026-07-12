from config import settings
from board.text_board import TextBoardRepresentation
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion
from realtime.real_time_arbiter import RealTimeArbiter


def make_arbiter(rows):
    board = TextBoardRepresentation(rows)
    arbiter = RealTimeArbiter(
        board=board,
        win_condition=KingCaptureWinCondition(),
        promotion_rule=LastRankPromotion(),
        config=settings,
    )
    return arbiter, board


def test_has_active_motion_false_before_any_motion_starts():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    assert arbiter.has_active_motion() is False


def test_start_motion_marks_source_cell_busy():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    arbiter.start_motion("wR", (0, 0), (0, 2), now=0)
    assert arbiter.has_active_motion() is True
    assert arbiter.is_cell_busy((0, 0)) is True
    assert arbiter.is_cell_busy((0, 2)) is False


def test_one_cell_move_does_not_arrive_before_full_duration():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    arbiter.start_motion("wR", (0, 0), (0, 1), now=0)
    arbiter.advance_time(settings.MOVE_DURATION - 1)
    assert board.get(0, 0) == "wR"
    assert board.is_empty(0, 1)


def test_one_cell_move_arrives_after_full_duration():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    arbiter.start_motion("wR", (0, 0), (0, 1), now=0)
    arbiter.advance_time(settings.MOVE_DURATION)
    assert board.is_empty(0, 0)
    assert board.get(0, 1) == "wR"
    assert arbiter.has_active_motion() is False


def test_arrival_event_reports_capture_and_king_capture():
    arbiter, board = make_arbiter([["wR", ".", "bK"]])
    arbiter.start_motion("wR", (0, 0), (0, 2), now=0)
    events = arbiter.advance_time(settings.MOVE_DURATION * 2)
    assert len(events) == 1
    assert events[0].captured == "bK"
    assert events[0].king_captured is True


def test_non_king_capture_does_not_report_king_captured():
    arbiter, board = make_arbiter([["wR", ".", "bN"]])
    arbiter.start_motion("wR", (0, 0), (0, 2), now=0)
    events = arbiter.advance_time(settings.MOVE_DURATION * 2)
    assert events[0].captured == "bN"
    assert events[0].king_captured is False


def test_jump_intercepts_enemy_move_and_reports_no_event():
    arbiter, board = make_arbiter([["wR", ".", "bP"]])
    arbiter.start_motion("wR", (0, 0), (0, 2), now=0)
    arbiter.start_jump("bP", (0, 2), now=0)

    events = arbiter.advance_time(settings.MOVE_DURATION * 2)
    assert events == []
    assert board.get(0, 2) == "bP"  # target unchanged
    assert board.is_empty(0, 0)  # intercepted piece is destroyed, not returned


def test_jump_expires_after_its_own_duration():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    arbiter.start_jump("wR", (0, 0), now=0)
    arbiter.advance_time(settings.JUMP_DURATION)
    assert arbiter.is_cell_busy((0, 0)) is False


def test_promotion_rule_applies_on_arrival():
    arbiter, board = make_arbiter([[".", ".", "."], ["wP", ".", "."]])
    arbiter.start_motion("wP", (1, 0), (0, 0), now=0)
    arbiter.advance_time(settings.MOVE_DURATION)
    assert board.get(0, 0) == "wQ"
