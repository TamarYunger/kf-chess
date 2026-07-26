"""KungFu Chess - offline entry point ("Play Offline"): wires a
LocalGameSession straight into GameScreen, no server or network involved
at all - hotseat, both colors played from this one window.

main_online.py is the networked counterpart (LOGIN -> HOME -> PLAY/ROOM ->
GAME, talking to a real server). The two don't share a process or a mode
flag - each is its own composition root - but both share view/app_loop.py's
window/render loop and config-setup helpers instead of duplicating them,
and both hand the exact same GameScreen a GameSession it can't tell apart
from the other's (session/game_session.py) - see GameSession's own
docstring for why that's what lets GameScreen itself stay unaware of which
one it's ever built with.
"""
from pathlib import Path

from bus.event_bus import EventBus
from config import settings
from client.session.local_game_session import LocalGameSession
from client.view.app_loop import configure_client_logging, run_app, with_synced_rest_durations
from client.view.game_screen import GameScreen
from client.view.graphics_renderer import SIDE_PANEL_WIDTH
from client.view.screen_manager import ScreenManager
from client.view.sound import attach_sound

PROJECT_ROOT = Path(__file__).resolve().parent
CLIENT_LOG_PATH = PROJECT_ROOT / "logs" / "client.log"

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


def build_session(events, config, board_lines=None):
    attach_sound(events)
    return LocalGameSession(board_lines or STANDARD_BOARD_TEXT, config, events=events)


def build_screens(events, config, session):
    """No one to log in to, let alone matchmake or room with - the board
    is the only screen this path ever shows."""
    manager = ScreenManager(events, initial="GAME")
    manager.register("GAME", GameScreen(config, session, events, board_x_offset=SIDE_PANEL_WIDTH))
    return manager


def run_gui(board_lines=None, config=settings, run_app=run_app):
    # run_app is injectable (defaulting to the real window/render loop) so
    # this function's own wiring - config sync, session/screen construction
    # - stays testable with a fake in its place, without ever opening a
    # real window (see view/app_loop.run_app's own docstring).
    configure_client_logging(CLIENT_LOG_PATH)
    config = with_synced_rest_durations(config, PROJECT_ROOT)
    events = EventBus()
    session = build_session(events, config, board_lines=board_lines)
    manager = build_screens(events, config, session)
    run_app(session, manager)


if __name__ == "__main__":  # pragma: no cover
    run_gui()
