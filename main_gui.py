"""KungFu Chess - interactive graphical entry point.

Separate from main.py (the script/test-driven CLI) so the existing tested
batch path is untouched. Opens an Img-backed window driven by the wall clock
and mouse: single click selects/moves, double click jumps.
"""
import dataclasses
import time
import types
from pathlib import Path

from config import settings
from rules.rule_registry import build_default_registry
from rules.rule_engine import RuleEngine
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion
from realtime.real_time_arbiter import RealTimeArbiter
from board.loaders import load_text_board
from game.board_mapper import BoardMapper
from game.engine import GameEngine
from game.controller import Controller
from view.graphics_renderer import GraphicsRenderer, SIDE_PANEL_WIDTH
from view.img import Img
from view.piece_assets import load_all_piece_configs, state_duration_ms

PROJECT_ROOT = Path(__file__).resolve().parent
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


def build_game(board_lines, config=settings, board_x_offset=0):
    """Wires the same collaborators as main.run's first half (registry,
    board, arbiter, engine, controller), stopping short of dispatching any
    commands - the GUI loop drives them interactively instead.

    `board_x_offset` is how far the board's own left edge sits from the
    window's left edge - non-zero once GraphicsRenderer draws a side panel
    before it, so BoardMapper can convert raw mouse coordinates correctly.
    """
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
        board_mapper=BoardMapper(board, config.CELL_SIZE, x_offset=board_x_offset),
    )
    return engine, controller


def with_synced_rest_durations(config):
    """Overrides SHORT_REST_DURATION/LONG_REST_DURATION with the real
    short_rest/long_rest sprites' own playback duration (frame_count/fps),
    so the gameplay cooldown always exactly matches how long the rest
    animation actually plays - taking the max across piece kinds in case a
    future skin gives them differing lengths (today they're uniform).

    Copies every field from `config` (not a fixed whitelist) so any new
    config field added later reaches the GUI automatically, instead of
    silently being missing until someone remembers to list it here too.
    """
    pieces_root = PROJECT_ROOT / config.ASSETS_DIR / "pieces"
    piece_configs = load_all_piece_configs(pieces_root)
    short = max(state_duration_ms(cfgs["short_rest"]) for cfgs in piece_configs.values())
    long_ = max(state_duration_ms(cfgs["long_rest"]) for cfgs in piece_configs.values())
    overrides = {**vars(config), "SHORT_REST_DURATION": short, "LONG_REST_DURATION": long_}
    return types.SimpleNamespace(**overrides)


def run_gui(board_lines=None, config=settings):
    config = with_synced_rest_durations(config)
    engine, controller = build_game(
        board_lines or STANDARD_BOARD_TEXT, config=config, board_x_offset=SIDE_PANEL_WIDTH,
    )
    renderer = GraphicsRenderer(config)

    Img.open_window(WINDOW_NAME)
    Img.set_mouse_callback(WINDOW_NAME, on_click=controller.click, on_double_click=controller.jump)

    last_time = time.time()
    try:
        while True:
            now = time.time()
            dt_ms = int((now - last_time) * 1000)
            last_time = now
            engine.wait(dt_ms)

            legal_destinations = (
                engine.legal_destinations(controller.selected)
                if controller.selected is not None else frozenset()
            )
            snapshot = dataclasses.replace(
                engine.snapshot(),
                selected=controller.selected,
                rejection_reason=controller.last_rejection,
                legal_destinations=legal_destinations,
            )
            canvas = renderer.render(snapshot)
            canvas.show_frame(WINDOW_NAME)

            key = Img.wait_key(16)
            if key == 27:  # ESC
                break
            if not Img.is_window_visible(WINDOW_NAME):
                break
    finally:
        Img.close_all_windows()


if __name__ == "__main__":  # pragma: no cover
    run_gui()
