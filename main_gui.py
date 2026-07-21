"""KungFu Chess - interactive graphical entry point.

A thin network client: it owns no GameEngine/Board/rules of its own (that
lives server-side, the same wiring main.py's run() still shows for a local/
batch path). A NetworkClient runs the actual WebSocket connection on a
background thread - the render loop itself is synchronous, driven by
cv2.waitKey, and must never block on network I/O - and every message that
arrives is drained non-blockingly once per frame, then republished on an
EventBus. That bus is also what drives screen transitions (see
view/screen_manager.py): adding a new screen or a new server message type
never touches this loop.
"""
import types
from pathlib import Path

from bus.event_bus import EventBus
from config import settings
from view.game_screen import GameScreen
from view.graphics_renderer import SIDE_PANEL_WIDTH
from view.img import Img
from view.network_client import NetworkClient
from view.piece_assets import load_all_piece_configs, state_duration_ms
from view.screen_manager import ScreenManager

PROJECT_ROOT = Path(__file__).resolve().parent
WINDOW_NAME = "KungFu Chess"
DEFAULT_SERVER_URL = "ws://localhost:8765"

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


def build_screens(events, config, send):
    """Wires every known screen into a ScreenManager. Only GAME exists so
    far - LOGIN/HOME/ROOM_DIALOG land in a later step, each registered here
    the same way, with its own bus-driven `transitions=` mapping."""
    manager = ScreenManager(events, initial="GAME")
    game_screen = GameScreen(config, send, board_x_offset=SIDE_PANEL_WIDTH)
    events.subscribe("snapshot", game_screen.update_snapshot)
    manager.register("GAME", game_screen)
    return manager


def run_gui(server_url=DEFAULT_SERVER_URL, config=settings):
    config = with_synced_rest_durations(config)
    events = EventBus()
    network = NetworkClient(server_url)
    manager = build_screens(events, config, send=network.send)

    network.start()
    Img.open_window(WINDOW_NAME)
    Img.set_mouse_callback(WINDOW_NAME, on_click=manager.handle_click, on_double_click=manager.handle_double_click)

    canvas = Img.create(1, 1)
    try:
        while True:
            for message in network.drain():
                events.publish(message["type"], message.get("payload"))

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
        network.stop()
        Img.close_all_windows()


if __name__ == "__main__":  # pragma: no cover
    run_gui()
