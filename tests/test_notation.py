from game.models import MoveRecord
from view.notation import square_name, move_notation


def test_square_name_uses_algebraic_files_and_ranks_from_the_bottom():
    assert square_name((0, 0), board_height=8) == "a8"
    assert square_name((7, 0), board_height=8) == "a1"
    assert square_name((6, 4), board_height=8) == "e2"


def test_square_name_derives_ranks_from_any_board_height():
    assert square_name((0, 0), board_height=3) == "a3"
    assert square_name((2, 0), board_height=3) == "a1"


def test_pawn_move_omits_the_kind_letter():
    record = MoveRecord(piece="wP", start=(6, 4), end=(4, 4))
    assert move_notation(record, board_height=8) == "e2-e4"


def test_non_pawn_move_includes_the_kind_letter():
    record = MoveRecord(piece="wN", start=(7, 6), end=(5, 5))
    assert move_notation(record, board_height=8) == "Ng1-f3"


def test_custom_piece_kind_letter_is_used_as_is():
    record = MoveRecord(piece="wC", start=(0, 0), end=(0, 1))
    assert move_notation(record, board_height=8) == "Ca8-b8"
