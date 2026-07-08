from board.text_board import TextBoardRepresentation


def make_board():
    return TextBoardRepresentation([["wK", ".", "bK"], [".", ".", "."]])


def test_dimensions():
    board = make_board()
    assert board.width == 3
    assert board.height == 2


def test_get_set():
    board = make_board()
    board.set(1, 1, "wQ")
    assert board.get(1, 1) == "wQ"


def test_is_empty():
    board = make_board()
    assert board.is_empty(0, 1) is True
    assert board.is_empty(0, 0) is False


def test_in_bounds():
    board = make_board()
    assert board.in_bounds(0, 0) is True
    assert board.in_bounds(2, 0) is False
    assert board.in_bounds(0, -1) is False


def test_snapshot_is_a_copy():
    board = make_board()
    snap = board.snapshot()
    snap[0][0] = "bQ"
    assert board.get(0, 0) == "wK"


def test_empty_board_dimensions():
    board = TextBoardRepresentation([])
    assert board.width == 0
    assert board.height == 0
