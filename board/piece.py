"""Accessors for the board's piece-token convention (e.g. "wK" = white king).

`Color` and `Kind` are Enums - fixed states, per the "rich domain model"
standard: never slice a raw string in business logic when a strongly
typed property will do (`piece.color == Color.BLACK` instead of
`token[0] == "b"`).

`Kind` covers the six standard chess kinds, but is not a hard gate:
`rules.rule_registry.PieceRuleRegistry` lets a caller register a
brand-new kind letter (e.g. "C" for a custom "Champion" piece) with no
change to this module, RuleEngine, or the parser - `_to_kind` falls back
to the raw letter for anything `Kind` doesn't recognise, so that
documented extension point keeps working instead of raising.

`Piece` is a real, immutable dataclass - not a string wrapper - but
compares/hashes equal to its plain 2-character token ("wK") on purpose:
every existing caller that compares a piece to a literal string, uses one
as a dict key, or needs one JSON-serializable (see game/snapshot.py,
which converts Piece back to a plain string at the GameSnapshot boundary,
since that's what the wire protocol and the view layer both expect)
keeps working unchanged.
"""

from dataclasses import dataclass
from enum import Enum


class Color(str, Enum):
    WHITE = "w"
    BLACK = "b"


class Kind(str, Enum):
    PAWN = "P"
    KNIGHT = "N"
    BISHOP = "B"
    ROOK = "R"
    QUEEN = "Q"
    KING = "K"


def _to_kind(value):
    try:
        return Kind(value)
    except ValueError:
        return value  # a custom, registered kind - not one of the six standard ones


def kind_to_str(kind):
    """A Kind member's own letter, or the value unchanged if it's already
    a plain string (a custom kind) or None (see MoveRecord.promoted_to).
    Not `str(kind)`: str, Enum's own __str__ gives "Kind.QUEEN", not "Q" -
    see server/protocol.py's identical note about rules.reasons.Reason."""
    return kind.value if isinstance(kind, Kind) else kind


@dataclass(frozen=True, eq=False)
class Piece:
    color: Color
    kind: "Kind | str"

    def __str__(self):
        return f"{self.color.value}{kind_to_str(self.kind)}"

    def __eq__(self, other):
        if isinstance(other, Piece):
            return self.color == other.color and self.kind == other.kind
        if isinstance(other, str):
            return str(self) == other
        return NotImplemented

    def __hash__(self):
        return hash(str(self))

    @classmethod
    def from_token(cls, token):
        return cls(Color(token[0]), _to_kind(token[1]))


def color_of(piece):
    return piece.color if isinstance(piece, Piece) else Color(piece[0])


def kind_of(piece):
    return piece.kind if isinstance(piece, Piece) else _to_kind(piece[1])


def make_piece(color, kind):
    return Piece(Color(color), _to_kind(kind))
