from config import settings
from board.board import Board
from rules.rule_registry import build_default_registry
from rules.rule_engine import RuleEngine
from rules.game_conditions import (
    KingCaptureWinCondition,
    LastRankPromotion,
    WinCondition,
    PromotionRule,
)
from realtime.real_time_arbiter import RealTimeArbiter
from game.engine import GameEngine
from rules.reasons import Reason
from view.renderer import BoardRenderer


class NeverEndsWinCondition(WinCondition):
    """Fake collaborator used to test engine behaviour in isolation,
    injected instead of monkeypatching KingCaptureWinCondition."""

    def is_game_over(self, captured_piece):
        return False


class NoPromotion(PromotionRule):
    def promote(self, piece, row, board_height):
        return piece


def make_engine(rows, win_condition=None, promotion_rule=None):
    board = Board(rows)
    registry = build_default_registry(settings)
    arbiter = RealTimeArbiter(
        board=board,
        promotion_rule=promotion_rule or LastRankPromotion(settings.PAWN_DIRECTION),
        config=settings,
    )
    engine = GameEngine(
        board=board,
        rule_engine=RuleEngine(rule_registry=registry, config=settings),
        arbiter=arbiter,
        win_condition=win_condition or KingCaptureWinCondition(),
        config=settings,
    )
    return engine, board


def test_request_move_starts_a_legal_move():
    engine, board = make_engine([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    result = engine.request_move((0, 0), (0, 2))

    assert result.is_accepted
    assert result.reason == Reason.OK
    assert board.get(0, 0) == "wR"  # piece stays at the source until it arrives


def test_move_lands_after_move_duration_elapses():
    engine, board = make_engine([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    engine.request_move((0, 0), (0, 2))

    # A two-square move takes two move-durations to arrive.
    engine.wait(2 * settings.MOVE_DURATION)
    assert board.get(0, 2) == "wR"


def test_illegal_move_is_rejected_and_leaves_board_unchanged():
    engine, board = make_engine([["wN", ".", "."], [".", ".", "."], [".", ".", "."]])
    result = engine.request_move((0, 0), (0, 1))  # not a legal knight move

    assert not result.is_accepted
    assert result.reason == Reason.ILLEGAL_PIECE_MOVE
    assert board.get(0, 0) == "wN"


def test_friendly_destination_is_rejected():
    engine, board = make_engine([["wR", "wP", "."]])
    result = engine.request_move((0, 0), (0, 1))

    assert not result.is_accepted
    assert result.reason == Reason.FRIENDLY_DESTINATION


def test_second_move_while_one_is_active_is_rejected():
    rows = [["wR", ".", "."], [".", ".", "."], ["bR", ".", "."]]
    engine, board = make_engine(rows)
    engine.request_move((0, 0), (0, 2))
    result = engine.request_move((2, 0), (2, 2))

    assert not result.is_accepted
    assert result.reason == Reason.MOTION_IN_PROGRESS


def test_king_capture_ends_the_game():
    rows = [["wR", ".", "bK"], [".", ".", "."], [".", ".", "."]]
    engine, board = make_engine(rows)
    engine.request_move((0, 0), (0, 2))
    engine.wait(2 * settings.MOVE_DURATION)

    assert engine.game_over is True


def test_move_after_game_over_is_rejected():
    rows = [["wR", ".", "bK"], ["bR", ".", "."], [".", ".", "."]]
    engine, board = make_engine(rows)
    engine.request_move((0, 0), (0, 2))
    engine.wait(2 * settings.MOVE_DURATION)

    result = engine.request_move((1, 0), (1, 1))
    assert not result.is_accepted
    assert result.reason == Reason.GAME_OVER


def test_injected_win_condition_overrides_default_behaviour():
    rows = [["wR", ".", "bK"], [".", ".", "."], [".", ".", "."]]
    engine, board = make_engine(rows, win_condition=NeverEndsWinCondition())
    engine.request_move((0, 0), (0, 2))
    engine.wait(2 * settings.MOVE_DURATION)

    assert engine.game_over is False


def test_jump_intercepts_a_move_of_the_opposite_color():
    # bP is adjacent so the one-square move (1000) and the jump (1000) land
    # together; otherwise the jump would expire before the move arrives.
    rows = [["wR", "bP", "."], [".", ".", "."], [".", ".", "."]]
    engine, board = make_engine(rows)
    engine.request_move((0, 0), (0, 1))
    engine.request_jump((0, 1))

    engine.wait(settings.JUMP_DURATION)
    assert board.get(0, 1) == "bP"  # move was intercepted, target unchanged
    assert board.is_empty(0, 0)  # the intercepted piece is captured mid-flight


def test_jump_on_empty_cell_is_rejected():
    engine, board = make_engine([[".", ".", "."], [".", ".", "."], [".", ".", "."]])
    result = engine.request_jump((1, 1))
    assert not result.is_accepted
    assert result.reason == Reason.EMPTY_CELL


def test_pawn_promotion_on_arrival():
    # white pawn one step from the last rank (row 0) is promoted to a queen
    rows = [[".", ".", "."], ["wP", ".", "."], [".", ".", "."]]
    engine, board = make_engine(rows)
    engine.request_move((1, 0), (0, 0))
    engine.wait(settings.MOVE_DURATION)

    assert board.get(0, 0) == "wQ"


def test_injected_promotion_rule_overrides_default_behaviour():
    rows = [[".", ".", "."], ["wP", ".", "."], [".", ".", "."]]
    engine, board = make_engine(rows, promotion_rule=NoPromotion())
    engine.request_move((1, 0), (0, 0))
    engine.wait(settings.MOVE_DURATION)

    assert board.get(0, 0) == "wP"


def test_render_returns_current_board_text():
    engine, board = make_engine([["wK", "."], [".", "bK"]])
    text = engine.render(BoardRenderer())
    assert text == "wK .\n. bK"


def test_clock_reflects_arbiter_time():
    engine, board = make_engine([["wR", ".", "."]])
    assert engine.clock == 0
    engine.wait(settings.MOVE_DURATION)
    assert engine.clock == settings.MOVE_DURATION


def test_busy_source_is_rejected_while_that_piece_is_moving():
    engine, board = make_engine([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    engine.request_move((0, 0), (0, 2))  # in flight, source (0,0) busy
    result = engine.request_move((0, 0), (0, 1))
    assert not result.is_accepted
    assert result.reason == Reason.BUSY_SOURCE


def test_can_select_returns_false_after_game_over():
    rows = [["wR", ".", "bK"], ["bR", ".", "."], [".", ".", "."]]
    engine, board = make_engine(rows)
    engine.request_move((0, 0), (0, 2))
    engine.wait(2 * settings.MOVE_DURATION)  # captures bK -> game over
    assert engine.can_select((1, 0)) is False


def test_jump_after_game_over_is_rejected():
    rows = [["wR", ".", "bK"], ["bR", ".", "."], [".", ".", "."]]
    engine, board = make_engine(rows)
    engine.request_move((0, 0), (0, 2))
    engine.wait(2 * settings.MOVE_DURATION)
    result = engine.request_jump((1, 0))
    assert not result.is_accepted
    assert result.reason == Reason.GAME_OVER


def test_jump_on_busy_cell_is_rejected():
    engine, board = make_engine([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    engine.request_move((0, 0), (0, 2))  # (0,0) now busy
    result = engine.request_jump((0, 0))
    assert not result.is_accepted
    assert result.reason == Reason.BUSY_CELL


def test_snapshot_is_readonly_view_of_state():
    engine, board = make_engine([["wK", "."], [".", "bK"]])
    snap = engine.snapshot()
    assert snap.cells == (("wK", "."), (".", "bK"))
    assert snap.width == 2 and snap.height == 2
    assert snap.game_over is False
    assert snap.selected is None
