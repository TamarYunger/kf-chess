from board.board import Board
from view.snapshot import GameSnapshot
from view.renderer import BoardRenderer


def test_from_board_captures_cells_and_dimensions():
    board = Board([["wK", ".", "bK"], [".", "wR", "."]])
    snap = GameSnapshot.from_board(board, game_over=False)

    assert snap.cells == (("wK", ".", "bK"), (".", "wR", "."))
    assert snap.width == 3
    assert snap.height == 2
    assert snap.game_over is False
    assert snap.selected is None


def test_from_board_carries_game_over_and_selected():
    board = Board([["wK", "."]])
    snap = GameSnapshot.from_board(board, game_over=True, selected=(0, 0))
    assert snap.game_over is True
    assert snap.selected == (0, 0)


def test_snapshot_is_isolated_from_later_board_mutation():
    board = Board([["wK", "."], [".", "."]])
    snap = GameSnapshot.from_board(board, game_over=False)
    board.set(0, 0, ".")
    # The snapshot is a frozen copy taken at creation time.
    assert snap.cells[0][0] == "wK"


def test_renderer_produces_legacy_text_from_snapshot():
    board = Board([["wK", "."], [".", "bK"]])
    snap = GameSnapshot.from_board(board, game_over=False)
    assert BoardRenderer().render(snap) == "wK .\n. bK"
