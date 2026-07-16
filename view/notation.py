"""Pure helpers turning a MoveRecord into human-readable chess notation.

Kept separate from GraphicsRenderer (mirrors view/animation.py) so the
formatting is unit-testable without a canvas, and reusable by any future
renderer (e.g. a text move log) without duplicating it.
"""

KIND_NAMES = {"P": "Pawn", "N": "Knight", "B": "Bishop", "R": "Rook", "Q": "Queen", "K": "King"}


def square_name(cell, board_height):
    """(row, col) -> algebraic square name (e.g. "e2"). Rank counts up from
    the bottom row, matching standard chess board orientation, and is
    derived from board_height so any board size works."""
    row, col = cell
    file_letter = chr(ord("a") + col)
    rank = board_height - row
    return f"{file_letter}{rank}"


def move_notation(record, board_height):
    """"Pawn e2-e4", "Knight g1-f3" - the full kind name is used (not the
    single-letter code) so the piece that moved is unambiguous at a
    glance. A kind absent from KIND_NAMES (a custom piece) falls back to
    its own letter as-is, so custom piece kinds still render without a
    KeyError. If the move promoted (`record.promoted_to` is set), an
    "= Queen"-style suffix is appended, mirroring standard chess notation.
    """
    name = KIND_NAMES.get(record.piece[1], record.piece[1])
    start = square_name(record.start, board_height)
    end = square_name(record.end, board_height)
    text = f"{name} {start}-{end}"
    if record.promoted_to is not None:
        promoted_name = KIND_NAMES.get(record.promoted_to, record.promoted_to)
        text += f" = {promoted_name}"
    return text
