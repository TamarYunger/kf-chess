import pytest

from config import settings
from board.text_board import TextBoardRepresentation
from rules.rule_registry import build_default_registry
from rules.rule_engine import RuleEngine
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion, WinCondition, PromotionRule
from game.engine import GameEngine
from game.controller import Controller
from game.board_mapper import BoardMapper
from realtime.real_time_arbiter import RealTimeArbiter
from board_io.board_printer import BoardPrinter


class NeverEndsWinCondition(WinCondition):
    """Fake collaborator used to test engine behaviour in isolation,
    injected instead of monkeypatching KingCaptureWinCondition."""

    def is_game_over(self, captured_piece):
        return False


class NoPromotion(PromotionRule):
    def promote(self, piece, row, board_height):
        return piece


def make_engine(rows, win_condition=None, promotion_rule=None):
    """Wires up the full click-to-arrival stack (Controller, GameEngine,
    RuleEngine, RealTimeArbiter) the same way main.py does, so these tests
    keep exercising the real command path end to end."""
    board = TextBoardRepresentation(rows)
    registry = build_default_registry(settings)
    real_time_arbiter = RealTimeArbiter(
        board=board,
        win_condition=win_condition or KingCaptureWinCondition(),
        promotion_rule=promotion_rule or LastRankPromotion(),
        config=settings,
    )
    engine = GameEngine(
        board=board,
        rule_engine=RuleEngine(registry, settings),
        real_time_arbiter=real_time_arbiter,
        config=settings,
    )
    controller = Controller(engine, BoardMapper(board, settings.CELL_SIZE))
    return controller, engine, board


def cell_to_pixel(row, col):
    return col * settings.CELL_SIZE, row * settings.CELL_SIZE


def test_click_selects_own_piece():
    controller, engine, board = make_engine([["wK", "."], [".", "."]])
    x, y = cell_to_pixel(0, 0)
    controller.click(x, y)
    assert controller.selected == (0, 0)


def test_click_out_of_bounds_is_ignored():
    controller, engine, board = make_engine([["wK", "."], [".", "."]])
    controller.click(-1, -1)
    assert controller.selected is None


def test_selecting_then_moving_starts_a_move():
    controller, engine, board = make_engine([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    controller.click(*cell_to_pixel(0, 0))
    controller.click(*cell_to_pixel(0, 2))

    assert controller.selected is None
    # the piece stays visible at its origin until the move actually arrives
    assert board.get(0, 0) == "wR"
    assert board.is_empty(0, 2)


def test_move_duration_scales_with_distance():
    controller, engine, board = make_engine([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    controller.click(*cell_to_pixel(0, 0))
    controller.click(*cell_to_pixel(0, 2))  # 2 cells away

    engine.wait(settings.MOVE_DURATION)  # only enough time for 1 cell
    assert board.get(0, 0) == "wR"  # not arrived yet

    engine.wait(settings.MOVE_DURATION)  # total = 2 cells worth of time
    assert board.get(0, 2) == "wR"
    assert board.is_empty(0, 0)


def test_illegal_move_keeps_selection_and_piece_in_place():
    controller, engine, board = make_engine([["wN", ".", "."], [".", ".", "."], [".", ".", "."]])
    controller.click(*cell_to_pixel(0, 0))
    controller.click(*cell_to_pixel(0, 1))  # not a legal knight move

    assert controller.selected == (0, 0)
    assert board.get(0, 0) == "wN"


def test_king_capture_ends_the_game():
    rows = [["wR", ".", "bK"], [".", ".", "."], [".", ".", "."]]
    controller, engine, board = make_engine(rows)
    controller.click(*cell_to_pixel(0, 0))
    controller.click(*cell_to_pixel(0, 2))
    engine.wait(settings.MOVE_DURATION * 2)  # 2 cells of distance

    assert engine.game_over is True


def test_injected_win_condition_overrides_default_behaviour():
    rows = [["wR", ".", "bK"], [".", ".", "."], [".", ".", "."]]
    controller, engine, board = make_engine(rows, win_condition=NeverEndsWinCondition())
    controller.click(*cell_to_pixel(0, 0))
    controller.click(*cell_to_pixel(0, 2))
    engine.wait(settings.MOVE_DURATION * 2)

    assert engine.game_over is False


def test_jump_intercepts_a_move_of_the_opposite_color():
    rows = [["wR", ".", "bP"], [".", ".", "."], [".", ".", "."]]
    controller, engine, board = make_engine(rows)
    controller.click(*cell_to_pixel(0, 0))
    controller.click(*cell_to_pixel(0, 2))  # move arrives after 2 cells of time
    controller.jump(*cell_to_pixel(0, 2))

    engine.wait(settings.MOVE_DURATION * 2)
    assert board.get(0, 2) == "bP"  # move was intercepted, target unchanged
    assert board.is_empty(0, 0)  # the intercepted piece is destroyed, not returned


def test_pawn_promotion_on_arrival():
    # white pawn one step from the last rank (row 0)
    rows = [[".", ".", "."], ["wP", ".", "."], [".", ".", "."]]
    controller, engine, board = make_engine(rows)

    controller.click(*cell_to_pixel(1, 0))
    controller.click(*cell_to_pixel(0, 0))
    engine.wait(settings.MOVE_DURATION)

    assert board.get(0, 0) == "wQ"


def test_injected_promotion_rule_overrides_default_behaviour():
    rows = [[".", ".", "."], ["wP", ".", "."], [".", ".", "."]]
    controller, engine, board = make_engine(rows, promotion_rule=NoPromotion())

    controller.click(*cell_to_pixel(1, 0))
    controller.click(*cell_to_pixel(0, 0))
    engine.wait(settings.MOVE_DURATION)

    assert board.get(0, 0) == "wP"


def test_render_returns_current_board_text():
    controller, engine, board = make_engine([["wK", "."], [".", "bK"]])
    text = engine.render(BoardPrinter())
    assert text == "wK .\n. bK"

def test_second_move_is_blocked_while_one_is_in_flight():
    rows = [["wR", ".", "."], [".", ".", "."], ["bR", ".", "."]]
    controller, engine, board = make_engine(rows)

    controller.click(*cell_to_pixel(0, 0))
    controller.click(*cell_to_pixel(0, 2))  # white move starts, still in flight

    controller.click(*cell_to_pixel(2, 0))
    controller.click(*cell_to_pixel(2, 2))  # blocked: a move is already active

    engine.wait(settings.MOVE_DURATION * 2)
    assert board.get(0, 2) == "wR"
    assert board.get(2, 0) == "bR"  # never moved

def test_enemy_arrives_after_landing_captures_normally():
    rows = [[".", ".", ".", "."], ["wK", ".", ".", "bR"], [".", ".", ".", "."]]
    controller, engine, board = make_engine(rows)

    controller.jump(50, 150)    # wK jumps defensively
    engine.wait(1000)           # the jump expires before anything else happens

    controller.click(350, 150)  # select bR
    controller.click(50, 150)   # move bR onto wK's square - 3 cells away

    engine.wait(3000)
    text = engine.render(BoardPrinter())
    assert text == ". . . .\nbR . . .\n. . . ."


def test_cannot_jump_while_moving():
    controller, engine, board = make_engine([["wR", ".", "."]])
    controller.click(50, 50)
    controller.click(250, 50)   # wR starts a 2-cell move (still mid-flight)

    engine.wait(500)             # move not yet arrived
    controller.jump(50, 50)      # blocked: the source square is busy

    engine.wait(1500)
    text = engine.render(BoardPrinter())
    assert text == ". . wR"


def test_airborne_capture_only_enemy():
    rows = [[".", ".", "."], ["wK", "wR", "."], [".", ".", "."]]
    controller, engine, board = make_engine(rows)

    controller.jump(50, 150)     # wK jumps
    controller.click(150, 150)   # select wR
    controller.click(50, 150)    # try to land on own airborne king - blocked

    engine.wait(1000)
    text = engine.render(BoardPrinter())
    assert text == ". . .\nwK wR .\n. . ."

def test_jump_lands_same_square():
    rows = [[".", ".", "."], [".", "wK", "."], [".", ".", "."]]
    controller, engine, board = make_engine(rows)

    controller.jump(150, 150)   # wK jumps on its own square
    engine.wait(1000)

    text = engine.render(BoardPrinter())
    assert text == ". . .\n. wK .\n. . ."


def test_airborne_piece_captures_arriving_enemy():
    rows = [[".", ".", "."], ["wK", "bR", "."], [".", ".", "."]]
    controller, engine, board = make_engine(rows)

    controller.jump(50, 150)     # wK jumps, guarding its square
    controller.click(150, 150)   # select bR
    controller.click(50, 150)    # bR tries to move onto wK - 1 cell away

    engine.wait(1000)
    text = engine.render(BoardPrinter())
    assert text == ". . .\nwK . .\n. . ."


def test_jump_too_late_does_not_save_piece():
    rows = [[".", ".", "."], ["wK", "bR", "."], [".", ".", "."]]
    controller, engine, board = make_engine(rows)

    controller.click(150, 150)   # select bR
    controller.click(50, 150)    # bR moves onto wK, 1 cell away

    engine.wait(1000)            # move arrives and captures wK - game over
    controller.jump(50, 150)     # too late: jump is ignored once game is over

    text = engine.render(BoardPrinter())
    assert text == ". . .\nbR . .\n. . ."
