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
