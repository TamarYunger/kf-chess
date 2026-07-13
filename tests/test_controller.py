from config import settings
from board.board import Board
from rules.rule_registry import build_default_registry
from rules.rule_engine import RuleEngine
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion
from realtime.real_time_arbiter import RealTimeArbiter
from game.engine import GameEngine
from game.board_mapper import BoardMapper
from game.controller import Controller


def make_controller(rows):
    board = Board(rows)
    registry = build_default_registry(settings)
    engine = GameEngine(
        board=board,
        rule_engine=RuleEngine(rule_registry=registry, config=settings),
        arbiter=RealTimeArbiter(board=board, promotion_rule=LastRankPromotion(settings.PAWN_DIRECTION), config=settings),
        win_condition=KingCaptureWinCondition(),
        config=settings,
    )
    controller = Controller(engine=engine, board_mapper=BoardMapper(board, settings.CELL_SIZE))
    return controller, engine, board


def cell_to_pixel(row, col):
    return col * settings.CELL_SIZE, row * settings.CELL_SIZE


def test_first_click_selects_own_piece():
    controller, engine, board = make_controller([["wK", "."], [".", "."]])
    controller.click(*cell_to_pixel(0, 0))
    assert controller.selected == (0, 0)


def test_first_click_on_empty_cell_selects_nothing():
    controller, engine, board = make_controller([["wK", "."], [".", "."]])
    controller.click(*cell_to_pixel(1, 1))
    assert controller.selected is None


def test_click_outside_board_with_no_selection_is_ignored():
    controller, engine, board = make_controller([["wK", "."], [".", "."]])
    controller.click(-10, -10)
    assert controller.selected is None


def test_click_outside_board_keeps_existing_selection():
    # Faithful to current behaviour: an outside-board click is a no-op and does
    # NOT cancel an existing selection.
    controller, engine, board = make_controller([["wK", "."], [".", "."]])
    controller.click(*cell_to_pixel(0, 0))
    controller.click(-10, -10)
    assert controller.selected == (0, 0)


def test_second_click_starts_move_and_clears_selection():
    controller, engine, board = make_controller([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    controller.click(*cell_to_pixel(0, 0))
    controller.click(*cell_to_pixel(0, 2))
    assert controller.selected is None
    assert board.get(0, 0) == "wR"  # still at source until it arrives


def test_illegal_second_click_clears_selection():
    # Clicking an illegal destination cancels the selection (the target was
    # not a legal move), leaving the piece in place.
    controller, engine, board = make_controller([["wN", ".", "."], [".", ".", "."], [".", ".", "."]])
    controller.click(*cell_to_pixel(0, 0))
    controller.click(*cell_to_pixel(0, 1))  # not a legal knight move
    assert controller.selected is None
    assert board.get(0, 0) == "wN"


def test_clicking_another_friendly_piece_reselects():
    controller, engine, board = make_controller([["wR", ".", "wK"], [".", ".", "."]])
    controller.click(*cell_to_pixel(0, 0))
    controller.click(*cell_to_pixel(0, 2))  # friendly -> reselect
    assert controller.selected == (0, 2)


def test_jump_clears_selection():
    controller, engine, board = make_controller([["wK", "bR"], [".", "."]])
    controller.click(*cell_to_pixel(0, 0))
    controller.jump(*cell_to_pixel(0, 0))
    assert controller.selected is None


def test_jump_outside_board_is_ignored():
    controller, engine, board = make_controller([["wK", "."], [".", "."]])
    controller.jump(-10, -10)  # out of bounds: no crash, no selection
    assert controller.selected is None
