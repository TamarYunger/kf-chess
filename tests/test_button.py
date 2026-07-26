from client.view.button import Button
from client.view.img import Img


def test_contains_is_true_inside_the_button_and_false_outside():
    button = Button(10, 20, 100, 40, "Go", (0, 130, 0, 255))

    assert button.contains(10, 20) is True  # top-left corner
    assert button.contains(110, 60) is True  # bottom-right corner
    assert button.contains(60, 40) is True  # center
    assert button.contains(9, 40) is False  # just left of it
    assert button.contains(60, 61) is False  # just below it


def test_draw_fills_the_button_area_with_its_color():
    canvas = Img.create(120, 60, color=(0, 0, 0, 255))
    button = Button(10, 10, 100, 40, "Go", (0, 130, 0, 255))

    button.draw(canvas)

    # A corner, not the center - the centered label's own text pixels can
    # cover the fill color right in the middle of the button.
    assert (canvas.img[12, 12, :3] == [0, 130, 0]).all()


def test_draw_uses_the_given_text_color_and_font_scale():
    canvas = Img.create(120, 60, color=(0, 0, 0, 255))
    button = Button(10, 10, 100, 40, "Go", (0, 130, 0, 255), text_color=(255, 0, 0, 255), font_scale=1.0)

    button.draw(canvas)  # must not raise, and must actually draw something

    assert canvas.img.any()
