from config import settings
from bus.event_bus import EventBus
from main_gui import build_screens, build_session, run_gui
from client.session.local_game_session import LocalGameSession
from client.view.game_screen import GameScreen
from client.view.graphics_renderer import SIDE_PANEL_WIDTH


def test_build_session_returns_a_working_offline_session():
    events = EventBus()
    session = build_session(events, settings, board_lines=["wK . .", ". . .", ". . ."])

    assert isinstance(session, LocalGameSession)
    assert session.latest_snapshot().cells[0][0] == "wK"


def test_build_screens_starts_directly_on_game():
    # There's no server to log in to, so the game board is the very first
    # thing shown - no LOGIN screen.
    events = EventBus()
    session = build_session(events, settings, board_lines=["wK . .", ". . .", ". . ."])
    manager = build_screens(events, settings, session)

    assert manager.current_name == "GAME"
    assert isinstance(manager.current, GameScreen)


def test_build_screens_click_reaches_the_underlying_local_session():
    # End-to-end through the pieces main_gui.py actually wires together:
    # ScreenManager -> GameScreen -> GameSession -> GameEngine, entirely
    # offline. This is the click-mapping regression test that used to run
    # through build_game()/Controller/BoardMapper directly.
    events = EventBus()
    session = build_session(events, settings, board_lines=["wK . .", ". . .", ". . ."])
    manager = build_screens(events, settings, session)

    from client.view.img import Img
    canvas = Img.create(1, 1)
    manager.render(canvas)  # lets GameScreen cache a snapshot to bounds-check against

    manager.handle_click(SIDE_PANEL_WIDTH, 0)
    session.tick()

    assert session.latest_snapshot().selected == (0, 0)


def test_run_gui_wires_a_local_session_into_the_injected_run_app():
    # run_app is injectable precisely so this wiring (config sync, session/
    # screen construction) is testable without ever opening a real window -
    # see view/app_loop.run_app's own docstring.
    received = {}

    def fake_run_app(session, manager):
        received["session"] = session
        received["manager"] = manager

    run_gui(board_lines=["wK . .", ". . .", ". . ."], run_app=fake_run_app)

    assert isinstance(received["session"], LocalGameSession)
    assert received["manager"].current_name == "GAME"
