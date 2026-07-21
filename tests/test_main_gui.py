from config import settings
from bus.event_bus import EventBus
from main_gui import build_screens, with_synced_rest_durations
from view.game_screen import GameScreen


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


# Pixel-to-cell mapping (including the SIDE_PANEL_WIDTH offset) now lives on
# GameScreen, not a locally-built BoardMapper - see tests/test_game_screen.py
# for the regression this file used to cover via build_game().


def test_build_screens_registers_game_as_the_initial_screen():
    events = EventBus()
    manager = build_screens(events, settings, send=lambda message: None)

    assert manager.current_name == "GAME"
    assert isinstance(manager.current, GameScreen)


def test_build_screens_wires_snapshot_events_to_the_game_screen():
    # The bridge from network messages to screen state: main_gui.py's loop
    # republishes every incoming message on the bus by its "type" - this
    # confirms a "snapshot" event actually reaches GameScreen.update_snapshot
    # without main_gui.py wiring GameEngine or the codec itself.
    events = EventBus()
    manager = build_screens(events, settings, send=lambda message: None)

    events.publish("snapshot", {
        "cells": [["wK", ".", "."], [".", ".", "."], [".", ".", "."]],
        "width": 3, "height": 3, "game_over": False,
    })

    assert manager.current._snapshot is not None
    assert manager.current._snapshot.width == 3


def test_build_screens_forwards_clicks_to_the_network_send_callback():
    sent = []
    events = EventBus()
    manager = build_screens(events, settings, send=sent.append)
    events.publish("snapshot", {
        "cells": [["wK", ".", "."], [".", ".", "."], [".", ".", "."]],
        "width": 3, "height": 3, "game_over": False,
    })

    from view.graphics_renderer import SIDE_PANEL_WIDTH
    manager.handle_click(SIDE_PANEL_WIDTH, 0)

    assert sent == [{"type": "select_or_move", "cell": [0, 0]}]
