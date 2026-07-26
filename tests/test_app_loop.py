from pathlib import Path

from config import settings
from client.view.app_loop import configure_client_logging, with_synced_rest_durations

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_with_synced_rest_durations_carries_every_config_field():
    # Regression test: with_synced_rest_durations used to rebuild the config
    # from a fixed field whitelist, so any new field added to config/settings
    # (e.g. PIECE_VALUES) was silently missing from the GUI's config until
    # someone remembered to list it here too - only crashing once actually
    # run through a real entry point, invisible to every other test.
    result = with_synced_rest_durations(settings, PROJECT_ROOT)

    assert result.PIECE_VALUES == settings.PIECE_VALUES
    assert result.COLORS == settings.COLORS
    assert result.ASSETS_DIR == settings.ASSETS_DIR


def test_with_synced_rest_durations_overrides_rest_durations():
    result = with_synced_rest_durations(settings, PROJECT_ROOT)

    assert isinstance(result.SHORT_REST_DURATION, (int, float))
    assert isinstance(result.LONG_REST_DURATION, (int, float))


def test_configure_client_logging_creates_the_log_directory_and_file(tmp_path):
    log_path = tmp_path / "logs" / "client.log"

    configure_client_logging(log_path)

    assert log_path.parent.is_dir()
    assert log_path.exists()
