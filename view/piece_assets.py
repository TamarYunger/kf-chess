from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

STATE_NAMES = ("idle", "move", "jump", "short_rest", "long_rest")


class InvalidTokenError(Exception):
    pass


def token_to_folder(token):
    """Board tokens are colour+kind (e.g. "wP"); asset folders are the
    opposite order, kind+colour (e.g. "PW"), matching the reference asset
    pack. This is the one seam that bridges the two conventions."""
    if len(token) != 2:
        raise InvalidTokenError(token)
    color, kind = token[0], token[1]
    return kind.upper() + color.upper()


@dataclass(frozen=True)
class StateConfig:
    fps: float
    is_loop: bool
    next_state: str
    frame_count: int


def load_state_config(folder, state, assets_root):
    state_dir = Path(assets_root) / folder / "states" / state
    with open(state_dir / "config.json", encoding="utf-8") as f:
        data = json.load(f)

    frame_count = len(list((state_dir / "sprites").glob("*.png")))
    return StateConfig(
        fps=data["graphics"]["frames_per_sec"],
        is_loop=data["graphics"]["is_loop"],
        next_state=data["physics"]["next_state_when_finished"],
        frame_count=frame_count,
    )


def load_all_piece_configs(assets_root):
    """Discovers piece folders from the assets directory itself, rather than
    a hardcoded token list, so a new piece kind's assets are picked up
    without a code change (mirrors PieceRuleRegistry.registered_kinds())."""
    assets_root = Path(assets_root)
    configs = {}
    for folder_path in sorted(assets_root.iterdir()):
        if not folder_path.is_dir():
            continue
        folder = folder_path.name
        configs[folder] = {
            state: load_state_config(folder, state, assets_root)
            for state in STATE_NAMES
        }
    return configs


def sprite_path(folder, state, frame_index, assets_root):
    return Path(assets_root) / folder / "states" / state / "sprites" / f"{frame_index + 1}.png"
