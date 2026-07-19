from __future__ import annotations

import dataclasses

from game.models import MoveRecord


class MoveHistory:
    """Per-color log of accepted moves, kept in sync via events instead of
    being written inline by whichever engine method changed the board.

    Subscribes to two events published by GameEngine:
      - "move_accepted": a move was just validated and handed to the
        arbiter (recorded immediately, the same moment standard chess
        notation would - not once the piece finishes travelling).
      - "arrival": the arbiter settled a move (possibly asynchronously,
        after MOVE_DURATION); patches the matching record's `promoted_to`
        if the piece that landed differs from the one that set out.
    """

    def __init__(self, colors):
        self._records = {color: [] for color in colors}

    def subscribe_to(self, events):
        events.subscribe("move_accepted", self._on_move_accepted)
        events.subscribe("arrival", self._on_arrival)

    def snapshot(self):
        return {color: tuple(moves) for color, moves in self._records.items()}

    # -- event handlers -----------------------------------------------

    def _on_move_accepted(self, piece, start, end):
        self._records[piece[0]].append(MoveRecord(piece, start, end))

    def _on_arrival(self, event):
        """Finds the record this arrival settled - matching color +
        destination, most recent first (that's always the one this event
        settled, since two same-color moves can never target the same
        destination - see the DESTINATION_CONTESTED guard in
        GameEngine.request_move)."""
        history = self._records[event.piece[0]]
        for i in range(len(history) - 1, -1, -1):
            record = history[i]
            if record.end == event.destination and record.piece[1] != event.piece[1]:
                history[i] = dataclasses.replace(record, promoted_to=event.piece[1])
                break
