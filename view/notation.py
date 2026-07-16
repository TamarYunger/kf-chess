"""Pure helpers turning a MoveRecord into human-readable chess notation.

Kept separate from GraphicsRenderer (mirrors view/animation.py) so the
formatting is unit-testable without a canvas, and reusable by any future
renderer (e.g. a text move log) without duplicating it.
"""


def square_name(cell, board_height):
    """(row, col) -> algebraic square name (e.g. "e2"). Rank counts up from
    the bottom row, matching standard chess board orientation, and is
    derived from board_height so any board size works."""
    row, col = cell
    file_letter = chr(ord("a") + col)
    rank = board_height - row
    return f"{file_letter}{rank}"


def move_notation(record, board_height):
    """"e2-e4" for a pawn, "Ng1-f3" for any other kind - the piece-kind
    letter is whatever the rule registry uses for that kind (see
    PieceRuleRegistry), so custom piece kinds are rendered automatically.
    Pawns ("P") omit the letter, matching standard chess notation.
    """
    kind = record.piece[1]
    prefix = "" if kind == "P" else kind
    start = square_name(record.start, board_height)
    end = square_name(record.end, board_height)
    return f"{prefix}{start}-{end}"
