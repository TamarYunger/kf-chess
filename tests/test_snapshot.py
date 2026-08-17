from board.board import Board
from board.piece import Piece
from game.models import MoveRecord
from game.snapshot import GameSnapshot
from client.view.renderer import BoardRenderer
from realtime.models import Arrival, Jump, Move


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


def test_from_board_defaults_legal_destinations_to_empty_frozenset():
    board = Board([["wK", "."]])
    snap = GameSnapshot.from_board(board, game_over=False)
    assert snap.legal_destinations == frozenset()


def test_from_board_carries_legal_destinations_when_passed():
    board = Board([["wK", "."]])
    snap = GameSnapshot.from_board(board, game_over=False, legal_destinations=frozenset({(0, 1)}))
    assert snap.legal_destinations == frozenset({(0, 1)})


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
    # Piece objects (real board.piece.Piece, not fake placeholders): the
    # snapshot's own job is converting these back to plain token strings,
    # the one boundary a Piece is documented not to cross - see
    # game/snapshot.py's _stringify_motion.
    board = Board([["wK", "."]])
    moves = (Move(piece=Piece.from_token("wR"), start=(0, 0), end=(0, 1), arrival=1000),)
    jumps = (Jump(piece=Piece.from_token("bP"), cell=(1, 0), end_time=500),)
    arrivals = (Arrival(piece=Piece.from_token("wQ"), cell=(0, 1), at=1000, kind="move"),)
    snap = GameSnapshot.from_board(
        board, game_over=False,
        moves=moves, jumps=jumps, recent_arrivals=arrivals, clock=42,
    )
    assert len(snap.moves) == 1
    assert snap.moves[0].piece == "wR" and snap.moves[0].start == (0, 0) and snap.moves[0].end == (0, 1)
    assert len(snap.jumps) == 1
    assert snap.jumps[0].piece == "bP" and snap.jumps[0].cell == (1, 0)
    assert len(snap.recent_arrivals) == 1
    assert snap.recent_arrivals[0].piece == "wQ" and snap.recent_arrivals[0].cell == (0, 1)
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
    history = {"w": (MoveRecord(piece=Piece.from_token("wQ"), start=(0, 0), end=(0, 1)),), "b": ()}
    snap = GameSnapshot.from_board(board, game_over=False, move_history=history)
    assert snap.move_history["w"][0].piece == "wQ"
    assert snap.move_history["w"][0].start == (0, 0)
    assert snap.move_history["b"] == ()


def test_from_board_defaults_rejection_reason_to_none():
    board = Board([["wK", "."]])
    snap = GameSnapshot.from_board(board, game_over=False)
    assert snap.rejection_reason is None


def test_from_board_carries_rejection_reason_when_passed():
    board = Board([["wK", "."]])
    snap = GameSnapshot.from_board(board, game_over=False, rejection_reason="destination_contested")
    assert snap.rejection_reason == "destination_contested"


def test_from_board_defaults_score_to_empty_dict():
    board = Board([["wK", "."]])
    snap = GameSnapshot.from_board(board, game_over=False)
    assert snap.score == {}


def test_from_board_carries_score_when_passed():
    board = Board([["wK", "."]])
    score = {"w": 9, "b": 3}
    snap = GameSnapshot.from_board(board, game_over=False, score=score)
    assert snap.score == score
