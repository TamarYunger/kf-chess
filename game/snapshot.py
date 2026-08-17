from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from board.piece import kind_to_str

if TYPE_CHECKING:
    from board.board import Board
    from game.models import MoveRecord
    from realtime.models import Arrival, Jump, Move

_Motion = TypeVar("_Motion", "Move", "Jump", "Arrival")


def _stringify_motion(items: tuple[_Motion, ...]) -> tuple[_Motion, ...]:
    """Move/Jump/Arrival all carry a `piece` field - a real Piece object
    once the board came from a loader (see board/loaders.py) - converted
    back to a plain token string here, at the one boundary GameSnapshot
    is documented to be (the renderer "never receives the live Board or
    Piece objects"). Works unchanged on a plain string `piece` too (a
    directly-constructed test board bypassing the loader), since str() on
    an already-plain string is a no-op."""
    return tuple(dataclasses.replace(item, piece=str(item.piece)) for item in items)


def _stringify_move_history(
    move_history: dict[str, tuple[MoveRecord, ...]],
) -> dict[str, tuple[MoveRecord, ...]]:
    return {
        color: tuple(
            dataclasses.replace(
                record, piece=str(record.piece), promoted_to=kind_to_str(record.promoted_to),
            )
            for record in records
        )
        for color, records in move_history.items()
    }


@dataclass(frozen=True)
class GameSnapshot:
    """Read-only view of the game state handed to the renderer.

    The renderer never receives the live Board or Piece objects - only this
    immutable snapshot - so the view layer cannot accidentally mutate the
    model. `cells` is the logical board (a tuple of tuples of tokens).

    `selected` is part of the shape (a graphical renderer highlights it) but is
    populated only by whoever owns selection state; the engine leaves it None,
    since `print board` never shows selection.

    `rejection_reason` mirrors `selected`: UI-only feedback about why the
    most recent command was refused, populated by whoever owns that state
    (the Controller) - the engine leaves it None.

    `legal_destinations` is the set of cells the currently selected piece
    could legally move to, for a renderer to highlight - empty whenever
    nothing is selected; the engine leaves it empty too, since it depends
    on `selected` which the engine doesn't own.

    `moves`, `jumps`, `recent_arrivals` and `clock` carry the arbiter's
    real-time motion state (all read-only, mirroring `cells`) so a graphical
    renderer can animate in-flight pieces; the text renderer ignores them.
    They default to empty/zero so every existing caller that only cares
    about board contents is unaffected.

    `winner` is the color that ended the game in its favour, populated by
    the engine alongside `game_over`; None while the game is still on.

    `move_history` maps each color to its tuple of accepted MoveRecords, for
    a renderer that wants to display a move log; defaults to empty so
    existing callers that don't care about it are unaffected.

    `score` maps each color to its accumulated capture points so far;
    defaults to empty for the same reason.
    """

    cells: tuple
    width: int
    height: int
    game_over: bool
    selected: tuple | None = None
    rejection_reason: str | None = None
    legal_destinations: frozenset = field(default_factory=frozenset)
    moves: tuple = ()
    jumps: tuple = ()
    recent_arrivals: tuple = ()
    clock: int = 0
    winner: str | None = None
    move_history: dict = field(default_factory=dict)
    score: dict = field(default_factory=dict)

    @classmethod
    def from_board(
        cls,
        board: Board,
        game_over: bool,
        selected: tuple[int, int] | None = None,
        moves: tuple[Move, ...] = (),
        jumps: tuple[Jump, ...] = (),
        recent_arrivals: tuple[Arrival, ...] = (),
        clock: int = 0,
        winner: str | None = None,
        move_history: dict[str, tuple[MoveRecord, ...]] | None = None,
        score: dict[str, int] | None = None,
        rejection_reason: str | None = None,
        legal_destinations: frozenset[tuple[int, int]] | None = None,
    ) -> GameSnapshot:
        cells = tuple(tuple(str(cell) for cell in row) for row in board.snapshot())
        return cls(
            cells=cells,
            width=board.width,
            height=board.height,
            game_over=game_over,
            selected=selected,
            rejection_reason=rejection_reason,
            legal_destinations=legal_destinations or frozenset(),
            moves=_stringify_motion(moves),
            jumps=_stringify_motion(jumps),
            recent_arrivals=_stringify_motion(recent_arrivals),
            clock=clock,
            winner=winner,
            move_history=_stringify_move_history(move_history or {}),
            score=score or {},
        )
