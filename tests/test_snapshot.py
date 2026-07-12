from board.text_board import TextBoardRepresentation
from model.piece import PieceColor, PieceKind, PieceSnapshot
from board_io.snapshot import GameSnapshot
from board_io.board_printer import BoardPrinter


def test_from_board_carries_pieces_dimensions_and_game_over():
    board = TextBoardRepresentation([["wK", "."], [".", "bK"]])
    snapshot = GameSnapshot.from_board(board, game_over=True)

    assert set(snapshot.pieces) == {
        PieceSnapshot(row=0, col=0, color=PieceColor.WHITE, kind=PieceKind.KING),
        PieceSnapshot(row=1, col=1, color=PieceColor.BLACK, kind=PieceKind.KING),
    }
    assert snapshot.board_width == 2
    assert snapshot.board_height == 2
    assert snapshot.game_over is True
    assert snapshot.selected is None


def test_from_board_carries_selected_when_given():
    board = TextBoardRepresentation([["wK"]])
    snapshot = GameSnapshot.from_board(board, game_over=False, selected=(0, 0))
    assert snapshot.selected == (0, 0)


def test_empty_cells_produce_no_piece_snapshot():
    board = TextBoardRepresentation([["wK", "."]])
    snapshot = GameSnapshot.from_board(board, game_over=False)
    assert len(snapshot.pieces) == 1


def test_snapshot_is_independent_of_later_board_mutation():
    board = TextBoardRepresentation([["wK", "."]])
    snapshot = GameSnapshot.from_board(board, game_over=False)
    board.set(0, 0, ".")
    board.set(0, 1, "wK")

    assert snapshot.pieces == (PieceSnapshot(row=0, col=0, color=PieceColor.WHITE, kind=PieceKind.KING),)


def test_printer_reads_pieces_from_snapshot():
    board = TextBoardRepresentation([["wK", "."], [".", "bK"]])
    snapshot = GameSnapshot.from_board(board, game_over=False)
    text = BoardPrinter().render(snapshot)
    assert text == "wK .\n. bK"


def test_printer_uses_configured_empty_token():
    board = TextBoardRepresentation([["wK", "."]])
    snapshot = GameSnapshot.from_board(board, game_over=False)
    text = BoardPrinter(empty_token="_").render(snapshot)
    assert text == "wK _"
