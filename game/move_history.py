from __future__ import annotations

import dataclasses

from board.piece import color_of, kind_of
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

    Every mutation republishes "move_log_updated" (payload: this same
    snapshot()) on the same bus, so a move-log UI can react without polling
    `GameEngine.move_history` itself.
    """

    def __init__(self, colors):
        self._records = {color: [] for color in colors}
        self._events = None

    def subscribe_to(self, events):
        self._events = events
        events.subscribe("move_accepted", self._on_move_accepted)
        events.subscribe("arrival", self._on_arrival)

    def snapshot(self):
        return {color: tuple(moves) for color, moves in self._records.items()}

    # -- event handlers -----------------------------------------------

    def _on_move_accepted(self, payload):
        piece, start, end = payload["piece"], payload["start"], payload["end"]
        self._records[color_of(piece)].append(MoveRecord(piece, start, end))
        self._publish_updated()

    def _on_arrival(self, event):
        """Finds the record this arrival settled - matching color +
        destination, most recent first (that's always the one this event
        settled, since two same-color moves can never target the same
        destination - see the DESTINATION_CONTESTED guard in
        GameEngine.request_move)."""
        history = self._records[color_of(event.piece)]
        for i in range(len(history) - 1, -1, -1):
            record = history[i]
            if record.end == event.destination and kind_of(record.piece) != kind_of(event.piece):
                history[i] = dataclasses.replace(record, promoted_to=kind_of(event.piece))
                self._publish_updated()
                break

    def _publish_updated(self):
        self._events.publish("move_log_updated", self.snapshot())
