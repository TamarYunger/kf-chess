from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING

from board.board import Board
from board.piece import Piece

if TYPE_CHECKING:
    from rules.rule_registry import PieceRuleRegistry


class BoardParseError(Exception):
    """Raised when external board input is malformed for its format."""


# The standard chess starting position, in load_text_board's own text
# format - shared so every composition root that needs a default board
# (main_gui.py's offline session, server/shard.py's per-room engine) uses
# the exact same literal instead of each keeping its own copy that could
# silently drift out of sync with the others.
STANDARD_BOARD_TEXT = [
    "bR bN bB bQ bK bB bN bR",
    "bP bP bP bP bP bP bP bP",
    ". . . . . . . .",
    ". . . . . . . .",
    ". . . . . . . .",
    ". . . . . . . .",
    "wP wP wP wP wP wP wP wP",
    "wR wN wB wQ wK wB wN wR",
]


def _valid_text_tokens(registry: PieceRuleRegistry, colors: tuple[str, ...], empty_token: str) -> set[str]:
    """Valid tokens are derived from whatever piece kinds are registered,
    rather than a hardcoded string - so registering a custom piece kind
    automatically makes its token accepted here too.
    """
    tokens = {empty_token}
    for color in colors:
        for kind in registry.registered_kinds():
            tokens.add(color + kind)
    return tokens


def load_text_board(rows: list[str], registry: PieceRuleRegistry, config: ModuleType) -> Board:
    """Adapter that converts text board rows into the internal Board.

    This is the text-format seam. To support another input format (e.g. a
    binary board) add a sibling loader that likewise returns a Board; no
    game-logic module needs to change, only main.py picks which loader to use.

    Validates that the board is rectangular and that every token is one the
    registry recognises, raising BoardParseError otherwise.
    """
    valid_tokens = _valid_text_tokens(registry, config.COLORS, config.EMPTY_CELL)
    grid = []
    width = None
    for line in rows:
        tokens = line.split()
        if not tokens:
            continue
        if width is None:
            width = len(tokens)
        elif len(tokens) != width:
            raise BoardParseError("ROW_WIDTH_MISMATCH")
        for token in tokens:
            if token not in valid_tokens:
                raise BoardParseError("UNKNOWN_TOKEN")
        grid.append([token if token == config.EMPTY_CELL else Piece.from_token(token) for token in tokens])
    return Board(grid, empty_token=config.EMPTY_CELL)
