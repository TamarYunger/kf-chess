from dataclasses import dataclass
from enum import Enum


class PieceColor(Enum):
    WHITE = "w"
    BLACK = "b"


class PieceKind(Enum):
    KING = "K"
    QUEEN = "Q"
    ROOK = "R"
    BISHOP = "B"
    KNIGHT = "N"
    PAWN = "P"


def kind_letter(kind):
    """The single-character board-token letter for a piece kind."""
    return kind.value


@dataclass(frozen=True)
class PieceSnapshot:
    """Read-only view of one piece's position and identity, for rendering.

    Deliberately separate from the board's internal token strings ("wK") -
    rendering code should describe *what piece is where*, not know that the
    board happens to store that as a two-character string.
    """

    row: int
    col: int
    color: PieceColor
    kind: PieceKind