from board.board import Board


class BoardParseError(Exception):
    """Raised when external board input is malformed for its format."""


def _valid_text_tokens(registry, colors, empty_token):
    """Valid tokens are derived from whatever piece kinds are registered,
    rather than a hardcoded string - so registering a custom piece kind
    automatically makes its token accepted here too.
    """
    tokens = {empty_token}
    for color in colors:
        for kind in registry.registered_kinds():
            tokens.add(color + kind)
    return tokens


def load_text_board(rows, registry, config):
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
        grid.append(tokens)
    return Board(grid, empty_token=config.EMPTY_CELL)
