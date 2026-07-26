from pathlib import Path

from bus.event_bus import EventBus
from realtime.real_time_arbiter import ArrivalEvent
from client.view.sound import CAPTURE_SOUND, GAME_OVER_SOUND, MOVE_SOUND, attach_sound


def make_bus_with_fake_sound(sounds_dir="assets/sounds"):
    played = []
    events = EventBus()
    attach_sound(events, sounds_dir=sounds_dir, play=lambda path: played.append(path))
    return events, played


def test_a_plain_move_arrival_plays_the_move_sound():
    events, played = make_bus_with_fake_sound()

    events.publish("arrival", ArrivalEvent(piece="wR", destination=(0, 2), captured=None))

    assert played == [Path("assets/sounds") / MOVE_SOUND]


def test_a_capturing_arrival_plays_the_capture_sound():
    events, played = make_bus_with_fake_sound()

    events.publish("arrival", ArrivalEvent(piece="wR", destination=(0, 2), captured="bK"))

    assert played == [Path("assets/sounds") / CAPTURE_SOUND]


def test_game_over_plays_the_game_over_sound():
    events, played = make_bus_with_fake_sound()

    events.publish("game_over", {"winner": "w"})

    assert played == [Path("assets/sounds") / GAME_OVER_SOUND]


def test_a_plain_move_arrival_plays_the_move_sound_over_the_network_too():
    # Once it's crossed the wire (server/protocol.py's encode_arrival,
    # decoded back into a dict by NetworkGameSession's generic
    # republish-by-type), the same event arrives here as a dict instead of
    # a real ArrivalEvent object - see _captured_of.
    events, played = make_bus_with_fake_sound()

    events.publish("arrival", {"piece": "wR", "destination": [0, 2], "captured": None})

    assert played == [Path("assets/sounds") / MOVE_SOUND]


def test_a_capturing_arrival_plays_the_capture_sound_over_the_network_too():
    events, played = make_bus_with_fake_sound()

    events.publish("arrival", {"piece": "wR", "destination": [0, 2], "captured": "bK"})

    assert played == [Path("assets/sounds") / CAPTURE_SOUND]


def test_sounds_directory_is_honored():
    events, played = make_bus_with_fake_sound(sounds_dir="somewhere/else")

    events.publish("arrival", ArrivalEvent(piece="wR", destination=(0, 2), captured=None))

    assert played == [Path("somewhere/else") / MOVE_SOUND]


def test_the_bundled_sound_files_actually_exist():
    from client.view.sound import SOUNDS_DIR
    assert (SOUNDS_DIR / MOVE_SOUND).exists()
    assert (SOUNDS_DIR / CAPTURE_SOUND).exists()
    assert (SOUNDS_DIR / GAME_OVER_SOUND).exists()
