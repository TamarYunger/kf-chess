from rules.movement_strategy import MovementStrategy


def _shape_delta(dr, dc):
    return abs(dr), abs(dc)


def path_is_clear(board, start, end):
    """Shared sliding-piece helper: True if every square strictly between
    start and end is empty. Used by Rook, Bishop and Queen so the check is
    written once (DRY) instead of duplicated per piece.
    """
    sr, sc = start
    er, ec = end
    dr = (er > sr) - (er < sr)
    dc = (ec > sc) - (ec < sc)
    r, c = sr + dr, sc + dc
    while (r, c) != (er, ec):
        if not board.is_empty(r, c):
            return False
        r += dr
        c += dc
    return True


class KingMovement(MovementStrategy):
    def is_legal(self, dr, dc, context):
        r, c = _shape_delta(dr, dc)
        return max(r, c) == 1


class RookMovement(MovementStrategy):
    def is_legal(self, dr, dc, context):
        if not ((dr == 0) != (dc == 0)):
            return False
        return path_is_clear(context.board, context.start, context.end)


class BishopMovement(MovementStrategy):
    def is_legal(self, dr, dc, context):
        r, c = _shape_delta(dr, dc)
        if not (r == c and r != 0):
            return False
        return path_is_clear(context.board, context.start, context.end)


class QueenMovement(MovementStrategy):
    def is_legal(self, dr, dc, context):
        r, c = _shape_delta(dr, dc)
        straight = (dr == 0) != (dc == 0)
        diagonal = r == c and r != 0
        if not (straight or diagonal):
            return False
        return path_is_clear(context.board, context.start, context.end)


class KnightMovement(MovementStrategy):
    def is_legal(self, dr, dc, context):
        r, c = _shape_delta(dr, dc)
        return sorted([r, c]) == [1, 2]


class PawnMovement(MovementStrategy):
    """Pawn movement rule.

    The per-color advance direction is injected (so variants can flip it),
    while the rank a pawn may double-step from is derived from the board
    height rather than hardcoded - so a single instance works for any
    board size.
    """

    def __init__(self, directions):
        self._directions = directions
    
    def _home_row(self, direction, board):
        """The rank a pawn may double-step from: the far edge it faces away
        from. Derived from board height, so any board size works."""
        return 0 if direction > 0 else board.height - 1

    def is_legal(self, dr, dc, context):
        direction = self._directions[context.color]
        start_row = self._home_row(direction, context.board)
        sr, _sc = context.start

        if dc == 0:
            if dr == direction and not context.target_occupied:
                return True
            if sr == start_row and dr == 2 * direction and not context.target_occupied:
                mid_row = sr + direction
                return context.board.is_empty(mid_row, context.start[1])
            return False

        if abs(dc) == 1 and dr == direction and context.target_occupied:
            return True

        return False
