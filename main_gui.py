"""KungFu Chess - interactive graphical entry point.

Talks only to a GameSession (view/game_session.py), never to GameEngine or
a network client directly - so this loop works identically whether the
game is running fully offline (LocalGameSession, the default: no server
involved at all) or over the network (NetworkGameSession, talking to a
real server over WebSocket). Which one is used is decided once, in
run_gui's `mode` argument - never mid-run; a future home screen's "Play
Offline" vs "Login" choice would just call run_gui with a different mode.

For a networked session the actual WebSocket connection - and the asyncio
event loop it needs - lives on its own background thread (this render loop
is synchronous, driven by cv2.waitKey, and must never block on network
I/O); see view/network_client.py. Either way, every screen transition is
driven by bus events (view/screen_manager.py), not hardcoded here.
"""
import types
from pathlib import Path

from bus.event_bus import EventBus
from config import settings
from view.game_screen import GameScreen
from view.graphics_renderer import SIDE_PANEL_WIDTH
from view.img import Img
from view.local_game_session import LocalGameSession
from view.network_game_session import NetworkGameSession
from view.piece_assets import load_all_piece_configs, state_duration_ms
from view.screen_manager import ScreenManager

PROJECT_ROOT = Path(__file__).resolve().parent
WINDOW_NAME = "KungFu Chess"
DEFAULT_SERVER_URL = "ws://localhost:8765"

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

# cv2.waitKey's return value (Img.wait_key) when no key was pressed during
# the frame's delay window.
NO_KEY = 255
ESC_KEY = 27


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


def build_session(mode, events, config, board_lines=None, server_url=DEFAULT_SERVER_URL):
    if mode == "local":
        return LocalGameSession(board_lines or STANDARD_BOARD_TEXT, config, events=events)
    if mode == "network":
        return NetworkGameSession(server_url, events)
    raise ValueError(f"Unknown mode: {mode!r} (expected 'local' or 'network')")


def build_screens(events, config, session):
    """Wires every known screen into a ScreenManager. Only GAME exists so
    far - LOGIN/HOME/ROOM_DIALOG land in a later step, each registered here
    the same way, with its own bus-driven `transitions=` mapping."""
    manager = ScreenManager(events, initial="GAME")
    manager.register("GAME", GameScreen(config, session, board_x_offset=SIDE_PANEL_WIDTH))
    return manager


def run_gui(mode="local", server_url=DEFAULT_SERVER_URL, board_lines=None, config=settings):
    config = with_synced_rest_durations(config)
    events = EventBus()
    session = build_session(mode, events, config, board_lines=board_lines, server_url=server_url)
    manager = build_screens(events, config, session)

    Img.open_window(WINDOW_NAME)
    Img.set_mouse_callback(WINDOW_NAME, on_click=manager.handle_click, on_double_click=manager.handle_double_click)

    canvas = Img.create(1, 1)
    try:
        while True:
            manager.render(canvas)
            canvas.show_frame(WINDOW_NAME)

            key = Img.wait_key(16)
            if key == ESC_KEY:
                break
            if key != NO_KEY:
                manager.handle_key(key)
            if not Img.is_window_visible(WINDOW_NAME):
                break
    finally:
        session.close()
        Img.close_all_windows()


if __name__ == "__main__":  # pragma: no cover
    run_gui()
