import types

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


def make_engine(rows, win_condition=None, promotion_rule=None, config=None):
    config = config or settings
    board = Board(rows)
    registry = build_default_registry(config)
    arbiter = RealTimeArbiter(
        board=board,
        promotion_rule=promotion_rule or LastRankPromotion(config.PAWN_DIRECTION),
        config=config,
    )
    engine = GameEngine(
        board=board,
        rule_engine=RuleEngine(rule_registry=registry, config=config),
        arbiter=arbiter,
        win_condition=win_condition or KingCaptureWinCondition(),
        config=config,
    )
    return engine, board


def config_with(**overrides):
    base = {k: v for k, v in vars(settings).items() if not k.startswith("_")}
    base.update(overrides)
    return types.SimpleNamespace(**base)


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


def test_second_move_while_one_is_active_is_rejected_when_concurrent_moves_disabled():
    rows = [["wR", ".", "."], [".", ".", "."], ["bR", ".", "."]]
    engine, board = make_engine(rows, config=config_with(ALLOW_CONCURRENT_MOVES=False))
    engine.request_move((0, 0), (0, 2))
    result = engine.request_move((2, 0), (2, 2))

    assert not result.is_accepted
    assert result.reason == Reason.MOTION_IN_PROGRESS


def test_concurrent_moves_allowed_by_default_for_different_colors():
    # The real KungFu Chess rule: no turns, either color may be moving at once.
    rows = [["wR", ".", "."], [".", ".", "."], ["bR", ".", "."]]
    engine, board = make_engine(rows)
    result_white = engine.request_move((0, 0), (0, 2))
    result_black = engine.request_move((2, 0), (2, 2))

    assert result_white.is_accepted
    assert result_black.is_accepted
    engine.wait(2 * settings.MOVE_DURATION)
    assert board.get(0, 2) == "wR"
    assert board.get(2, 2) == "bR"


def test_concurrent_moves_allowed_by_default_for_same_color():
    # Nothing limits how many of one side's own pieces can move at once
    # either - only a piece's own busy/resting state limits it.
    rows = [["wR", ".", "."], [".", ".", "."], ["wR", ".", "."]]
    engine, board = make_engine(rows)
    result_first = engine.request_move((0, 0), (0, 2))
    result_second = engine.request_move((2, 0), (2, 2))

    assert result_first.is_accepted
    assert result_second.is_accepted
    engine.wait(2 * settings.MOVE_DURATION)
    assert board.get(0, 2) == "wR"
    assert board.get(2, 2) == "wR"


def test_second_same_color_move_to_a_contested_destination_is_rejected():
    # Two white rooks converging on the same empty square is never a real
    # choice - the second request is rejected outright, not left to silently
    # fail to land once it arrives.
    rows = [["wR", ".", "."], [".", ".", "."], [".", ".", "wR"]]
    engine, board = make_engine(rows)
    result_first = engine.request_move((0, 0), (0, 2))
    result_second = engine.request_move((2, 2), (0, 2))

    assert result_first.is_accepted
    assert not result_second.is_accepted
    assert result_second.reason == Reason.DESTINATION_CONTESTED


def test_enemy_move_to_a_contested_destination_is_still_allowed():
    # An enemy racing to the same square is a legitimate contest, not a
    # mistake - only a same-color destination clash is rejected.
    rows = [["wR", ".", "."], [".", ".", "."], [".", ".", "bR"]]
    engine, board = make_engine(rows)
    result_white = engine.request_move((0, 0), (0, 2))
    result_black = engine.request_move((2, 2), (0, 2))

    assert result_white.is_accepted
    assert result_black.is_accepted


def test_king_capture_ends_the_game():
    rows = [["wR", ".", "bK"], [".", ".", "."], [".", ".", "."]]
    engine, board = make_engine(rows)
    engine.request_move((0, 0), (0, 2))
    engine.wait(2 * settings.MOVE_DURATION)

    assert engine.game_over is True


def test_winner_is_none_before_game_over():
    rows = [["wR", ".", "bK"], [".", ".", "."], [".", ".", "."]]
    engine, board = make_engine(rows)
    assert engine.winner is None


def test_winner_is_the_color_whose_piece_survived():
    rows = [["wR", ".", "bK"], [".", ".", "."], [".", ".", "."]]
    engine, board = make_engine(rows)
    engine.request_move((0, 0), (0, 2))  # white captures the black king
    engine.wait(2 * settings.MOVE_DURATION)

    assert engine.winner == "w"


def test_winner_is_black_when_white_king_is_captured():
    rows = [["wK", ".", "bR"], [".", ".", "."], [".", ".", "."]]
    engine, board = make_engine(rows)
    engine.request_move((0, 2), (0, 0))  # black captures the white king
    engine.wait(2 * settings.MOVE_DURATION)

    assert engine.game_over is True
    assert engine.winner == "b"


def test_winner_reflects_the_chronologically_first_king_capture():
    # wR captures bK after 2 squares (arrives first); bR captures wK after 3
    # squares (arrives later) - both settle in the same `wait`. Even though
    # bR's move was requested first, wR's capture happens first in time and
    # must decide the winner; the later capture must not overwrite it.
    rows = [["wK", ".", ".", "bR"], ["bK", ".", "wR", "."]]
    engine, board = make_engine(rows)
    engine.request_move((0, 3), (0, 0))  # bR -> captures wK, 3 squares
    engine.request_move((1, 2), (1, 0))  # wR -> captures bK, 2 squares
    engine.wait(3 * settings.MOVE_DURATION)

    assert engine.winner == "w"


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


def test_can_select_is_false_while_a_landed_piece_is_resting():
    engine, board = make_engine([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    engine.request_move((0, 0), (0, 2))
    engine.wait(2 * settings.MOVE_DURATION)  # arrives at (0,2)
    assert engine.can_select((0, 2)) is False


def test_can_select_becomes_true_again_once_long_rest_elapses():
    engine, board = make_engine([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    engine.request_move((0, 0), (0, 2))
    engine.wait(2 * settings.MOVE_DURATION)
    engine.wait(settings.LONG_REST_DURATION)
    assert engine.can_select((0, 2)) is True


def test_request_move_from_a_resting_source_is_rejected():
    rows = [["wR", ".", "."], [".", ".", "."], [".", ".", "."]]
    engine, board = make_engine(rows)
    engine.request_move((0, 0), (0, 1))
    engine.wait(settings.MOVE_DURATION)  # (0,1) now resting

    result = engine.request_move((0, 1), (0, 2))
    assert not result.is_accepted
    assert result.reason == Reason.BUSY_SOURCE


def test_request_jump_on_a_resting_cell_is_rejected():
    rows = [["wR", ".", "."], [".", ".", "."], [".", ".", "."]]
    engine, board = make_engine(rows)
    engine.request_move((0, 0), (0, 1))
    engine.wait(settings.MOVE_DURATION)  # (0,1) now resting

    result = engine.request_jump((0, 1))
    assert not result.is_accepted
    assert result.reason == Reason.BUSY_CELL


def test_snapshot_is_readonly_view_of_state():
    engine, board = make_engine([["wK", "."], [".", "bK"]])
    snap = engine.snapshot()
    assert snap.cells == (("wK", "."), (".", "bK"))
    assert snap.width == 2 and snap.height == 2
    assert snap.game_over is False
    assert snap.selected is None


def test_move_history_starts_empty_for_every_configured_color():
    engine, board = make_engine([["wR", ".", "."]])
    assert engine.move_history == {"w": (), "b": ()}


def test_accepted_move_is_appended_to_its_color_history():
    engine, board = make_engine([["wR", ".", "."], [".", ".", "."], ["bR", ".", "."]])
    engine.request_move((0, 0), (0, 2))
    engine.request_move((2, 0), (2, 1))

    history = engine.move_history
    assert [(r.piece, r.start, r.end) for r in history["w"]] == [("wR", (0, 0), (0, 2))]
    assert [(r.piece, r.start, r.end) for r in history["b"]] == [("bR", (2, 0), (2, 1))]


def test_rejected_move_is_not_recorded():
    engine, board = make_engine([["wN", ".", "."], [".", ".", "."], [".", ".", "."]])
    engine.request_move((0, 0), (0, 1))  # illegal knight move
    assert engine.move_history["w"] == ()


def test_snapshot_carries_move_history():
    engine, board = make_engine([["wR", ".", "."]])
    engine.request_move((0, 0), (0, 2))
    snap = engine.snapshot()
    assert [(r.piece, r.start, r.end) for r in snap.move_history["w"]] == [("wR", (0, 0), (0, 2))]
