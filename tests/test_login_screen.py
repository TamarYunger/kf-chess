from bus.event_bus import EventBus
from view.img import Img
from view.screens.login_screen import BUTTON_HEIGHT, BUTTON_WIDTH, BUTTON_X, BUTTON_Y, LoginScreen


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
    screen = LoginScreen(session, events)
    return screen, session, events


def button_center():
    return BUTTON_X + BUTTON_WIDTH // 2, BUTTON_Y + BUTTON_HEIGHT // 2


def test_render_does_not_raise_before_any_input():
    screen, session, events = make_screen()
    canvas = Img.create(1, 1)

    screen.render(canvas)

    assert canvas.img.shape[0] > 1 and canvas.img.shape[1] > 1


def test_on_enter_focuses_the_username_field():
    screen, session, events = make_screen()

    screen.on_enter()

    assert screen._username_field.focused is True


def test_clicking_the_field_focuses_it_and_does_not_submit():
    screen, session, events = make_screen()

    screen.handle_click(screen._username_field.x + 5, screen._username_field.y + 5)

    assert screen._username_field.focused is True
    assert session.commands == []


def test_typing_and_clicking_login_submits_the_username():
    screen, session, events = make_screen()
    screen.handle_click(screen._username_field.x + 5, screen._username_field.y + 5)
    for ch in "alice":
        screen.handle_key(ord(ch))

    screen.handle_click(*button_center())

    assert session.commands == ["LOGIN alice"]


def test_pressing_enter_in_the_field_also_submits():
    screen, session, events = make_screen()
    screen.handle_click(screen._username_field.x + 5, screen._username_field.y + 5)
    for ch in "bob":
        screen.handle_key(ord(ch))

    screen.handle_key(13)  # Enter

    assert session.commands == ["LOGIN bob"]


def test_clicking_login_with_an_empty_username_submits_nothing():
    screen, session, events = make_screen()

    screen.handle_click(*button_center())

    assert session.commands == []


def test_clicking_outside_the_field_and_button_does_nothing():
    screen, session, events = make_screen()

    screen.handle_click(0, 0)

    assert session.commands == []


def test_login_rejected_event_shows_an_error_message():
    screen, session, events = make_screen()

    events.publish("login_rejected", {"message": "Room is full"})

    assert screen._error_message == "Room is full"


def test_error_message_is_drawn_without_raising():
    screen, session, events = make_screen()
    events.publish("login_rejected", {"message": "Room is full"})
    canvas = Img.create(1, 1)

    screen.render(canvas)  # must not raise with an active error banner


def test_on_enter_clears_a_previous_error_and_field_value():
    screen, session, events = make_screen()
    screen.handle_click(screen._username_field.x + 5, screen._username_field.y + 5)
    screen.handle_key(ord("x"))
    events.publish("login_rejected", {"message": "Room is full"})

    screen.on_enter()

    assert screen._error_message is None
    assert screen._username_field.value == ""


def test_submitting_again_clears_a_stale_error_message():
    screen, session, events = make_screen()
    events.publish("login_rejected", {"message": "Room is full"})
    screen.handle_click(screen._username_field.x + 5, screen._username_field.y + 5)
    for ch in "alice":
        screen.handle_key(ord(ch))

    screen.handle_click(*button_center())

    assert screen._error_message is None
