"""Turns the server's JSON snapshot message back into the same GameSnapshot
GraphicsRenderer already renders locally in main.py/main_gui.py's old
in-process path - so the network client can reuse GraphicsRenderer's
existing "snapshot in, canvas out" contract unchanged.

GameSnapshot, MoveRecord, Move, Jump and Arrival are all plain dataclasses
with no game-logic imports (no Board/RuleEngine/GameEngine), so importing
them here does not pull any server-only code into the client - they are
the wire schema, not the engine.

Expected JSON shape (matches GameSnapshot's own field names):
{
  "cells": [["wR", ".", ...], ...],
  "width": int, "height": int, "game_over": bool,
  "selected": [row, col] | null,
  "rejection_reason": str | null,
  "legal_destinations": [[row, col], ...],
  "moves": [{"piece": str, "start": [r,c], "end": [r,c], "arrival": int, "path": [[r,c], ...]}, ...],
  "jumps": [{"piece": str, "cell": [r,c], "end_time": int}, ...],
  "recent_arrivals": [{"piece": str, "cell": [r,c], "at": int, "kind": "move"|"jump"}, ...],
  "clock": int,
  "winner": str | null,
  "move_history": {"w": [{"piece": str, "start": [r,c], "end": [r,c], "promoted_to": str | null}, ...], ...},
  "score": {"w": int, "b": int, ...}
}
"""
from __future__ import annotations

from game.models import MoveRecord
from game.snapshot import GameSnapshot
from realtime.models import Arrival, Jump, Move


def snapshot_from_json(data):
    return GameSnapshot(
        cells=tuple(tuple(row) for row in data["cells"]),
        width=data["width"],
        height=data["height"],
        game_over=data["game_over"],
        selected=_cell(data.get("selected")),
        rejection_reason=data.get("rejection_reason"),
        legal_destinations=frozenset(_cell(c) for c in data.get("legal_destinations", ())),
        moves=tuple(_move(m) for m in data.get("moves", ())),
        jumps=tuple(_jump(j) for j in data.get("jumps", ())),
        recent_arrivals=tuple(_arrival(a) for a in data.get("recent_arrivals", ())),
        clock=data.get("clock", 0),
        winner=data.get("winner"),
        move_history={
            color: tuple(_move_record(r) for r in records)
            for color, records in data.get("move_history", {}).items()
        },
        score=dict(data.get("score", {})),
    )


def _cell(pair):
    return tuple(pair) if pair is not None else None


def _move(data):
    return Move(
        piece=data["piece"],
        start=_cell(data["start"]),
        end=_cell(data["end"]),
        arrival=data["arrival"],
        path=tuple(_cell(c) for c in data.get("path", ())),
    )


def _jump(data):
    return Jump(piece=data["piece"], cell=_cell(data["cell"]), end_time=data["end_time"])


def _arrival(data):
    return Arrival(piece=data["piece"], cell=_cell(data["cell"]), at=data["at"], kind=data["kind"])


def _move_record(data):
    return MoveRecord(
        piece=data["piece"],
        start=_cell(data["start"]),
        end=_cell(data["end"]),
        promoted_to=data.get("promoted_to"),
    )
