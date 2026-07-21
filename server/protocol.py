"""Wire format for server/ws_server.py: text move/jump commands in, JSON
state out.

Kept free of any websockets/asyncio/GameEngine import - it only converts
between plain text/dicts and plain Python values - so it's testable
without a running server.

Client -> server (one command per text message):
    "MOVE <start-square> <end-square>"   e.g. "MOVE e2 e4"
    "JUMP <square>"                      e.g. "JUMP e2"
    "LOGIN <username>"                   e.g. "LOGIN alice"
Squares are algebraic notation (view.notation.square_name/parse_square) -
letter file, then rank counting up from the bottom row - so a command
never depends on window pixels or a particular board size beyond the
board's own height. LOGIN's argument is a plain username, not a square -
see resolve_cells vs. Command.args directly.

Server -> client (JSON-encoded):
    {"type": "snapshot", "payload": {...}}   - same shape
        view.snapshot_codec.snapshot_from_json expects, so the existing
        GUI client can decode a server snapshot unchanged. Sent to every
        connection in a game after any change (a move accepted, a motion
        landing, a periodic tick - see ws_server.py) - "relevant parties"
        for now means everyone connected to that server, ahead of
        players/spectators being told apart.
    {"type": "error", "payload": {"message": str}}      - malformed command
    {"type": "rejected", "payload": {"reason": str}}    - legal command,
        refused by GameEngine (Reason.* from rules.reasons)
    {"type": "login", "payload": {"color": str, "username": str}}
        - LOGIN accepted, this connection is now seated as `color`
    {"type": "login_rejected", "payload": {"message": str}}
        - LOGIN refused (e.g. both seats already taken)
"""
from __future__ import annotations

from dataclasses import dataclass

from view.notation import parse_square

_ARITY = {"MOVE": 2, "JUMP": 1, "LOGIN": 1}


class ProtocolError(Exception):
    """A client sent something that isn't a valid command - bad verb, wrong
    number of arguments, or a malformed square (e.g. "MOVE e2 e5e5")."""


@dataclass(frozen=True)
class Command:
    verb: str
    args: tuple  # raw strings - algebraic squares for MOVE/JUMP, a
    # username for LOGIN - not yet resolved/validated, see resolve_cells


def parse_command(line):
    """"MOVE e2 e4" -> Command("MOVE", ("e2", "e4")). Args are left as text
    here - turning a MOVE/JUMP arg into a (row, col) needs the board's
    height, which this module doesn't have; see resolve_cells. LOGIN's arg
    needs no further resolution - use command.args[0] directly."""
    parts = line.split()
    if not parts:
        raise ProtocolError("Empty command")

    verb = parts[0].upper()
    if verb not in _ARITY:
        raise ProtocolError(f"Unknown command: {parts[0]!r}")

    args = tuple(parts[1:])
    expected = _ARITY[verb]
    if len(args) != expected:
        raise ProtocolError(f"{verb} expects {expected} argument(s), got {len(args)}")

    return Command(verb, args)


def resolve_cells(command, board_height):
    """A MOVE/JUMP Command's raw algebraic squares -> a tuple of (row, col)
    cells. Kept separate from parse_command because it needs board_height,
    which the wire format itself has no business knowing. Not meaningful
    for LOGIN - its single arg is a username, not a square."""
    try:
        return tuple(parse_square(square, board_height) for square in command.args)
    except ValueError as error:
        raise ProtocolError(str(error)) from error


def encode_snapshot(engine):
    """The {"type": "snapshot", ...} message for the given engine's current
    state - the same JSON shape view.snapshot_codec.snapshot_from_json
    expects. Includes the arbiter's real-time motion state (moves/jumps/
    recent_arrivals) - unlike a headless-only protocol, this project's GUI
    client needs it to animate in-flight pieces (see view/animation.py).
    Excludes selected/rejection_reason/legal_destinations: those are
    per-client UI state the server doesn't own.
    """
    snapshot = engine.snapshot()
    return {
        "type": "snapshot",
        "payload": {
            "cells": [list(row) for row in snapshot.cells],
            "width": snapshot.width,
            "height": snapshot.height,
            "game_over": snapshot.game_over,
            "moves": [
                {
                    "piece": move.piece,
                    "start": list(move.start),
                    "end": list(move.end),
                    "arrival": move.arrival,
                    "path": [list(cell) for cell in move.path],
                }
                for move in snapshot.moves
            ],
            "jumps": [
                {"piece": jump.piece, "cell": list(jump.cell), "end_time": jump.end_time}
                for jump in snapshot.jumps
            ],
            "recent_arrivals": [
                {
                    "piece": arrival.piece,
                    "cell": list(arrival.cell),
                    "at": arrival.at,
                    "kind": arrival.kind,
                }
                for arrival in snapshot.recent_arrivals
            ],
            "clock": snapshot.clock,
            "winner": snapshot.winner,
            "move_history": {
                color: [
                    {
                        "piece": record.piece,
                        "start": list(record.start),
                        "end": list(record.end),
                        "promoted_to": record.promoted_to,
                    }
                    for record in records
                ]
                for color, records in snapshot.move_history.items()
            },
            "score": dict(snapshot.score),
        },
    }


def encode_error(message):
    return {"type": "error", "payload": {"message": message}}


def encode_rejected(reason):
    # Reason subclasses str (see rules.reasons), so it serializes as its
    # plain value ("busy_source") once json.dumps'd - not str(reason),
    # which would instead give Enum's own "Reason.BUSY_SOURCE".
    return {"type": "rejected", "payload": {"reason": reason}}


def encode_login(color, username):
    return {"type": "login", "payload": {"color": color, "username": username}}


def encode_login_rejected(message):
    return {"type": "login_rejected", "payload": {"message": message}}
