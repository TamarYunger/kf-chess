import pytest

from config import settings
from bus.event_bus import EventBus
from main_gui import build_screens, build_session, with_synced_rest_durations
from view.game_screen import GameScreen
from view.graphics_renderer import SIDE_PANEL_WIDTH
from view.local_game_session import LocalGameSession
from view.network_game_session import NetworkGameSession
from view.screens.login_screen import LoginScreen


def test_with_synced_rest_durations_carries_every_config_field():
    # Regression test: with_synced_rest_durations used to rebuild the config
    # from a fixed field whitelist, so any new field added to config/settings
    # (e.g. PIECE_VALUES) was silently missing from the GUI's config until
    # someone remembered to list it here too - only crashing once actually
    # run through main_gui.py, invisible to every other test.
    result = with_synced_rest_durations(settings)

    assert result.PIECE_VALUES == settings.PIECE_VALUES
    assert result.COLORS == settings.COLORS
    assert result.ASSETS_DIR == settings.ASSETS_DIR


def test_with_synced_rest_durations_overrides_rest_durations():
    result = with_synced_rest_durations(settings)

    assert isinstance(result.SHORT_REST_DURATION, (int, float))
    assert isinstance(result.LONG_REST_DURATION, (int, float))


def test_build_session_local_mode_returns_a_working_offline_session():
    # The point of "mode" defaulting to "local": main_gui.py must still be
    # able to run a full game with no server involved at all.
    events = EventBus()
    session = build_session("local", events, settings, board_lines=["wK . .", ". . .", ". . ."])

    assert isinstance(session, LocalGameSession)
    assert session.latest_snapshot().cells[0][0] == "wK"


def test_build_session_network_mode_returns_a_network_session_without_connecting_yet():
    events = EventBus()
    session = build_session("network", events, settings, server_url="ws://127.0.0.1:1")

    try:
        assert isinstance(session, NetworkGameSession)
        # No server is actually listening - this must not raise; the
        # session just has no snapshot yet.
        assert session.latest_snapshot() is None
    finally:
        session.close()


def test_build_session_rejects_an_unknown_mode():
    events = EventBus()
    with pytest.raises(ValueError):
        build_session("bogus", events, settings)


def test_build_screens_local_mode_starts_directly_on_game():
    # "Play Offline" (mode="local"): there's no server to log in to, so
    # the game board is the very first thing shown - no LOGIN screen.
    events = EventBus()
    session = build_session("local", events, settings, board_lines=["wK . .", ". . .", ". . ."])
    manager = build_screens(events, settings, session, "local")

    assert manager.current_name == "GAME"
    assert isinstance(manager.current, GameScreen)


def test_build_screens_click_reaches_the_underlying_local_session():
    # End-to-end through the pieces main_gui.py actually wires together:
    # ScreenManager -> GameScreen -> GameSession -> GameEngine, entirely
    # offline. This is the click-mapping regression test that used to run
    # through build_game()/Controller/BoardMapper directly.
    events = EventBus()
    session = build_session("local", events, settings, board_lines=["wK . .", ". . .", ". . ."])
    manager = build_screens(events, settings, session, "local")

    from view.img import Img
    canvas = Img.create(1, 1)
    manager.render(canvas)  # lets GameScreen cache a snapshot to bounds-check against

    manager.handle_click(SIDE_PANEL_WIDTH, 0)

    assert session.latest_snapshot().selected == (0, 0)


def test_build_screens_network_mode_starts_on_login():
    events = EventBus()
    session = build_session("network", events, settings, server_url="ws://127.0.0.1:1")

    try:
        manager = build_screens(events, settings, session, "network")
        assert manager.current_name == "LOGIN"
        assert isinstance(manager.current, LoginScreen)
    finally:
        session.close()


def test_build_screens_network_mode_moves_to_game_once_the_bus_reports_a_login():
    # ScreenManager's own transitions= wiring is what does this - nothing
    # in main_gui.py's render loop branches on "did login succeed".
    events = EventBus()
    session = build_session("network", events, settings, server_url="ws://127.0.0.1:1")

    try:
        manager = build_screens(events, settings, session, "network")
        events.publish("login", {"color": "w", "username": "alice"})

        assert manager.current_name == "GAME"
    finally:
        session.close()
