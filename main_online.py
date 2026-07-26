"""KungFu Chess - online entry point: LOGIN -> HOME -> PLAY/ROOM -> GAME,
wiring a NetworkGameSession that talks to a real server over WebSocket.

main_gui.py is the offline counterpart (see its own docstring for why the
two share view/app_loop.py's window/render loop instead of duplicating it,
and both hand the exact same GameScreen a GameSession it can't tell apart
from the other's).

The actual WebSocket connection - and the asyncio event loop it needs -
lives on its own background thread (this render loop is synchronous,
driven by cv2.waitKey, and must never block on network I/O); see
session/network_client.py.
"""
from pathlib import Path

from bus.event_bus import EventBus
from config import settings
from client.session.network_game_session import NetworkGameSession
from client.session.session_logging import attach_session_logging
from client.view.app_loop import configure_client_logging, run_app, with_synced_rest_durations
from client.view.game_screen import GameScreen
from client.view.graphics_renderer import SIDE_PANEL_WIDTH
from client.view.screen_manager import ScreenManager
from client.view.screens.home_screen import HomeScreen
from client.view.screens.login_screen import LoginScreen
from client.view.sound import attach_sound

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SERVER_URL = "ws://localhost:8765"
CLIENT_LOG_PATH = PROJECT_ROOT / "logs" / "client.log"


def build_session(events, server_url):
    attach_sound(events)
    return NetworkGameSession(server_url, events)


def build_screens(events, config, session):
    """Starts on LOGIN: a successful LOGIN moves on to HOME ("login"
    event) - it only authenticates, it doesn't put anyone in a room - and
    HOME's "Play" button (server.matchmaking) or its "Room" dialog's
    Create/Join (view/screens/room_dialog.py) both only reach GAME once
    the server actually seats this connection somewhere - PLAY's match and
    ROOM CREATE/JOIN end up publishing the exact same "room" event
    (server.room.Room), so one transition covers both. Every one of these
    transitions is ScreenManager's own `transitions=` wiring, not an
    if/else here or in the render loop.
    """
    manager = ScreenManager(events, initial="LOGIN")
    manager.register("GAME", GameScreen(config, session, events, board_x_offset=SIDE_PANEL_WIDTH))
    manager.register("LOGIN", LoginScreen(session, events), transitions={"login": "HOME"})
    manager.register("HOME", HomeScreen(session, events), transitions={"room": "GAME"})
    return manager


def run_gui(server_url=DEFAULT_SERVER_URL, config=settings, run_app=run_app):
    # run_app is injectable (defaulting to the real window/render loop) so
    # this function's own wiring - config sync, session/screen construction
    # - stays testable with a fake in its place, without ever opening a
    # real window (see view/app_loop.run_app's own docstring).
    configure_client_logging(CLIENT_LOG_PATH)
    config = with_synced_rest_durations(config, PROJECT_ROOT)
    events = EventBus()
    attach_session_logging(events)
    session = build_session(events, server_url)
    manager = build_screens(events, config, session)
    run_app(session, manager)


if __name__ == "__main__":  # pragma: no cover
    run_gui()
