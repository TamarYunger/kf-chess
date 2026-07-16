from config import settings
from main_gui import build_game, with_synced_rest_durations
from view.graphics_renderer import SIDE_PANEL_WIDTH


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


def test_build_game_threads_board_x_offset_into_the_board_mapper():
    # Regression: the board's on-screen position shifted right by
    # SIDE_PANEL_WIDTH once GraphicsRenderer started drawing a side panel
    # before it, but nothing told BoardMapper - every real click mapped to
    # the wrong cell. A click at the board's actual on-screen top-left
    # corner (where the wK sits below) must select it, not miss or select
    # some other cell.
    board_lines = ["wK . .", ". . .", ". . ."]
    engine, controller = build_game(board_lines, config=settings, board_x_offset=SIDE_PANEL_WIDTH)

    controller.click(SIDE_PANEL_WIDTH, 0)
    assert controller.selected == (0, 0)


def test_build_game_without_an_offset_maps_clicks_from_the_window_origin():
    board_lines = ["wK . .", ". . .", ". . ."]
    engine, controller = build_game(board_lines, config=settings)

    controller.click(0, 0)
    assert controller.selected == (0, 0)
