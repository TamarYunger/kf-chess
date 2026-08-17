"""Wire format for server/ws_server.py: text move/jump commands in, JSON
state out.

Kept free of any websockets/asyncio/GameEngine import - it only converts
between plain text/dicts and plain Python values - so it's testable
without a running server.

Client -> server (one command per text message):
    "MOVE <start-square> <end-square>"   e.g. "MOVE e2 e4"
    "JUMP <square>"                      e.g. "JUMP e2"
    "SELECT <square>"                    - a read-only query: "if I moved
                                          this piece, where could it go
                                          right now" (see legal_destinations
                                          below) - not a move itself, so it
                                          is never rejected/logged as one
    "AUTH <token>"                        e.g. "AUTH 9f3c2b1a..."
    "PLAY"                                - join the matchmaking queue
    "ROOM CREATE"                         - create a new room, seated first
    "ROOM JOIN <room-id>"                 - join an existing room
Squares are algebraic notation (board.notation.square_name/parse_square) -
letter file, then rank counting up from the bottom row - so a command
never depends on window pixels or a particular board size beyond the
board's own height. AUTH's argument is an opaque token, not a square -
see resolve_cells vs. Command.args directly. The token itself was issued
by server.api_gateway's POST /login (which is what actually checks a
username/password against server.db) and looked up here against Redis,
not authenticated locally - this module/this server no longer sees a
password at all. AUTH only authenticates - it does NOT seat a color;
PLAY (matched against another PLAY-ing connection within
server.matchmaking's rating range) or ROOM CREATE/JOIN is what does
that, so a player can be logged in (browsing HOME) without occupying a
game seat. Both paths end up in the exact same place - a
server.room.Room - PLAY just creates one automatically instead of the
player picking an id (see server/ws_server.py); a room's third-and-later
joiner becomes a viewer instead of a third seat.

Server -> client (JSON-encoded):
    {"type": "snapshot", "payload": {...}}   - same shape
        session.snapshot_codec.snapshot_from_json expects, so the existing
        GUI client can decode a server snapshot unchanged. Sent to every
        connection in a room after any change (a move accepted, a motion
        landing, a periodic tick - see ws_server.py) - seated players and
        viewers alike.
    {"type": "error", "payload": {"message": str}}      - malformed command,
        or a viewer/unseated connection attempting MOVE/JUMP, or ROOM JOIN
        for an id that doesn't exist
    {"type": "rejected", "payload": {"reason": str}}    - legal command,
        refused by GameEngine (Reason.* from rules.reasons)
    {"type": "login", "payload": {"username": str, "rating": int}}
        - AUTH accepted (a valid, unexpired token - see server/api_gateway.py);
          no room/color yet - see PLAY/ROOM
    {"type": "login_rejected", "payload": {"message": str}}
        - AUTH refused (invalid/expired/already-used token)
    {"type": "room", "payload": {"room_id": str, "role": str}}
        - this connection is now part of room_id, as `role` - one of
          config.COLORS ("w"/"b") if seated, or "viewer". Sent once, right
          after PLAY finds a match or ROOM CREATE/JOIN succeeds - the GUI
          client shows room_id as a persistent header for as long as it's
          in that room (view/game_screen.py)
    {"type": "no_match", "payload": null}
        - PLAY timed out (server.matchmaker_service.MATCHMAKING_TIMEOUT_SECONDS)
          with no compatible opponent found
    {"type": "opponent_disconnected", "payload": {"color": str, "grace_period_seconds": int}}
        - the player seated as `color` dropped connection; they have
          `grace_period_seconds` to reconnect (a fresh REST /login, then
          AUTH with the new token, then rejoin the same room with the
          same username) before auto-resigning
    {"type": "opponent_reconnected", "payload": {"color": str}}
        - `color` reconnected within the grace period; the countdown is
          cancelled
    {"type": "legal_destinations", "payload": {"start": [row, col], "destinations": [[row, col], ...]}}
        - reply to that connection's own SELECT, using the exact same
          GameEngine.legal_destinations the engine itself enforces on the
          following MOVE - never computed twice with different rules.
          `destinations` is empty if `start` isn't that connection's own
          piece (an empty cell, the opponent's, or a viewer's SELECT at all)
    {"type": "arrival", "payload": {"piece": str, "destination": [row, col], "captured": str | None}}
        - broadcast the instant a move actually lands (mirrors GameEngine's
          own "arrival" bus event, JSON-shaped for the wire) - purely so a
          client can react exactly once per landing (e.g. view.sound's move
          vs capture sound) without diffing consecutive snapshots itself.
          Never sent for a jump (see RealTimeArbiter.resolve/_resolve_jumps
          - a jump never publishes "arrival" either, on the server side)
    {"type": "game_over", "payload": {"winner": str | None}}
        - broadcast the instant the game actually ends (capture or resign);
          also already reflected in every subsequent snapshot's own
          game_over/winner fields, but this is the one-time edge a reactive
          client (again, view.sound) needs instead of polling those
    {"type": "resign", "payload": {"color": str}}
        - broadcast right before that same "game_over", only when the game
          ended via `color` running out its disconnect grace period
          (server/room.py's auto-resign) rather than a capture - lets a
          client (or session_logging's audit trail) tell the two apart;
          "game_over" alone can't, since a capture also just reports a
          winner
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from board.notation import parse_square
from bus.event_types import (
    ARRIVAL, ERROR, GAME_OVER, LEGAL_DESTINATIONS, LOGIN, LOGIN_REJECTED, NO_MATCH,
    OPPONENT_DISCONNECTED, OPPONENT_RECONNECTED, REJECTED, RESIGN, ROOM, ROOM_STARTED, SNAPSHOT,
    WAITING_FOR_OPPONENT,
)

if TYPE_CHECKING:
    from game.engine import GameEngine
    from realtime.real_time_arbiter import ArrivalEvent

_ARITY = {"MOVE": 2, "JUMP": 1, "SELECT": 1, "AUTH": 1, "PLAY": 0}
_ROOM_SUBCOMMANDS = {"CREATE": 0, "JOIN": 1}


class ProtocolError(Exception):
    """A client sent something that isn't a valid command - bad verb, wrong
    number of arguments, or a malformed square (e.g. "MOVE e2 e5e5")."""


@dataclass(frozen=True)
class Command:
    verb: str
    args: tuple  # raw strings - algebraic squares for MOVE/JUMP,
    # (username, password) for LOGIN - not yet resolved/validated, see
    # resolve_cells


def parse_command(line: str) -> Command:
    """"MOVE e2 e4" -> Command("MOVE", ("e2", "e4")). Args are left as text
    here - turning a MOVE/JUMP arg into a (row, col) needs the board's
    height, which this module doesn't have; see resolve_cells. AUTH's arg
    needs no further resolution - use command.args[0] directly.

    "ROOM ..." is special-cased: its second word (CREATE/JOIN) picks the
    actual verb ("ROOM_CREATE"/"ROOM_JOIN") and that verb's own arity, the
    same way every other verb's first word does - see _parse_room.
    """
    parts = line.split()
    if not parts:
        raise ProtocolError("Empty command")

    verb = parts[0].upper()
    if verb == "ROOM":
        return _parse_room(parts)

    if verb not in _ARITY:
        raise ProtocolError(f"Unknown command: {parts[0]!r}")

    args = tuple(parts[1:])
    expected = _ARITY[verb]
    if len(args) != expected:
        raise ProtocolError(f"{verb} expects {expected} argument(s), got {len(args)}")

    return Command(verb, args)


def _parse_room(parts: list[str]) -> Command:
    if len(parts) < 2:
        raise ProtocolError("ROOM expects CREATE or JOIN <room id>")

    subcommand = parts[1].upper()
    if subcommand not in _ROOM_SUBCOMMANDS:
        raise ProtocolError(f"Unknown ROOM subcommand: {parts[1]!r}")

    args = tuple(parts[2:])
    expected = _ROOM_SUBCOMMANDS[subcommand]
    if len(args) != expected:
        raise ProtocolError(f"ROOM {subcommand} expects {expected} argument(s), got {len(args)}")

    return Command(f"ROOM_{subcommand}", args)


def resolve_cells(command: Command, board_height: int) -> tuple[tuple[int, int], ...]:
    """A MOVE/JUMP Command's raw algebraic squares -> a tuple of (row, col)
    cells. Kept separate from parse_command because it needs board_height,
    which the wire format itself has no business knowing. Not meaningful
    for AUTH - its arg is an opaque token, not a square."""
    try:
        return tuple(parse_square(square, board_height) for square in command.args)
    except ValueError as error:
        raise ProtocolError(str(error)) from error


def encode_snapshot(engine: GameEngine) -> dict:
    """The {"type": "snapshot", ...} message for the given engine's current
    state - the same JSON shape session.snapshot_codec.snapshot_from_json
    expects. Includes the arbiter's real-time motion state (moves/jumps/
    recent_arrivals) - unlike a headless-only protocol, this project's GUI
    client needs it to animate in-flight pieces (see view/animation.py).
    Excludes selected/rejection_reason/legal_destinations: those are
    per-client UI state the server doesn't own.
    """
    snapshot = engine.snapshot()
    return {
        "type": SNAPSHOT,
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


def encode_error(message: str) -> dict:
    return {"type": ERROR, "payload": {"message": message}}


def encode_rejected(reason: str) -> dict:
    # Reason subclasses str (see rules.reasons), so it serializes as its
    # plain value ("busy_source") once json.dumps'd - not str(reason),
    # which would instead give Enum's own "Reason.BUSY_SOURCE".
    return {"type": REJECTED, "payload": {"reason": reason}}


def encode_login(username: str, rating: int) -> dict:
    return {"type": LOGIN, "payload": {"username": username, "rating": rating}}


def encode_login_rejected(message: str) -> dict:
    return {"type": LOGIN_REJECTED, "payload": {"message": message}}


def encode_room(room_id: str, role: str) -> dict:
    return {"type": ROOM, "payload": {"room_id": room_id, "role": role}}


def encode_no_match() -> dict:
    return {"type": NO_MATCH, "payload": None}


def encode_opponent_disconnected(color: str, grace_period_seconds: int) -> dict:
    return {
        "type": OPPONENT_DISCONNECTED,
        "payload": {"color": color, "grace_period_seconds": grace_period_seconds},
    }


def encode_opponent_reconnected(color: str) -> dict:
    return {"type": OPPONENT_RECONNECTED, "payload": {"color": color}}


def encode_legal_destinations(start: tuple[int, int], destinations: Iterable[tuple[int, int]]) -> dict:
    return {
        "type": LEGAL_DESTINATIONS,
        "payload": {"start": list(start), "destinations": [list(cell) for cell in sorted(destinations)]},
    }


def encode_waiting_for_opponent() -> dict:
    # Sent once, right after a ROOM CREATE, only to the creator, and only
    # if no one else is seated yet - PLAY's matchmaking always seats both
    # sides at once, so a PLAY-matched room never sends this.
    return {"type": WAITING_FOR_OPPONENT, "payload": None}


def encode_room_started() -> dict:
    # Broadcast once, exactly when a room's second seat is filled for the
    # first time - clears whatever "waiting" state the creator's client
    # is showing.
    return {"type": ROOM_STARTED, "payload": None}


def encode_arrival(event: ArrivalEvent) -> dict:
    # event.piece/.captured are a real board.piece.Piece (a dataclass, not
    # JSON-serializable) whenever the room's board came from a loader -
    # str() converts back to the plain token, same boundary conversion
    # game/snapshot.py does for a full snapshot (this event bypasses that
    # and goes straight from the bus to the wire, so it needs its own).
    return {
        "type": ARRIVAL,
        "payload": {
            "piece": str(event.piece),
            "destination": list(event.destination),
            "captured": str(event.captured) if event.captured is not None else None,
        },
    }


def encode_game_over(winner: str | None) -> dict:
    return {"type": GAME_OVER, "payload": {"winner": winner}}


def encode_resign(color: str) -> dict:
    return {"type": RESIGN, "payload": {"color": color}}
