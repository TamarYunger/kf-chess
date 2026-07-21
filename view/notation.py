"""Pure helpers turning a MoveRecord into human-readable chess notation.

Kept separate from GraphicsRenderer (mirrors view/animation.py) so the
formatting is unit-testable without a canvas, and reusable by any future
renderer (e.g. a text move log) without duplicating it.
"""

from board.piece import kind_of

KIND_NAMES = {"P": "Pawn", "N": "Knight", "B": "Bishop", "R": "Rook", "Q": "Queen", "K": "King"}


def square_name(cell, board_height):
    """(row, col) -> algebraic square name (e.g. "e2"). Rank counts up from
    the bottom row, matching standard chess board orientation, and is
    derived from board_height so any board size works."""
    row, col = cell
    file_letter = chr(ord("a") + col)
    rank = board_height - row
    return f"{file_letter}{rank}"


def parse_square(name, board_height):
    """Inverse of square_name: "e2" -> (row, col). Raises ValueError for
    anything that isn't <letter><digits> (e.g. a malformed or empty
    string) - never IndexError/TypeError - so a caller parsing untrusted
    input (see server/protocol.py) can catch one exception type. Does not
    itself bounds-check the result against the board's width - callers
    that need a guaranteed-in-bounds cell should also check that (see
    Board.in_bounds / RuleEngine.validate_move)."""
    if len(name) < 2 or not name[0].isalpha() or not name[1:].isdigit():
        raise ValueError(f"Malformed square: {name!r}")
    col = ord(name[0].lower()) - ord("a")
    rank = int(name[1:])
    row = board_height - rank
    return row, col


def move_notation(record, board_height):
    """"Pawn e2-e4", "Knight g1-f3" - the full kind name is used (not the
    single-letter code) so the piece that moved is unambiguous at a
    glance. A kind absent from KIND_NAMES (a custom piece) falls back to
    its own letter as-is, so custom piece kinds still render without a
    KeyError. If the move promoted (`record.promoted_to` is set), an
    "= Queen"-style suffix is appended, mirroring standard chess notation.
    """
    name = KIND_NAMES.get(kind_of(record.piece), kind_of(record.piece))
    start = square_name(record.start, board_height)
    end = square_name(record.end, board_height)
    text = f"{name} {start}-{end}"
    if record.promoted_to is not None:
        promoted_name = KIND_NAMES.get(record.promoted_to, record.promoted_to)
        text += f" = {promoted_name}"
    return text
