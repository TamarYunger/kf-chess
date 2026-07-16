from config import settings
from main_gui import with_synced_rest_durations


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
