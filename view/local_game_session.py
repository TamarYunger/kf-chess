"""LocalGameSession: a GameSession backed directly by an in-process
GameEngine - the "Play Offline" path, no server or network involved at
all. Deliberately the only file under view/ that imports GameEngine and
its collaborators; every other view-layer module (GameScreen included)
only ever sees the GameSession abstraction.
"""
from __future__ import annotations

import dataclasses
import time

from board.loaders import load_text_board
from bus.event_bus import EventBus
from game.board_mapper import BoardMapper
from game.controller import Controller
from game.engine import GameEngine
from game.presentation_stub import attach_presentation_stub
from realtime.real_time_arbiter import RealTimeArbiter
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion
from rules.rule_engine import RuleEngine
from rules.rule_registry import build_default_registry
from view.game_session import GameSession

# Commands reaching this session already carry a board cell - GameScreen
# resolves window pixels to a cell itself, the one piece of geometry
# needed identically whether the game is local or networked - so this
# session's own BoardMapper is configured as a pure identity pass-through
# (a 1-pixel-per-cell mapper with no offset) purely to reuse Controller's
# existing pixel-shaped click()/jump() and its selection state machine,
# instead of duplicating that logic here.
_IDENTITY_CELL_SIZE = 1


class LocalGameSession(GameSession):
    def __init__(self, board_lines, config, events=None):
        registry = build_default_registry(config)
        board = load_text_board(board_lines, registry, config)
        arbiter = RealTimeArbiter(
            board=board,
            promotion_rule=LastRankPromotion(config.PAWN_DIRECTION),
            config=config,
        )
        events = events if events is not None else EventBus()
        attach_presentation_stub(events)
        self._engine = GameEngine(
            board=board,
            rule_engine=RuleEngine(rule_registry=registry, config=config),
            arbiter=arbiter,
            win_condition=KingCaptureWinCondition(),
            config=config,
            events=events,
        )
        mapper = BoardMapper(board, _IDENTITY_CELL_SIZE)
        self._controller = Controller(engine=self._engine, board_mapper=mapper)
        self._last_tick = time.time()
        self._latest_snapshot = None
        self._recompute_snapshot()  # available immediately, even before the first real tick()

    def submit_command(self, command):
        row, col = command["cell"]
        if command["type"] == "click":
            self._controller.click(col, row)
        elif command["type"] == "jump":
            self._controller.jump(col, row)

    def tick(self):
        now = time.time()
        dt_ms = int((now - self._last_tick) * 1000)
        self._last_tick = now
        self._engine.wait(dt_ms)
        self._recompute_snapshot()

    def latest_snapshot(self):
        return self._latest_snapshot

    def _recompute_snapshot(self):
        selected = self._controller.selected
        legal_destinations = (
            self._engine.legal_destinations(selected) if selected is not None else frozenset()
        )
        self._latest_snapshot = dataclasses.replace(
            self._engine.snapshot(),
            selected=selected,
            rejection_reason=self._controller.last_rejection,
            legal_destinations=legal_destinations,
        )
