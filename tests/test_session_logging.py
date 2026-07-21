import logging

from bus.event_bus import EventBus
from view.session_logging import attach_session_logging


def test_logged_events_do_not_raise_for_any_payload_shape():
    events = EventBus()
    attach_session_logging(events)

    events.publish("login", {"username": "alice", "rating": 1200})
    events.publish("login_rejected", {"message": "Invalid password"})
    events.publish("room", {"room_id": "abc123", "role": "w"})
    events.publish("no_match", None)
    events.publish("opponent_disconnected", {"color": "b", "grace_period_seconds": 20})
    events.publish("opponent_reconnected", {"color": "b"})
    events.publish("resign", {"color": "b"})
    events.publish("rejected", {"reason": "busy_source"})
    events.publish("error", {"message": "Not in a room"})
    events.publish("connected", None)
    events.publish("disconnected", None)
    events.publish("connection_error", {"error": "boom"})


def test_login_event_is_logged(caplog):
    events = EventBus()
    attach_session_logging(events)

    with caplog.at_level(logging.INFO, logger="view.session_logging"):
        events.publish("login", {"username": "alice", "rating": 1200})

    assert any("login" in record.message and "alice" in record.message for record in caplog.records)


def test_room_and_viewer_rejection_events_are_logged(caplog):
    events = EventBus()
    attach_session_logging(events)

    with caplog.at_level(logging.INFO, logger="view.session_logging"):
        events.publish("room", {"room_id": "abc123", "role": "viewer"})
        events.publish("error", {"message": "Only seated players can make moves"})

    messages = [record.message for record in caplog.records]
    assert any("room" in m and "abc123" in m for m in messages)
    assert any("error" in m and "seated" in m for m in messages)


def test_unrelated_event_types_are_not_logged(caplog):
    events = EventBus()
    attach_session_logging(events)

    with caplog.at_level(logging.INFO, logger="view.session_logging"):
        events.publish("score_changed", {"color": "w", "score": 3})

    assert caplog.records == []
