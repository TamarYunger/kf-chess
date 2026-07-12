from dataclasses import dataclass
from typing import Optional, Tuple

from model.piece import PieceSnapshot, PieceColor, PieceKind


@dataclass(frozen=True)
class GameSnapshot:
    """Read-only view of engine state, consumed by BoardPrinter.

    Carries a flat list of PieceSnapshot rather than the board's token
    grid, so BoardPrinter describes *where each piece is* instead of
    reading board internals directly. `selected` stays None from
    GameEngine today (selection is Controller state, and print-board
    output never shows it), but is included since it's part of the same
    read-only state a renderer would need.
    """

    pieces: Tuple[PieceSnapshot, ...]
    board_width: int
    board_height: int
    game_over: bool
    selected: Optional[tuple] = None

    @classmethod
    def from_board(cls, board, game_over, selected=None):
        pieces = []
        for row in range(board.height):
            for col in range(board.width):
                if board.is_empty(row, col):
                    continue
                token = board.get(row, col)
                pieces.append(
                    PieceSnapshot(
                        row=row,
                        col=col,
                        color=PieceColor(token[0]),
                        kind=PieceKind(token[1]),
                    )
                )
        return cls(
            pieces=tuple(pieces),
            board_width=board.width,
            board_height=board.height,
            game_over=game_over,
            selected=selected,
        )