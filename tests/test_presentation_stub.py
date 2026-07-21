import logging

from bus.event_bus import EventBus
from game.presentation_stub import attach_presentation_stub


def test_placeholder_handlers_only_log_and_do_not_raise():
    bus = EventBus()
    attach_presentation_stub(bus)

    # Must not raise for any of the wired placeholder events, whatever the
    # payload shape - these are log-only stubs, not real reactions yet.
    bus.publish("game_started", {"colors": ("w", "b")})
    bus.publish("game_over", {"winner": "w"})
    bus.publish("score_changed", {"color": "w", "score": 3})
    bus.publish("move_log_updated", {"w": (), "b": ()})


def test_placeholder_handler_logs_the_event(caplog):
    bus = EventBus()
    attach_presentation_stub(bus)

    with caplog.at_level(logging.INFO, logger="game.presentation_stub"):
        bus.publish("game_over", {"winner": "b"})

    assert any("game_over" in record.message for record in caplog.records)


def test_every_placeholder_event_is_logged_when_published(caplog):
    bus = EventBus()
    attach_presentation_stub(bus)

    with caplog.at_level(logging.INFO, logger="game.presentation_stub"):
        bus.publish("game_started", {"colors": ("w", "b")})
        bus.publish("score_changed", {"color": "w", "score": 1})
        bus.publish("move_log_updated", {"w": (), "b": ()})
        bus.publish("game_over", {"winner": "w"})

    logged_prefixes = [record.message.split(":")[0] for record in caplog.records]
    assert logged_prefixes == ["game_started", "score_changed", "move_log_updated", "game_over"]
