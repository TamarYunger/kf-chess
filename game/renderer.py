class BoardRenderer:
    """Turns a BoardRepresentation snapshot into printable text.

    Kept separate from GameEngine so rendering format can change (or the
    engine can be tested) without either one depending on the other.
    """

    def render(self, board):
        return "\n".join(" ".join(row) for row in board.snapshot())
