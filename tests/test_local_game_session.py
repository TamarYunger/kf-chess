import time

from config import settings
from bus.event_bus import EventBus
from view.local_game_session import LocalGameSession


def make_session(board_lines, config=settings, events=None):
    return LocalGameSession(board_lines, config, events=events)


def test_latest_snapshot_reflects_the_starting_board():
    # Available immediately, even before the first tick() - matches
    # NetworkGameSession only ever being None before its first message,
    # never for a local session (see LocalGameSession's own docstring).
    session = make_session(["wK . .", ". . .", ". . ."])

    snapshot = session.latest_snapshot()

    assert snapshot.cells == (("wK", ".", "."), (".", ".", "."), (".", ".", "."))
    assert snapshot.selected is None


def test_first_click_selects_the_piece_at_that_cell():
    session = make_session(["wK . .", ". . .", ". . ."])

    session.submit_command({"type": "click", "cell": (0, 0)})
    session.tick()

    assert session.latest_snapshot().selected == (0, 0)


def test_second_click_requests_a_move_and_clears_selection():
    session = make_session(["wR . .", ". . .", ". . ."])

    session.submit_command({"type": "click", "cell": (0, 0)})
    session.submit_command({"type": "click", "cell": (0, 2)})
    session.tick()

    snapshot = session.latest_snapshot()
    assert snapshot.selected is None
    # The rook hasn't arrived yet (MOVE_DURATION hasn't elapsed) - it's an
    # in-flight move, not yet reflected in `cells`.
    assert snapshot.cells[0][0] == "wR"


def test_waiting_lets_a_move_land():
    session = make_session(["wR . .", ". . .", ". . ."])
    session.submit_command({"type": "click", "cell": (0, 0)})
    session.submit_command({"type": "click", "cell": (0, 2)})

    # tick() advances the session's own clock by real elapsed time each
    # call - simulate that by calling it repeatedly until the move's
    # duration has plausibly elapsed rather than sleeping the full
    # 2 * MOVE_DURATION wall-clock seconds.
    deadline = time.time() + (2 * settings.MOVE_DURATION) / 1000 + 0.5
    session.tick()
    snapshot = session.latest_snapshot()
    while snapshot.cells[0][2] != "wR" and time.time() < deadline:
        time.sleep(0.05)
        session.tick()
        snapshot = session.latest_snapshot()

    assert snapshot.cells[0][2] == "wR"
    assert snapshot.cells[0][0] == "."


def test_selecting_a_piece_reports_its_legal_destinations():
    session = make_session(["wR . .", ". . .", ". . ."])

    session.submit_command({"type": "click", "cell": (0, 0)})
    session.tick()

    assert (0, 2) in session.latest_snapshot().legal_destinations


def test_illegal_move_sets_a_rejection_reason():
    session = make_session(["wN . .", ". . .", ". . ."])

    session.submit_command({"type": "click", "cell": (0, 0)})
    session.submit_command({"type": "click", "cell": (0, 1)})  # not a legal knight move
    session.tick()

    assert session.latest_snapshot().rejection_reason is not None


def test_jump_command_does_not_require_a_prior_selection():
    session = make_session(["wR . .", ". . .", ". . ."])

    session.submit_command({"type": "jump", "cell": (0, 0)})
    session.tick()

    # A jump doesn't raise and doesn't leave anything selected.
    assert session.latest_snapshot().selected is None


def test_local_session_publishes_engine_events_on_the_injected_bus():
    events = EventBus()
    received = []
    events.subscribe("game_started", lambda payload: received.append(payload))

    make_session(["wK . .", ". . .", ". . ."], events=events)

    assert len(received) == 1
