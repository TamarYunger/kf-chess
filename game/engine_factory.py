"""Shared GameEngine assembly: registry -> board -> arbiter -> rule engine
-> GameEngine, the exact wiring every composition root that builds its own
engine needs (server/shard.py's per-room engine, client/session/
local_game_session.py's offline session, main.py's text-mode CLI) - kept in
one place so a change to how an engine is put together (a new collaborator,
a different default win condition) doesn't have to be applied identically
in three unrelated files by hand.

Deliberately just the engine-construction sequence - not `events`, which
each caller still creates (and may attach its own subscribers to, e.g.
game.presentation_stub, before the engine's constructor publishes
"game_started") on its own, and not board-loading error handling, which
differs per caller (main.py prints and exits on a malformed board;
server/shard.py and local_game_session.py let it raise - a malformed
default board there is a programming bug, not user input to report
gracefully).
"""
from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING

from board.loaders import load_text_board
from game.engine import GameEngine
from realtime.real_time_arbiter import RealTimeArbiter
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion
from rules.rule_engine import RuleEngine
from rules.rule_registry import build_default_registry

if TYPE_CHECKING:
    from bus.event_bus import EventBus


def build_engine(board_lines: list[str], config: ModuleType, events: EventBus | None = None) -> GameEngine:
    registry = build_default_registry(config)
    board = load_text_board(board_lines, registry, config)
    arbiter = RealTimeArbiter(board=board, promotion_rule=LastRankPromotion(config.PAWN_DIRECTION), config=config)
    return GameEngine(
        board=board,
        rule_engine=RuleEngine(rule_registry=registry, config=config),
        arbiter=arbiter,
        win_condition=KingCaptureWinCondition(),
        config=config,
        events=events,
    )
