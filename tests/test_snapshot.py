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


def test_from_board_defaults_motion_fields_to_empty():
    board = Board([["wK", "."]])
    snap = GameSnapshot.from_board(board, game_over=False)
    assert snap.moves == ()
    assert snap.jumps == ()
    assert snap.recent_arrivals == ()
    assert snap.clock == 0


def test_from_board_carries_motion_fields_when_passed():
    board = Board([["wK", "."]])
    moves = ("fake-move",)
    jumps = ("fake-jump",)
    arrivals = ("fake-arrival",)
    snap = GameSnapshot.from_board(
        board, game_over=False,
        moves=moves, jumps=jumps, recent_arrivals=arrivals, clock=42,
    )
    assert snap.moves == moves
    assert snap.jumps == jumps
    assert snap.recent_arrivals == arrivals
    assert snap.clock == 42


def test_from_board_defaults_winner_to_none():
    board = Board([["wK", "."]])
    snap = GameSnapshot.from_board(board, game_over=False)
    assert snap.winner is None


def test_from_board_carries_winner_when_passed():
    board = Board([["wK", "."]])
    snap = GameSnapshot.from_board(board, game_over=True, winner="w")
    assert snap.winner == "w"


def test_from_board_defaults_move_history_to_empty_dict():
    board = Board([["wK", "."]])
    snap = GameSnapshot.from_board(board, game_over=False)
    assert snap.move_history == {}


def test_from_board_carries_move_history_when_passed():
    board = Board([["wK", "."]])
    history = {"w": ("fake-record",), "b": ()}
    snap = GameSnapshot.from_board(board, game_over=False, move_history=history)
    assert snap.move_history == history
