from bus.event_bus import EventBus
from view.img import Img
from view.screens.home_screen import (
    BUTTON_HEIGHT, BUTTON_WIDTH, PLAY_BUTTON_X, PLAY_BUTTON_Y, ROOM_BUTTON_X, ROOM_BUTTON_Y, HomeScreen,
)
from view.screens.room_dialog import (
    BUTTON_HEIGHT as ROOM_BUTTON_HEIGHT, BUTTON_WIDTH as ROOM_BUTTON_WIDTH,
    BUTTON_Y as ROOM_DIALOG_BUTTON_Y, CANCEL_BUTTON_X, CREATE_BUTTON_X, JOIN_BUTTON_X,
)


class FakeSession:
    def __init__(self):
        self.commands = []

    def submit_command(self, command):
        self.commands.append(command)

    def latest_snapshot(self):
        return None

    def close(self):
        pass


def make_screen():
    events = EventBus()
    session = FakeSession()
    screen = HomeScreen(session, events)
    return screen, session, events


def button_center():
    return PLAY_BUTTON_X + BUTTON_WIDTH // 2, PLAY_BUTTON_Y + BUTTON_HEIGHT // 2


def room_dialog_button_center(button_x):
    return button_x + ROOM_BUTTON_WIDTH // 2, ROOM_DIALOG_BUTTON_Y + ROOM_BUTTON_HEIGHT // 2


def test_render_does_not_raise_before_any_input():
    screen, session, events = make_screen()
    canvas = Img.create(1, 1)

    screen.render(canvas)

    assert canvas.img.shape[0] > 1 and canvas.img.shape[1] > 1


def test_clicking_play_sends_play_and_starts_searching():
    screen, session, events = make_screen()

    screen.handle_click(*button_center())

    assert session.commands == ["PLAY"]
    assert screen._searching_since is not None


def test_clicking_outside_the_button_does_nothing():
    screen, session, events = make_screen()

    screen.handle_click(0, 0)

    assert session.commands == []
    assert screen._searching_since is None


def test_clicking_play_again_while_searching_does_not_resend():
    screen, session, events = make_screen()
    screen.handle_click(*button_center())

    screen.handle_click(*button_center())  # same spot - but not clickable while searching

    assert session.commands == ["PLAY"]


def test_render_while_searching_does_not_raise():
    screen, session, events = make_screen()
    screen.handle_click(*button_center())
    canvas = Img.create(1, 1)

    screen.render(canvas)  # dim overlay + elapsed-time text


def test_no_match_event_stops_searching_and_sets_the_flag():
    screen, session, events = make_screen()
    screen.handle_click(*button_center())

    events.publish("no_match", None)

    assert screen._searching_since is None
    assert screen._no_match is True


def test_render_after_no_match_does_not_raise_and_button_is_clickable_again():
    screen, session, events = make_screen()
    screen.handle_click(*button_center())
    events.publish("no_match", None)
    canvas = Img.create(1, 1)

    screen.render(canvas)
    screen.handle_click(*button_center())  # can search again

    assert session.commands == ["PLAY", "PLAY"]


def test_starting_a_new_search_clears_a_stale_no_match_flag():
    screen, session, events = make_screen()
    screen.handle_click(*button_center())
    events.publish("no_match", None)

    screen.handle_click(*button_center())

    assert screen._no_match is False


def test_on_enter_resets_searching_and_no_match_state():
    screen, session, events = make_screen()
    screen.handle_click(*button_center())
    events.publish("no_match", None)

    screen.on_enter()

    assert screen._searching_since is None
    assert screen._no_match is False


def room_button_center():
    return ROOM_BUTTON_X + BUTTON_WIDTH // 2, ROOM_BUTTON_Y + BUTTON_HEIGHT // 2


def test_clicking_room_opens_the_dialog():
    screen, session, events = make_screen()

    screen.handle_click(*room_button_center())

    assert screen._room_dialog.is_open is True
    assert session.commands == []


def test_room_dialog_create_sends_room_create_and_closes():
    screen, session, events = make_screen()
    screen.handle_click(*room_button_center())

    screen.handle_click(*room_dialog_button_center(CREATE_BUTTON_X))

    assert session.commands == ["ROOM CREATE"]
    assert screen._room_dialog.is_open is False


def test_room_dialog_join_sends_room_join_with_the_typed_id():
    screen, session, events = make_screen()
    screen.handle_click(*room_button_center())
    field = screen._room_dialog._room_id_field
    screen.handle_click(field.x + 5, field.y + 5)
    for ch in "abc123":
        screen.handle_key(ord(ch))

    screen.handle_click(*room_dialog_button_center(JOIN_BUTTON_X))

    assert session.commands == ["ROOM JOIN abc123"]
    assert screen._room_dialog.is_open is False


def test_room_dialog_join_with_an_empty_id_sends_nothing():
    screen, session, events = make_screen()
    screen.handle_click(*room_button_center())

    screen.handle_click(*room_dialog_button_center(JOIN_BUTTON_X))

    assert session.commands == []
    assert screen._room_dialog.is_open is True  # stays open - nothing to submit yet


def test_room_dialog_cancel_closes_without_any_server_call():
    screen, session, events = make_screen()
    screen.handle_click(*room_button_center())

    screen.handle_click(*room_dialog_button_center(CANCEL_BUTTON_X))

    assert session.commands == []
    assert screen._room_dialog.is_open is False


def test_room_dialog_open_blocks_the_play_button():
    screen, session, events = make_screen()
    screen.handle_click(*room_button_center())

    screen.handle_click(*button_center())  # Play button's coordinates, but the dialog is modal

    assert session.commands == []
    assert screen._searching_since is None


def test_render_with_the_dialog_open_does_not_raise():
    screen, session, events = make_screen()
    screen.handle_click(*room_button_center())
    canvas = Img.create(1, 1)

    screen.render(canvas)


def test_on_enter_closes_an_open_dialog():
    screen, session, events = make_screen()
    screen.handle_click(*room_button_center())

    screen.on_enter()

    assert screen._room_dialog.is_open is False
