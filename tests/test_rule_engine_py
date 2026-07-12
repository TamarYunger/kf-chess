from config import settings
from board.text_board import TextBoardRepresentation
from rules.rule_registry import build_default_registry
from rules.rule_engine import RuleEngine


def make_rule_engine():
    return RuleEngine(build_default_registry(settings), settings)


def test_valid_move_returns_ok():
    board = TextBoardRepresentation([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    result = make_rule_engine().validate_move(board, (0, 0), (0, 2))
    assert result.is_valid is True
    assert result.reason == "ok"


def test_empty_source_is_rejected():
    board = TextBoardRepresentation([[".", ".", "."], [".", ".", "."], [".", ".", "."]])
    result = make_rule_engine().validate_move(board, (0, 0), (0, 2))
    assert result.is_valid is False
    assert result.reason == "empty_source"


def test_friendly_destination_is_rejected():
    board = TextBoardRepresentation([["wR", ".", "wN"], [".", ".", "."], [".", ".", "."]])
    result = make_rule_engine().validate_move(board, (0, 0), (0, 2))
    assert result.is_valid is False
    assert result.reason == "friendly_destination"


def test_illegal_piece_move_is_rejected():
    board = TextBoardRepresentation([["wN", ".", "."], [".", ".", "."], [".", ".", "."]])
    result = make_rule_engine().validate_move(board, (0, 0), (0, 1))
    assert result.is_valid is False
    assert result.reason == "illegal_piece_move"


def test_enemy_destination_is_a_legal_capture():
    board = TextBoardRepresentation([["wR", ".", "bN"], [".", ".", "."], [".", ".", "."]])
    result = make_rule_engine().validate_move(board, (0, 0), (0, 2))
    assert result.is_valid is True


def test_does_not_mutate_board():
    board = TextBoardRepresentation([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    make_rule_engine().validate_move(board, (0, 0), (0, 2))
    assert board.get(0, 0) == "wR"
    assert board.is_empty(0, 2)
