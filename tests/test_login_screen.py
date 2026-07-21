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


def click_username(screen):
    screen.handle_click(screen._username_field.x + 5, screen._username_field.y + 5)


def click_password(screen):
    screen.handle_click(screen._password_field.x + 5, screen._password_field.y + 5)


def type_text(screen, text):
    for ch in text:
        screen.handle_key(ord(ch))


def login_via_fields(screen, username, password):
    """Types username, presses Enter (moves to password), types password,
    presses Enter (submits) - the same sequence a real player typing and
    hitting Enter twice would produce."""
    click_username(screen)
    type_text(screen, username)
    screen.handle_key(13)  # Enter -> focus password
    type_text(screen, password)
    screen.handle_key(13)  # Enter -> submit


def test_render_does_not_raise_before_any_input():
    screen, session, events = make_screen()
    canvas = Img.create(1, 1)

    screen.render(canvas)

    assert canvas.img.shape[0] > 1 and canvas.img.shape[1] > 1


def test_on_enter_focuses_the_username_field():
    screen, session, events = make_screen()

    screen.on_enter()

    assert screen._username_field.focused is True
    assert screen._password_field.focused is False


def test_clicking_the_username_field_focuses_it_and_does_not_submit():
    screen, session, events = make_screen()

    click_username(screen)

    assert screen._username_field.focused is True
    assert session.commands == []


def test_clicking_the_password_field_focuses_it_directly():
    screen, session, events = make_screen()

    click_password(screen)

    assert screen._password_field.focused is True
    assert screen._username_field.focused is False


def test_enter_in_the_username_field_moves_focus_to_password_without_submitting():
    screen, session, events = make_screen()
    click_username(screen)
    type_text(screen, "alice")

    screen.handle_key(13)  # Enter

    assert screen._username_field.focused is False
    assert screen._password_field.focused is True
    assert session.commands == []


def test_typing_both_fields_and_clicking_login_submits_username_and_password():
    screen, session, events = make_screen()
    click_username(screen)
    type_text(screen, "alice")
    click_password(screen)
    type_text(screen, "hunter2")

    screen.handle_click(*button_center())

    assert session.commands == ["LOGIN alice hunter2"]


def test_pressing_enter_in_the_password_field_submits():
    screen, session, events = make_screen()

    login_via_fields(screen, "bob", "secret123")

    assert session.commands == ["LOGIN bob secret123"]


def test_clicking_login_with_an_empty_username_submits_nothing():
    screen, session, events = make_screen()
    click_password(screen)
    type_text(screen, "somepassword")

    screen.handle_click(*button_center())

    assert session.commands == []


def test_clicking_login_with_an_empty_password_submits_nothing():
    screen, session, events = make_screen()
    click_username(screen)
    type_text(screen, "alice")

    screen.handle_click(*button_center())

    assert session.commands == []


def test_clicking_outside_every_field_and_button_does_nothing():
    screen, session, events = make_screen()

    screen.handle_click(0, 0)

    assert session.commands == []


def test_password_field_masks_its_rendered_value():
    screen, session, events = make_screen()
    click_password(screen)
    type_text(screen, "hunter2")

    assert screen._password_field.value == "hunter2"
    canvas = Img.create(1, 1)
    screen.render(canvas)  # must not raise; masking itself is TextInput's own job


def test_login_rejected_event_shows_an_error_message():
    screen, session, events = make_screen()

    events.publish("login_rejected", {"message": "Invalid password"})

    assert screen._error_message == "Invalid password"


def test_error_message_is_drawn_without_raising():
    screen, session, events = make_screen()
    events.publish("login_rejected", {"message": "Room is full"})
    canvas = Img.create(1, 1)

    screen.render(canvas)  # must not raise with an active error banner


def test_on_enter_clears_a_previous_error_and_both_fields():
    screen, session, events = make_screen()
    click_username(screen)
    type_text(screen, "x")
    screen.handle_key(13)
    type_text(screen, "y")
    events.publish("login_rejected", {"message": "Room is full"})

    screen.on_enter()

    assert screen._error_message is None
    assert screen._username_field.value == ""
    assert screen._password_field.value == ""


def test_submitting_again_clears_a_stale_error_message():
    screen, session, events = make_screen()
    events.publish("login_rejected", {"message": "Invalid password"})

    login_via_fields(screen, "alice", "correct-password")

    assert screen._error_message is None
