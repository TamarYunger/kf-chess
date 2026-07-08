from abc import ABC, abstractmethod


class BoardRepresentation(ABC):
    """Abstraction over how board state is stored.

    Game logic (rules, engine) only ever talks to this interface.
    A concrete implementation may store cells as text tokens, packed
    bitboards, or anything else, as long as it honors this contract.
    That means a future binary/bitboard representation can be dropped in
    without touching a single line of game logic.
    """

    @property
    @abstractmethod
    def width(self):
        ...

    @property
    @abstractmethod
    def height(self):
        ...

    @abstractmethod
    def in_bounds(self, row, col):
        ...

    @abstractmethod
    def get(self, row, col):
        """Return the token/value occupying a cell."""

    @abstractmethod
    def set(self, row, col, value):
        """Place a token/value on a cell."""

    @abstractmethod
    def is_empty(self, row, col):
        ...

    @abstractmethod
    def snapshot(self):
        """Return a read-only, text-token view of the board for rendering.

        Even a binary implementation must be able to produce this view,
        so rendering code never needs to know the internal storage format.
        """
