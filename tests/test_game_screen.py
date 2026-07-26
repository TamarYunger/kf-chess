from bus.event_bus import EventBus
from config import settings
from client.session.snapshot_codec import snapshot_from_json
from client.view.game_screen import GameScreen
from client.view.graphics_renderer import SIDE_PANEL_WIDTH
from client.view.img import Img


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


def test_resign_event_records_the_resigning_color():
    events = EventBus()
    screen = GameScreen(settings, FakeSession(snapshot=None), events)

    events.publish("resign", {"color": "b"})

    assert screen._resigned_color == "b"


def test_resign_caption_renders_without_raising_once_the_game_is_over():
    events = EventBus()
    session = FakeSession(snapshot=snapshot_from_json(minimal_json(game_over=True, winner="w")))
    screen = GameScreen(settings, session, events, board_x_offset=SIDE_PANEL_WIDTH)
    events.publish("resign", {"color": "b"})
    canvas = Img.create(1, 1)

    screen.render(canvas)  # must not raise with the resign caption active


def test_resign_caption_is_not_drawn_before_the_snapshot_itself_reports_game_over():
    # The disconnect grace period's own countdown overlay is what shows
    # while a resign is still pending (see test_disconnect_overlay_renders_
    # without_raising) - the "resign" event can arrive before the snapshot
    # that reflects it (see server/room.py's own ordering: "resign" is
    # queued right before "game_over"), so the caption itself waits for
    # the snapshot to catch up instead of assuming payload order.
    events = EventBus()
    session = FakeSession(snapshot=snapshot_from_json(minimal_json(game_over=False)))
    screen = GameScreen(settings, session, events, board_x_offset=SIDE_PANEL_WIDTH)
    events.publish("resign", {"color": "b"})
    canvas = Img.create(1, 1)

    screen.render(canvas)  # must not raise while the snapshot still lags behind


def test_waiting_for_opponent_event_blocks_clicks_and_renders_without_raising():
    events = EventBus()
    session = FakeSession(snapshot=snapshot_from_json(minimal_json()))
    screen = GameScreen(settings, session, events, board_x_offset=SIDE_PANEL_WIDTH)
    events.publish("room", {"room_id": "abc123", "role": "w"})
    events.publish("waiting_for_opponent", None)
    canvas = Img.create(1, 1)

    screen.render(canvas)  # must not raise, with the waiting overlay drawn
    screen.handle_click(SIDE_PANEL_WIDTH, 0)
    screen.handle_double_click(SIDE_PANEL_WIDTH, 0)

    assert session.commands == []  # a lone creator can't move yet either


def test_room_started_event_clears_the_waiting_state_and_allows_clicks():
    events = EventBus()
    session = FakeSession(snapshot=snapshot_from_json(minimal_json()))
    screen = GameScreen(settings, session, events, board_x_offset=SIDE_PANEL_WIDTH)
    events.publish("room", {"room_id": "abc123", "role": "w"})
    events.publish("waiting_for_opponent", None)
    canvas = Img.create(1, 1)
    screen.render(canvas)  # caches a snapshot to bounds-check clicks against

    events.publish("room_started", None)

    assert screen._waiting_for_opponent is False
    screen.handle_click(SIDE_PANEL_WIDTH, 0)
    assert session.commands == [{"type": "click", "cell": (0, 0)}]


def test_room_event_is_stored_and_rendered_without_raising():
    events = EventBus()
    session = FakeSession(snapshot=snapshot_from_json(minimal_json()))
    screen = GameScreen(settings, session, events, board_x_offset=SIDE_PANEL_WIDTH)

    events.publish("room", {"room_id": "abc123", "role": "w"})
    canvas = Img.create(1, 1)
    screen.render(canvas)  # must not raise, with the header drawn

    assert screen._room_id == "abc123"
    assert screen._role == "w"


def test_seated_role_can_click_and_double_click():
    events = EventBus()
    session = FakeSession(snapshot=snapshot_from_json(minimal_json()))
    screen = GameScreen(settings, session, events, board_x_offset=SIDE_PANEL_WIDTH)
    events.publish("room", {"room_id": "abc123", "role": "w"})
    canvas = Img.create(1, 1)
    screen.render(canvas)

    screen.handle_click(SIDE_PANEL_WIDTH, 0)
    screen.handle_double_click(SIDE_PANEL_WIDTH, 0)

    assert session.commands == [{"type": "click", "cell": (0, 0)}, {"type": "jump", "cell": (0, 0)}]


def test_viewer_role_click_submits_nothing():
    events = EventBus()
    session = FakeSession(snapshot=snapshot_from_json(minimal_json()))
    screen = GameScreen(settings, session, events, board_x_offset=SIDE_PANEL_WIDTH)
    events.publish("room", {"room_id": "abc123", "role": "viewer"})
    canvas = Img.create(1, 1)
    screen.render(canvas)

    screen.handle_click(SIDE_PANEL_WIDTH, 0)

    assert session.commands == []


def test_viewer_role_double_click_submits_nothing():
    events = EventBus()
    session = FakeSession(snapshot=snapshot_from_json(minimal_json()))
    screen = GameScreen(settings, session, events, board_x_offset=SIDE_PANEL_WIDTH)
    events.publish("room", {"room_id": "abc123", "role": "viewer"})
    canvas = Img.create(1, 1)
    screen.render(canvas)

    screen.handle_double_click(SIDE_PANEL_WIDTH, 0)

    assert session.commands == []


def test_no_room_yet_still_allows_clicks_local_play_style():
    # Before any "room" event has arrived (e.g. LocalGameSession, which
    # never publishes one), self._role stays None - clicks must still work,
    # exactly like offline play always has.
    events = EventBus()
    session = FakeSession(snapshot=snapshot_from_json(minimal_json()))
    screen = GameScreen(settings, session, events, board_x_offset=SIDE_PANEL_WIDTH)
    canvas = Img.create(1, 1)
    screen.render(canvas)

    screen.handle_click(SIDE_PANEL_WIDTH, 0)

    assert session.commands == [{"type": "click", "cell": (0, 0)}]
