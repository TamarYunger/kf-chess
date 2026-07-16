import pytest

from view.piece_assets import (
    token_to_folder,
    InvalidTokenError,
    load_state_config,
    load_all_piece_configs,
    sprite_path,
    STATE_NAMES,
)

ASSETS_ROOT = "assets/pieces"


def test_token_to_folder_reverses_color_and_kind():
    assert token_to_folder("wP") == "PW"
    assert token_to_folder("bK") == "KB"
    assert token_to_folder("wR") == "RW"


def test_token_to_folder_rejects_malformed_token():
    with pytest.raises(InvalidTokenError):
        token_to_folder("w")
    with pytest.raises(InvalidTokenError):
        token_to_folder("wPP")


def test_load_state_config_reads_fps_loop_and_next_state():
    cfg = load_state_config("PW", "move", ASSETS_ROOT)
    assert cfg.fps == 10
    assert cfg.is_loop is True
    assert cfg.next_state == "long_rest"


def test_load_state_config_discovers_frame_count_from_disk():
    import pathlib
    cfg = load_state_config("PW", "idle", ASSETS_ROOT)
    actual_files = list((pathlib.Path(ASSETS_ROOT) / "PW" / "states" / "idle" / "sprites").glob("*.png"))
    assert cfg.frame_count == len(actual_files)
    assert cfg.frame_count > 0


def test_load_all_piece_configs_discovers_every_piece_and_state():
    configs = load_all_piece_configs(ASSETS_ROOT)
    expected_folders = {"BB", "BW", "KB", "KW", "NB", "NW", "PB", "PW", "QB", "QW", "RB", "RW"}
    assert set(configs.keys()) == expected_folders
    for folder_configs in configs.values():
        assert set(folder_configs.keys()) == set(STATE_NAMES)


def test_sprite_path_is_one_indexed_on_disk():
    path = sprite_path("PW", "idle", 0, ASSETS_ROOT)
    assert path.name == "1.png"
    assert path.exists()
