import numpy as np
import pytest

from client.view.img import Img

BOARD_PATH = "assets/board.png"  # real 3-channel (BGR) image on disk
SPRITE_PATH = "assets/pieces/PW/states/idle/sprites/1.png"  # real 4-channel (BGRA) image


def test_read_loads_and_returns_self_for_chaining():
    img = Img()
    result = img.read(BOARD_PATH)
    assert result is img
    assert img.img is not None


def test_read_missing_file_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        Img().read("assets/does_not_exist.png")


def test_read_resizes_to_the_exact_requested_size_without_keep_aspect():
    img = Img().read(BOARD_PATH, size=(40, 20))
    assert img.img.shape[:2] == (20, 40)


def test_read_keep_aspect_shrinks_the_longer_side_to_fit():
    # The source is square (800x800) - keep_aspect against a non-square
    # target must shrink to fit the *smaller* target dimension, not distort
    # to fill both.
    img = Img().read(BOARD_PATH, size=(40, 20), keep_aspect=True)
    h, w = img.img.shape[:2]
    assert max(h, w) <= 20
    assert h == w  # aspect preserved (source was square)


def test_draw_on_raises_if_either_image_is_not_loaded():
    loaded = Img.create(4, 4)
    unloaded = Img()
    with pytest.raises(ValueError):
        unloaded.draw_on(loaded, 0, 0)
    with pytest.raises(ValueError):
        loaded.draw_on(unloaded, 0, 0)


def test_draw_on_raises_if_it_does_not_fit_at_the_given_position():
    small = Img.create(4, 4)
    big = Img.create(10, 10)
    with pytest.raises(ValueError):
        small.draw_on(big, 8, 8)  # 4x4 at (8,8) overflows a 10x10 canvas


def test_draw_on_converts_a_bgr_source_to_bgra_to_match_a_bgra_target():
    board = Img().read(BOARD_PATH, size=(20, 20))  # 3-channel
    assert board.img.shape[2] == 3
    canvas = Img.create(20, 20)  # 4-channel

    board.draw_on(canvas, 0, 0)  # must not raise on the channel mismatch

    assert board.img.shape[2] == 4  # converted in place
    assert canvas.img.shape[2] == 4


def test_draw_on_converts_a_bgra_source_to_bgr_to_match_a_bgr_target():
    sprite = Img().read(SPRITE_PATH, size=(10, 10))  # 4-channel
    assert sprite.img.shape[2] == 4
    canvas = Img()
    canvas.img = np.zeros((10, 10, 3), dtype=np.uint8)  # 3-channel, no alpha

    sprite.draw_on(canvas, 0, 0)  # must not raise on the channel mismatch

    assert sprite.img.shape[2] == 3  # converted in place


def test_draw_on_alpha_blends_a_partially_transparent_source_onto_the_target():
    source = Img()
    # 1x2 BGRA: a fully transparent pixel, then a fully opaque one.
    source.img = np.array([[[0, 0, 255, 0], [0, 255, 0, 255]]], dtype=np.uint8)
    canvas = Img.create(2, 1, color=(100, 100, 100, 255))

    source.draw_on(canvas, 0, 0)

    assert (canvas.img[0, 0, :3] == [100, 100, 100]).all()  # alpha=0: canvas colour untouched
    assert (canvas.img[0, 1, :3] == [0, 255, 0]).all()  # alpha=255: fully replaced by source colour


def test_draw_on_directly_assigns_when_neither_image_has_an_alpha_channel():
    source = Img()
    source.img = np.full((5, 5, 3), 200, dtype=np.uint8)
    canvas = Img()
    canvas.img = np.zeros((10, 10, 3), dtype=np.uint8)

    source.draw_on(canvas, 2, 2)

    assert (canvas.img[2:7, 2:7] == 200).all()
    assert (canvas.img[0, 0] == 0).all()  # untouched outside the paste area


def test_put_text_raises_if_not_loaded():
    with pytest.raises(ValueError):
        Img().put_text("hi", 0, 0, 1.0)


def test_put_text_draws_visible_pixels_onto_a_loaded_image():
    canvas = Img.create(60, 20, color=(0, 0, 0, 255))
    canvas.put_text("Hi", 2, 15, 1.0, color=(255, 255, 255, 255))
    assert (canvas.img[:, :, :3] >= 200).any()


def test_text_size_returns_positive_dimensions():
    w, h = Img().text_size("hello", 1.0)
    assert w > 0
    assert h > 0


def test_rectangle_raises_if_not_loaded():
    with pytest.raises(ValueError):
        Img().rectangle((0, 0), (1, 1), (255, 255, 255), 1)


def test_rectangle_draws_a_visible_border():
    canvas = Img.create(10, 10, color=(0, 0, 0, 255))
    canvas.rectangle((1, 1), (8, 8), (255, 255, 255, 255), 1)
    assert canvas.img[1, 1].any()


def test_to_bgra_raises_if_not_loaded():
    with pytest.raises(ValueError):
        Img().to_bgra()


def test_to_bgra_adds_an_opaque_alpha_channel_to_a_bgr_image():
    img = Img()
    img.img = np.zeros((3, 3, 3), dtype=np.uint8)
    img.to_bgra()
    assert img.img.shape[2] == 4


def test_to_bgra_is_a_noop_for_an_already_bgra_image():
    img = Img.create(3, 3)
    before = img.img.copy()
    img.to_bgra()
    assert (img.img == before).all()


def test_blend_rect_raises_if_not_loaded():
    with pytest.raises(ValueError):
        Img().blend_rect(0, 0, 1, 1, (255, 255, 255), 0.5)


def test_blend_rect_moves_the_region_toward_the_given_color():
    canvas = Img.create(10, 10, color=(0, 0, 0, 255))
    canvas.blend_rect(0, 0, 10, 10, (200, 200, 200), 1.0)  # full-strength blend
    assert (canvas.img[:, :, :3] == 200).all()


def test_blend_circle_raises_if_not_loaded():
    with pytest.raises(ValueError):
        Img().blend_circle(5, 5, 3, (255, 255, 255), 0.5)


def test_blend_circle_only_affects_pixels_inside_the_radius():
    canvas = Img.create(20, 20, color=(0, 0, 0, 255))
    canvas.blend_circle(10, 10, 5, (255, 255, 255), 1.0)
    assert (canvas.img[10, 10, :3] == 255).all()  # center: inside the circle
    assert (canvas.img[0, 0, :3] == 0).all()  # far corner: outside the circle


def test_create_returns_a_filled_canvas_of_the_requested_size():
    canvas = Img.create(6, 4, color=(1, 2, 3, 4))
    assert canvas.img.shape == (4, 6, 4)
    assert (canvas.img[0, 0] == [1, 2, 3, 4]).all()
