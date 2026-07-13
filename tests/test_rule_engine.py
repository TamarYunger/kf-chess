from config import settings
from board.board import Board
from rules.rule_registry import build_default_registry
from rules.rule_engine import RuleEngine
from rules.reasons import Reason


def make_engine(rows):
    board = Board(rows)
    registry = build_default_registry(settings)
    return RuleEngine(rule_registry=registry, config=settings), board


def test_legal_move_is_valid():
    engine, board = make_engine([["wR", ".", "."]])
    result = engine.validate_move(board, (0, 0), (0, 2))
    assert result.is_valid
    assert result.reason == Reason.OK


def test_empty_source_is_rejected():
    engine, board = make_engine([[".", ".", "."]])
    result = engine.validate_move(board, (0, 0), (0, 2))
    assert not result.is_valid
    assert result.reason == Reason.EMPTY_SOURCE


def test_friendly_destination_is_rejected():
    engine, board = make_engine([["wR", "wP", "."]])
    result = engine.validate_move(board, (0, 0), (0, 1))
    assert not result.is_valid
    assert result.reason == Reason.FRIENDLY_DESTINATION


def test_illegal_piece_move_is_rejected():
    engine, board = make_engine([["wN", ".", "."], [".", ".", "."], [".", ".", "."]])
    result = engine.validate_move(board, (0, 0), (0, 1))  # not an L-shape
    assert not result.is_valid
    assert result.reason == Reason.ILLEGAL_PIECE_MOVE


def test_out_of_bounds_destination_is_rejected():
    engine, board = make_engine([["wR", ".", "."]])
    result = engine.validate_move(board, (0, 0), (0, 5))
    assert not result.is_valid
    assert result.reason == Reason.OUTSIDE_BOARD


def test_enemy_at_destination_is_a_legal_capture_target():
    engine, board = make_engine([["wR", ".", "bR"]])
    result = engine.validate_move(board, (0, 0), (0, 2))
    assert result.is_valid


def test_validate_does_not_mutate_board():
    engine, board = make_engine([["wR", ".", "bR"]])
    engine.validate_move(board, (0, 0), (0, 2))
    assert board.get(0, 0) == "wR"
    assert board.get(0, 2) == "bR"
