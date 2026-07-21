from view.img import Img
from view.screens.room_dialog import (
    BUTTON_HEIGHT, BUTTON_WIDTH, BUTTON_Y, CANCEL_BUTTON_X, CREATE_BUTTON_X, JOIN_BUTTON_X, RoomDialog,
)


class FakeSession:
    def __init__(self):
        self.commands = []

    def submit_command(self, command):
        self.commands.append(command)


def button_center(button_x):
    return button_x + BUTTON_WIDTH // 2, BUTTON_Y + BUTTON_HEIGHT // 2


def test_starts_closed():
    dialog = RoomDialog(FakeSession())

    assert dialog.is_open is False


def test_open_focuses_the_room_id_field_and_clears_it():
    dialog = RoomDialog(FakeSession())
    dialog._room_id_field.set_value("stale")

    dialog.open()

    assert dialog.is_open is True
    assert dialog._room_id_field.value == ""
    assert dialog._room_id_field.focused is True


def test_clicks_while_closed_do_nothing():
    session = FakeSession()
    dialog = RoomDialog(session)

    dialog.handle_click(*button_center(CREATE_BUTTON_X))

    assert session.commands == []


def test_render_while_closed_does_not_draw_anything_and_does_not_raise():
    dialog = RoomDialog(FakeSession())
    canvas = Img.create(100, 100)
    before = canvas.img.copy()

    dialog.render(canvas)

    assert (canvas.img == before).all()


def test_render_while_open_does_not_raise():
    dialog = RoomDialog(FakeSession())
    dialog.open()
    canvas = Img.create(480, 340)

    dialog.render(canvas)


def test_create_sends_room_create_and_closes():
    session = FakeSession()
    dialog = RoomDialog(session)
    dialog.open()

    dialog.handle_click(*button_center(CREATE_BUTTON_X))

    assert session.commands == ["ROOM CREATE"]
    assert dialog.is_open is False


def test_join_sends_room_join_with_the_field_value():
    session = FakeSession()
    dialog = RoomDialog(session)
    dialog.open()
    dialog.handle_click(dialog._room_id_field.x + 5, dialog._room_id_field.y + 5)
    for ch in "xyz789":
        dialog.handle_key(ord(ch))

    dialog.handle_click(*button_center(JOIN_BUTTON_X))

    assert session.commands == ["ROOM JOIN xyz789"]
    assert dialog.is_open is False


def test_join_strips_surrounding_whitespace():
    session = FakeSession()
    dialog = RoomDialog(session)
    dialog.open()
    dialog._room_id_field.set_value("  abc123  ")

    dialog.handle_click(*button_center(JOIN_BUTTON_X))

    assert session.commands == ["ROOM JOIN abc123"]


def test_join_with_an_empty_field_sends_nothing_and_stays_open():
    session = FakeSession()
    dialog = RoomDialog(session)
    dialog.open()

    dialog.handle_click(*button_center(JOIN_BUTTON_X))

    assert session.commands == []
    assert dialog.is_open is True


def test_pressing_enter_in_the_field_also_joins():
    session = FakeSession()
    dialog = RoomDialog(session)
    dialog.open()
    dialog.handle_click(dialog._room_id_field.x + 5, dialog._room_id_field.y + 5)
    for ch in "abc123":
        dialog.handle_key(ord(ch))

    dialog.handle_key(13)  # Enter

    assert session.commands == ["ROOM JOIN abc123"]
    assert dialog.is_open is False


def test_cancel_closes_without_any_command():
    session = FakeSession()
    dialog = RoomDialog(session)
    dialog.open()
    dialog._room_id_field.set_value("abc123")

    dialog.handle_click(*button_center(CANCEL_BUTTON_X))

    assert session.commands == []
    assert dialog.is_open is False


def test_close_blurs_the_field():
    dialog = RoomDialog(FakeSession())
    dialog.open()

    dialog.close()

    assert dialog._room_id_field.focused is False
