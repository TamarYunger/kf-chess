from view.img import Img
from view.text_input import TextInput


def test_starts_empty_and_unfocused():
    field = TextInput(0, 0, 100, 30)

    assert field.value == ""
    assert field.focused is False


def test_click_inside_focuses_the_field():
    field = TextInput(10, 10, 100, 30)

    inside = field.handle_click(50, 20)

    assert inside is True
    assert field.focused is True


def test_click_outside_blurs_the_field():
    field = TextInput(10, 10, 100, 30)
    field.focus()

    inside = field.handle_click(500, 500)

    assert inside is False
    assert field.focused is False


def test_typing_while_unfocused_does_nothing():
    field = TextInput(0, 0, 100, 30)

    consumed = field.handle_key(ord("a"))

    assert consumed is False
    assert field.value == ""


def test_typing_while_focused_appends_characters():
    field = TextInput(0, 0, 100, 30)
    field.focus()

    for ch in "hi":
        field.handle_key(ord(ch))

    assert field.value == "hi"


def test_backspace_removes_the_last_character():
    field = TextInput(0, 0, 100, 30)
    field.focus()
    field.set_value("hi")

    consumed = field.handle_key(8)

    assert consumed is True
    assert field.value == "h"


def test_backspace_on_empty_value_stays_empty():
    field = TextInput(0, 0, 100, 30)
    field.focus()

    field.handle_key(8)

    assert field.value == ""


def test_enter_invokes_on_submit_with_the_current_value():
    submitted = []
    field = TextInput(0, 0, 100, 30, on_submit=lambda value: submitted.append(value))
    field.focus()
    field.set_value("secret")

    consumed = field.handle_key(13)

    assert consumed is True
    assert submitted == ["secret"]


def test_max_length_stops_further_typing():
    field = TextInput(0, 0, 100, 30, max_length=3)
    field.focus()

    for ch in "abcd":
        field.handle_key(ord(ch))

    assert field.value == "abc"


def test_hidden_mode_masks_the_rendered_text_but_not_the_value():
    field = TextInput(0, 0, 200, 30, hidden=True)
    field.focus()
    field.set_value("pw")
    canvas = Img.create(200, 30)

    field.render(canvas)  # must not raise, and must not draw the raw value

    assert field.value == "pw"


def test_clear_empties_the_value():
    field = TextInput(0, 0, 100, 30)
    field.set_value("abc")

    field.clear()

    assert field.value == ""


def test_render_does_not_raise_when_empty_and_unfocused():
    field = TextInput(0, 0, 100, 30, placeholder="username")
    canvas = Img.create(100, 30)

    field.render(canvas)
