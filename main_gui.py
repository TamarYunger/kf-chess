"""KungFu Chess - interactive graphical entry point.

Separate from main.py (the script/test-driven CLI) so the existing tested
batch path is untouched. Opens a cv2 window driven by the wall clock and
mouse: single click selects/moves, double click jumps.
"""
import dataclasses
import time

import cv2

from config import settings
from rules.rule_registry import build_default_registry
from rules.rule_engine import RuleEngine
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion
from realtime.real_time_arbiter import RealTimeArbiter
from board.loaders import load_text_board
from game.board_mapper import BoardMapper
from game.engine import GameEngine
from game.controller import Controller
from view.graphics_renderer import GraphicsRenderer

WINDOW_NAME = "KungFu Chess"

STANDARD_BOARD_TEXT = [
    "bR bN bB bQ bK bB bN bR",
    "bP bP bP bP bP bP bP bP",
    ". . . . . . . .",
    ". . . . . . . .",
    ". . . . . . . .",
    ". . . . . . . .",
    "wP wP wP wP wP wP wP wP",
    "wR wN wB wQ wK wB wN wR",
]


def build_game(board_lines, config=settings):
    """Wires the same collaborators as main.run's first half (registry,
    board, arbiter, engine, controller), stopping short of dispatching any
    commands - the GUI loop drives them interactively instead."""
    registry = build_default_registry(config)
    board = load_text_board(board_lines, registry, config)

    arbiter = RealTimeArbiter(
        board=board,
        promotion_rule=LastRankPromotion(config.PAWN_DIRECTION),
        config=config,
    )
    engine = GameEngine(
        board=board,
        rule_engine=RuleEngine(rule_registry=registry, config=config),
        arbiter=arbiter,
        win_condition=KingCaptureWinCondition(),
        config=config,
    )
    controller = Controller(
        engine=engine,
        board_mapper=BoardMapper(board, config.CELL_SIZE),
    )
    return engine, controller


def run_gui(board_lines=None, config=settings):
    engine, controller = build_game(board_lines or STANDARD_BOARD_TEXT, config=config)
    renderer = GraphicsRenderer(config)

    def on_mouse(event, x, y, flags, userdata):
        if event == cv2.EVENT_LBUTTONDOWN:
            controller.click(x, y)
        elif event == cv2.EVENT_LBUTTONDBLCLK:
            controller.jump(x, y)

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)

    last_time = time.time()
    try:
        while True:
            now = time.time()
            dt_ms = int((now - last_time) * 1000)
            last_time = now
            engine.wait(dt_ms)

            snapshot = dataclasses.replace(engine.snapshot(), selected=controller.selected)
            canvas = renderer.render(snapshot)
            cv2.imshow(WINDOW_NAME, canvas.img)

            key = cv2.waitKey(16) & 0xFF
            if key == 27:  # ESC
                break
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cv2.destroyAllWindows()


if __name__ == "__main__":  # pragma: no cover
    run_gui()
