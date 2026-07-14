from dataclasses import dataclass


@dataclass(frozen=True)
class Move:
    """A piece in flight between two cells.

    Owned by RealTimeArbiter, not Board: the board only stores logical
    occupancy, while an in-flight Move lives outside it until it arrives.
    """

    piece: str
    start: tuple
    end: tuple
    arrival: int


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
