from dataclasses import dataclass


@dataclass
class Move:
    piece: str
    start: tuple
    end: tuple
    arrival: int


@dataclass
class Jump:
    piece: str
    cell: tuple
    end_time: int
