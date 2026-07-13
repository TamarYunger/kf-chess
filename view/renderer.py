class BoardRenderer:
    """Turns a read-only GameSnapshot into printable text.

    Lives in the view layer and consumes only a snapshot (never a live Board),
    so rendering format can change - or the engine can be tested - without
    either one depending on the other.
    """

    def render(self, snapshot):
        return "\n".join(" ".join(row) for row in snapshot.cells)
