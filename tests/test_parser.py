import pytest

from config import settings
from game.parser import parse_input, build_board, BoardParseError
from rules.rule_registry import build_default_registry


@pytest.fixture
def registry():
    return build_default_registry(settings)


def test_parse_input_splits_sections():
    lines = ["Board:", "wK . bK", "Commands:", "print", "wait 5"]
    board_lines, commands = parse_input(lines)
    assert board_lines == ["wK . bK"]
    assert commands == ["print", "wait 5"]


def test_build_board_valid(registry):
    board = build_board(["wK . bK"], registry, settings)
    assert board.get(0, 0) == "wK"
    assert board.is_empty(0, 1)


def test_build_board_rejects_unknown_token(registry):
    with pytest.raises(BoardParseError):
        build_board(["wX . bK"], registry, settings)


def test_build_board_rejects_row_width_mismatch(registry):
    with pytest.raises(BoardParseError):
        build_board(["wK . bK", "wK ."], registry, settings)


def test_build_board_skips_blank_lines(registry):
    board = build_board(["wK . bK", "", "  "], registry, settings)
    assert board.height == 1
