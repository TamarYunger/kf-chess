class UnknownPieceKindError(Exception):
    pass


class PieceRuleRegistry:
    """Maps a piece-kind letter to its MovementStrategy.

    This is the extension point required for custom games: registering a
    new kind (e.g. "C" for a custom "Champion" piece) with its own
    MovementStrategy is all that's needed to support it - no engine or
    parser code has to change, and the piece automatically becomes a
    valid board token (see game.parser).
    """

    def __init__(self):
        self._strategies = {}

    def register(self, kind, strategy):
        self._strategies[kind] = strategy

    def get(self, kind):
        try:
            return self._strategies[kind]
        except KeyError:
            raise UnknownPieceKindError(kind) from None

    def registered_kinds(self):
        return tuple(self._strategies.keys())


def build_default_registry(config):
    """Factory for the standard chess piece set.

    Kept separate from PieceRuleRegistry itself so alternate registries
    (e.g. for a custom variant) can be assembled the same way without
    subclassing anything.
    """
    from rules.piece_rules import (
        KingMovement,
        QueenMovement,
        RookMovement,
        BishopMovement,
        KnightMovement,
        PawnMovement,
    )

    registry = PieceRuleRegistry()
    registry.register("K", KingMovement())
    registry.register("Q", QueenMovement())
    registry.register("R", RookMovement())
    registry.register("B", BishopMovement())
    registry.register("N", KnightMovement())
    registry.register("P", PawnMovement(config.PAWN_DIRECTION, config.PAWN_START_ROW))
    return registry
