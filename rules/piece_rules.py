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
    """Pawn behaviour depends on per-color direction/start-row config,
    which is injected rather than hardcoded, so board layouts or custom
    variants can change it without editing this class.
    """

    def __init__(self, directions, start_rows):
        self._directions = directions
        self._start_rows = start_rows

    def is_legal(self, dr, dc, context):
        direction = self._directions[context.color]
        start_row = self._start_rows[context.color]
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
