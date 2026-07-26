from config import settings
from bus.event_bus import EventBus
from main_online import build_screens, build_session, run_gui
from client.session.network_game_session import NetworkGameSession
from client.view.screens.login_screen import LoginScreen


def test_build_session_returns_a_network_session_without_connecting_yet():
    events = EventBus()
    session = build_session(events, server_url="ws://127.0.0.1:1")

    try:
        assert isinstance(session, NetworkGameSession)
        # No server is actually listening - this must not raise; the
        # session just has no snapshot yet.
        assert session.latest_snapshot() is None
    finally:
        session.close()


def test_build_screens_starts_on_login():
    events = EventBus()
    session = build_session(events, server_url="ws://127.0.0.1:1")

    try:
        manager = build_screens(events, settings, session)
        assert manager.current_name == "LOGIN"
        assert isinstance(manager.current, LoginScreen)
    finally:
        session.close()


def test_build_screens_moves_to_home_once_the_bus_reports_a_login():
    # ScreenManager's own transitions= wiring is what does this - nothing
    # in the render loop branches on "did login succeed". LOGIN only
    # authenticates - it doesn't seat a color - so it lands on HOME, not
    # straight into GAME.
    events = EventBus()
    session = build_session(events, server_url="ws://127.0.0.1:1")

    try:
        manager = build_screens(events, settings, session)
        events.publish("login", {"username": "alice", "rating": 1200})

        assert manager.current_name == "HOME"
    finally:
        session.close()


def test_build_screens_moves_to_game_once_the_bus_reports_a_room():
    # PLAY's match and ROOM CREATE/JOIN both end up publishing the same
    # "room" event - one transition covers both.
    events = EventBus()
    session = build_session(events, server_url="ws://127.0.0.1:1")

    try:
        manager = build_screens(events, settings, session)
        events.publish("login", {"username": "alice", "rating": 1200})
        events.publish("room", {"room_id": "abc123", "role": "w"})

        assert manager.current_name == "GAME"
    finally:
        session.close()


def test_run_gui_wires_a_network_session_into_the_injected_run_app():
    # run_app is injectable precisely so this wiring (config sync, session/
    # screen construction) is testable without ever opening a real window -
    # see view/app_loop.run_app's own docstring.
    received = {}

    def fake_run_app(session, manager):
        received["session"] = session
        received["manager"] = manager
        session.close()

    run_gui(server_url="ws://127.0.0.1:1", run_app=fake_run_app)

    assert isinstance(received["session"], NetworkGameSession)
    assert received["manager"].current_name == "LOGIN"
