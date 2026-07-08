from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class MoveContext:
    """Everything a movement strategy needs to judge a move, bundled up.

    Keeping this as one immutable object (instead of passing five loose
    parameters around) is what lets new piece kinds be registered without
    changing every call site.
    """

    board: object  # BoardRepresentation
    color: str
    start: tuple
    end: tuple
    target_occupied: bool


class MovementStrategy(ABC):
    """A single piece kind's movement rule (Strategy pattern).

    New piece kinds - including custom, non-standard ones - are supported
    simply by implementing this interface and registering an instance with
    a PieceRuleRegistry. No engine or parser code needs to change.
    """

    @abstractmethod
    def is_legal(self, dr: int, dc: int, context: MoveContext) -> bool:
        ...
