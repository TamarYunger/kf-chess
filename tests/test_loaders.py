import pytest

from config import settings
from board.board import Board
from board.loaders import load_text_board, BoardParseError
from rules.rule_registry import build_default_registry


@pytest.fixture
def registry():
    return build_default_registry(settings)


def test_load_text_board_builds_a_board(registry):
    board = load_text_board(["wK . bK"], registry, settings)
    assert isinstance(board, Board)
    assert board.get(0, 0) == "wK"
    assert board.is_empty(0, 1)


def test_load_text_board_rejects_unknown_token(registry):
    with pytest.raises(BoardParseError):
        load_text_board(["wX . bK"], registry, settings)


def test_load_text_board_rejects_row_width_mismatch(registry):
    with pytest.raises(BoardParseError):
        load_text_board(["wK . bK", "wK ."], registry, settings)


def test_load_text_board_skips_blank_lines(registry):
    board = load_text_board(["wK . bK", "", "  "], registry, settings)
    assert board.height == 1
