from bus.event_bus import EventBus
from config import settings
from view.game_screen import GameScreen
from view.graphics_renderer import SIDE_PANEL_WIDTH
from view.img import Img
from view.snapshot_codec import snapshot_from_json


def minimal_json(**overrides):
    data = {
        "cells": [["wK", ".", "."], [".", ".", "."], [".", ".", "."]],
        "width": 3,
        "height": 3,
        "game_over": False,
    }
    data.update(overrides)
    return data


class FakeSession:
    """A minimal GameSession fake - no LocalGameSession/NetworkGameSession
    involved - so these tests exercise only GameScreen's own contract with
    GameSession, not either concrete implementation."""

    def __init__(self, snapshot=None):
        self._snapshot = snapshot
        self.commands = []

    def submit_command(self, command):
        self.commands.append(command)

    def latest_snapshot(self):
        return self._snapshot

    def close(self):
        pass


def test_renders_a_connecting_placeholder_when_the_session_has_no_snapshot_yet():
    screen = GameScreen(settings, FakeSession(snapshot=None), EventBus())
    canvas = Img.create(1, 1)

    screen.render(canvas)

    assert canvas.img is not None
    assert canvas.img.shape[0] > 1 and canvas.img.shape[1] > 1


def test_renders_the_board_once_the_session_has_a_snapshot():
    session = FakeSession(snapshot=snapshot_from_json(minimal_json()))
    screen = GameScreen(settings, session, EventBus())
    canvas = Img.create(1, 1)

    screen.render(canvas)

    # 3x3 board at settings.CELL_SIZE plus the two side panels.
    expected_w = 3 * settings.CELL_SIZE + 2 * SIDE_PANEL_WIDTH
    expected_h = 3 * settings.CELL_SIZE
    assert canvas.img.shape[1] == expected_w
    assert canvas.img.shape[0] == expected_h


def test_click_before_any_snapshot_submits_nothing():
    session = FakeSession(snapshot=None)
    screen = GameScreen(settings, session, EventBus())

    screen.handle_click(SIDE_PANEL_WIDTH, 0)  # no render() yet -> no cached snapshot

    assert session.commands == []


def test_click_on_the_board_submits_a_click_command_with_the_offset_applied():
    session = FakeSession(snapshot=snapshot_from_json(minimal_json()))
    screen = GameScreen(settings, session, EventBus(), board_x_offset=SIDE_PANEL_WIDTH)
    canvas = Img.create(1, 1)
    screen.render(canvas)  # caches the snapshot for bounds-checking

    # Top-left board cell (0, 0) sits at x == SIDE_PANEL_WIDTH on screen,
    # not x == 0 - the side panel is drawn first (mirrors the old
    # BoardMapper offset regression test).
    screen.handle_click(SIDE_PANEL_WIDTH, 0)

    assert session.commands == [{"type": "click", "cell": (0, 0)}]


def test_click_outside_the_board_submits_nothing():
    session = FakeSession(snapshot=snapshot_from_json(minimal_json()))
    screen = GameScreen(settings, session, EventBus(), board_x_offset=SIDE_PANEL_WIDTH)
    canvas = Img.create(1, 1)
    screen.render(canvas)

    screen.handle_click(0, 0)  # lands in the left side panel, not the board

    assert session.commands == []


def test_double_click_submits_a_jump_command():
    session = FakeSession(snapshot=snapshot_from_json(minimal_json()))
    screen = GameScreen(settings, session, EventBus(), board_x_offset=SIDE_PANEL_WIDTH)
    canvas = Img.create(1, 1)
    screen.render(canvas)

    screen.handle_double_click(SIDE_PANEL_WIDTH + settings.CELL_SIZE, settings.CELL_SIZE)

    assert session.commands == [{"type": "jump", "cell": (1, 1)}]


def test_click_below_the_board_bounds_submits_nothing():
    session = FakeSession(snapshot=snapshot_from_json(minimal_json()))
    screen = GameScreen(settings, session, EventBus(), board_x_offset=SIDE_PANEL_WIDTH)
    canvas = Img.create(1, 1)
    screen.render(canvas)

    screen.handle_click(SIDE_PANEL_WIDTH, 3 * settings.CELL_SIZE + 5)

    assert session.commands == []


def test_click_bounds_check_uses_the_snapshot_cached_at_the_last_render():
    # handle_click runs from the mouse callback, not the per-frame render
    # call - it must never call session.latest_snapshot() itself (that
    # would, for a LocalGameSession, advance the engine's clock from a
    # click instead of once per frame).
    session = FakeSession(snapshot=snapshot_from_json(minimal_json()))
    screen = GameScreen(settings, session, EventBus(), board_x_offset=SIDE_PANEL_WIDTH)
    canvas = Img.create(1, 1)
    screen.render(canvas)

    session._snapshot = None  # session moved on; screen must still use its cache
    screen.handle_click(SIDE_PANEL_WIDTH, 0)

    assert session.commands == [{"type": "click", "cell": (0, 0)}]


def test_opponent_disconnected_event_sets_a_countdown_deadline():
    events = EventBus()
    screen = GameScreen(settings, FakeSession(snapshot=None), events)

    events.publish("opponent_disconnected", {"color": "b", "grace_period_seconds": 20})

    assert screen._disconnect_deadline is not None


def test_disconnect_overlay_renders_without_raising():
    events = EventBus()
    session = FakeSession(snapshot=snapshot_from_json(minimal_json()))
    screen = GameScreen(settings, session, events, board_x_offset=SIDE_PANEL_WIDTH)
    events.publish("opponent_disconnected", {"color": "b", "grace_period_seconds": 20})
    canvas = Img.create(1, 1)

    screen.render(canvas)  # must not raise with the countdown overlay active


def test_opponent_reconnected_event_clears_the_countdown():
    events = EventBus()
    screen = GameScreen(settings, FakeSession(snapshot=None), events)
    events.publish("opponent_disconnected", {"color": "b", "grace_period_seconds": 20})

    events.publish("opponent_reconnected", {"color": "b"})

    assert screen._disconnect_deadline is None


def test_game_over_snapshot_suppresses_the_disconnect_overlay():
    # Once the snapshot itself reports game_over (e.g. the auto-resign
    # this countdown was heading toward), GraphicsRenderer's own game-over
    # banner takes over - the countdown overlay should not still draw on
    # top of it.
    events = EventBus()
    session = FakeSession(snapshot=snapshot_from_json(minimal_json(game_over=True, winner="w")))
    screen = GameScreen(settings, session, events, board_x_offset=SIDE_PANEL_WIDTH)
    events.publish("opponent_disconnected", {"color": "b", "grace_period_seconds": 20})
    canvas = Img.create(1, 1)

    screen.render(canvas)  # must not raise, and the countdown must not be drawn
