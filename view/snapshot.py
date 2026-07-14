from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameSnapshot:
    """Read-only view of the game state handed to the renderer.

    The renderer never receives the live Board or Piece objects - only this
    immutable snapshot - so the view layer cannot accidentally mutate the
    model. `cells` is the logical board (a tuple of tuples of tokens).

    `selected` is part of the shape (a graphical renderer highlights it) but is
    populated only by whoever owns selection state; the engine leaves it None,
    since `print board` never shows selection.

    `moves`, `jumps`, `recent_arrivals` and `clock` carry the arbiter's
    real-time motion state (all read-only, mirroring `cells`) so a graphical
    renderer can animate in-flight pieces; the text renderer ignores them.
    They default to empty/zero so every existing caller that only cares
    about board contents is unaffected.
    """

    cells: tuple
    width: int
    height: int
    game_over: bool
    selected: tuple | None = None
    moves: tuple = ()
    jumps: tuple = ()
    recent_arrivals: tuple = ()
    clock: int = 0

    @classmethod
    def from_board(cls, board, game_over, selected=None, moves=(), jumps=(),
                    recent_arrivals=(), clock=0):
        cells = tuple(tuple(row) for row in board.snapshot())
        return cls(
            cells=cells,
            width=board.width,
            height=board.height,
            game_over=game_over,
            selected=selected,
            moves=moves,
            jumps=jumps,
            recent_arrivals=recent_arrivals,
            clock=clock,
        )
