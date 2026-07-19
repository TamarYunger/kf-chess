from game.events import EventBus


def test_subscriber_receives_published_args():
    received = []
    bus = EventBus()
    bus.subscribe("score_changed", lambda *args: received.append(args))

    bus.publish("score_changed", "w", 3)

    assert received == [("w", 3)]


def test_multiple_subscribers_all_receive_the_event():
    calls = []
    bus = EventBus()
    bus.subscribe("game_over", lambda winner: calls.append(("first", winner)))
    bus.subscribe("game_over", lambda winner: calls.append(("second", winner)))

    bus.publish("game_over", "b")

    assert calls == [("first", "b"), ("second", "b")]


def test_publish_with_no_subscribers_is_a_no_op():
    bus = EventBus()
    bus.publish("nobody_listening")  # must not raise


def test_subscriber_is_not_called_for_a_different_event_name():
    received = []
    bus = EventBus()
    bus.subscribe("score_changed", lambda *args: received.append(args))

    bus.publish("game_over", "w")

    assert received == []
