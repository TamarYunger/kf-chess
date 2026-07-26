"""Shared plumbing for every graphical entry point (main_gui.py "Play
Offline", main_online.py "Play Online") - the window/render loop and the
one-time config setup neither needs to differ on. Building the right
GameSession and ScreenManager for its own mode is each entry point's own
job (see each module's own docstring); this only ever runs whatever
session/manager pair it's handed, so it never needs to know which one that
is - the same reason GameScreen itself doesn't (session/game_session.py).
"""
from __future__ import annotations

import logging
import types

from client.view.img import Img
from client.view.piece_assets import load_all_piece_configs, state_duration_ms

WINDOW_NAME = "KungFu Chess"

# cv2.waitKey's return value (Img.wait_key) when no key was pressed during
# the frame's delay window.
NO_KEY = 255
ESC_KEY = 27


def with_synced_rest_durations(config, project_root):
    """Overrides SHORT_REST_DURATION/LONG_REST_DURATION with the real
    short_rest/long_rest sprites' own playback duration (frame_count/fps),
    so the gameplay cooldown always exactly matches how long the rest
    animation actually plays - taking the max across piece kinds in case a
    future skin gives them differing lengths (today they're uniform).

    Copies every field from `config` (not a fixed whitelist) so any new
    config field added later reaches the GUI automatically, instead of
    silently being missing until someone remembers to list it here too.
    `project_root` is the caller's own directory (its assets live relative
    to itself, not to this shared module's location).
    """
    pieces_root = project_root / config.ASSETS_DIR / "pieces"
    piece_configs = load_all_piece_configs(pieces_root)
    short = max(state_duration_ms(cfgs["short_rest"]) for cfgs in piece_configs.values())
    long_ = max(state_duration_ms(cfgs["long_rest"]) for cfgs in piece_configs.values())
    overrides = {**vars(config), "SHORT_REST_DURATION": short, "LONG_REST_DURATION": long_}
    return types.SimpleNamespace(**overrides)


def configure_client_logging(log_path, level=logging.INFO):
    log_path.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
    )


def run_app(session, manager, window_name=WINDOW_NAME):  # pragma: no cover
    """Opens the window and drives the render loop until Escape, the
    window is closed, or the session is torn down - identical regardless
    of what kind of GameSession/ScreenManager it was handed.

    A real OS window and an unboundedly-running loop driven by cv2.waitKey
    - like view/img.py's own window methods, there's no logic of ours left
    to unit-test here without actually popping up a window, so it's
    excluded from coverage the same way. main_gui.py/main_online.py accept
    this function itself as an injectable `run_app` parameter, so their
    own wiring (config sync, session/screen construction) stays testable
    with a fake in its place.
    """
    Img.open_window(window_name)
    Img.set_mouse_callback(window_name, on_click=manager.handle_click, on_double_click=manager.handle_double_click)

    canvas = Img.create(1, 1)
    try:
        while True:
            # Exactly once per frame, regardless of which screen is
            # current - see GameSession.tick's own docstring for why this
            # can't live inside a Screen's render() instead (that's the
            # bug it replaced: a bus event published while LOGIN or HOME
            # was current never reached anyone, because nothing was
            # draining the session's queue).
            session.tick()
            manager.render(canvas)
            canvas.show_frame(window_name)

            key = Img.wait_key(16)
            if key == ESC_KEY:
                break
            if key != NO_KEY:
                manager.handle_key(key)
            if not Img.is_window_visible(window_name):
                break
    finally:
        session.close()
        Img.close_all_windows()
