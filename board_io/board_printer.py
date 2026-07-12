from model.piece import kind_letter


class BoardPrinter:
    """Turns a GameSnapshot into printable text - the same text format
    the board's own token grid always produced ("wK"/"." rows joined by
    spaces/newlines), just built from PieceSnapshot data instead of
    talking to Board/GameEngine directly.
    """

    def __init__(self, empty_token="."):
        self._empty_token = empty_token

    def render(self, snapshot):
        grid = [
            [self._empty_token] * snapshot.board_width for _ in range(snapshot.board_height)
        ]
        for piece in snapshot.pieces:
            grid[piece.row][piece.col] = piece.color.value + kind_letter(piece.kind)
        return "\n".join(" ".join(row) for row in grid)