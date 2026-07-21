from bus.event_bus import EventBus


def test_subscriber_receives_the_published_payload():
    received = []
    bus = EventBus()
    bus.subscribe("score_changed", lambda payload: received.append(payload))

    bus.publish("score_changed", {"color": "w", "score": 3})

    assert received == [{"color": "w", "score": 3}]


def test_multiple_subscribers_all_receive_the_event():
    calls = []
    bus = EventBus()
    bus.subscribe("game_over", lambda payload: calls.append(("first", payload)))
    bus.subscribe("game_over", lambda payload: calls.append(("second", payload)))

    bus.publish("game_over", "b")

    assert calls == [("first", "b"), ("second", "b")]


def test_publish_with_no_subscribers_is_a_no_op():
    bus = EventBus()
    bus.publish("nobody_listening")  # must not raise


def test_publish_with_no_payload_passes_none():
    received = []
    bus = EventBus()
    bus.subscribe("ping", lambda payload: received.append(payload))

    bus.publish("ping")

    assert received == [None]


def test_subscriber_is_not_called_for_a_different_event_type():
    received = []
    bus = EventBus()
    bus.subscribe("score_changed", lambda payload: received.append(payload))

    bus.publish("game_over", "w")

    assert received == []


def test_subscribers_are_called_in_subscription_order():
    calls = []
    bus = EventBus()
    bus.subscribe("event", lambda payload: calls.append("first"))
    bus.subscribe("event", lambda payload: calls.append("second"))

    bus.publish("event")

    assert calls == ["first", "second"]
