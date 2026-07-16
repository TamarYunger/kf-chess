from dataclasses import dataclass


@dataclass(frozen=True)
class Move:
    """A piece in flight between two cells.

    Owned by RealTimeArbiter, not Board: the board only stores logical
    occupancy, while an in-flight Move lives outside it until it arrives.

    `path` is the sequence of cells strictly after `start` up to and
    including `end`, walked in a straight line/diagonal - used only to
    detect a same-color path crossing with another active move. It is empty
    for any non-straight-line move (e.g. a knight's L-shape): those have no
    intermediate squares, so they can never cross another move's path.
    """

    piece: str
    start: tuple
    end: tuple
    arrival: int
    path: tuple = ()


@dataclass(frozen=True)
class Jump:
    """A piece that is airborne on a cell until end_time.

    While airborne it can intercept an enemy Move arriving on the same cell.
    """

    piece: str
    cell: tuple
    end_time: int


@dataclass(frozen=True)
class Arrival:
    """The most recent landing (move or jump) recorded for a cell.

    Kept only so the animation layer can compute "time since landing" for
    the post-motion rest chain - the one piece of motion state that cannot
    be derived from anything else. `kind` picks which rest chain applies
    ("move" piece settle into long_rest, "jump" pieces into short_rest).
    """

    piece: str
    cell: tuple
    at: int
    kind: str
