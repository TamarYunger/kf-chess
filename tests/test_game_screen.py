from config import settings
from view.game_screen import GameScreen
from view.graphics_renderer import SIDE_PANEL_WIDTH
from view.img import Img


def minimal_json(**overrides):
    data = {
        "cells": [["wK", ".", "."], [".", ".", "."], [".", ".", "."]],
        "width": 3,
        "height": 3,
        "game_over": False,
    }
    data.update(overrides)
    return data


def test_renders_a_connecting_placeholder_before_any_snapshot():
    screen = GameScreen(settings, send=lambda message: None)
    canvas = Img.create(1, 1)

    screen.render(canvas)

    assert canvas.img is not None
    assert canvas.img.shape[0] > 1 and canvas.img.shape[1] > 1


def test_renders_the_board_once_a_snapshot_arrives():
    screen = GameScreen(settings, send=lambda message: None)
    canvas = Img.create(1, 1)

    screen.update_snapshot(minimal_json())
    screen.render(canvas)

    # 3x3 board at settings.CELL_SIZE plus the two side panels.
    expected_w = 3 * settings.CELL_SIZE + 2 * SIDE_PANEL_WIDTH
    expected_h = 3 * settings.CELL_SIZE
    assert canvas.img.shape[1] == expected_w
    assert canvas.img.shape[0] == expected_h


def test_click_before_any_snapshot_sends_nothing():
    sent = []
    screen = GameScreen(settings, send=sent.append)

    screen.handle_click(SIDE_PANEL_WIDTH, 0)

    assert sent == []


def test_click_on_the_board_sends_select_or_move_with_the_offset_applied():
    sent = []
    screen = GameScreen(settings, send=sent.append, board_x_offset=SIDE_PANEL_WIDTH)
    screen.update_snapshot(minimal_json())

    # Top-left board cell (0, 0) sits at x == SIDE_PANEL_WIDTH on screen,
    # not x == 0 - the side panel is drawn first (mirrors the old
    # BoardMapper offset test in test_main_gui.py).
    screen.handle_click(SIDE_PANEL_WIDTH, 0)

    assert sent == [{"type": "select_or_move", "cell": [0, 0]}]


def test_click_outside_the_board_sends_nothing():
    sent = []
    screen = GameScreen(settings, send=sent.append, board_x_offset=SIDE_PANEL_WIDTH)
    screen.update_snapshot(minimal_json())

    screen.handle_click(0, 0)  # lands in the left side panel, not the board

    assert sent == []


def test_double_click_sends_jump():
    sent = []
    screen = GameScreen(settings, send=sent.append, board_x_offset=SIDE_PANEL_WIDTH)
    screen.update_snapshot(minimal_json())

    screen.handle_double_click(SIDE_PANEL_WIDTH + settings.CELL_SIZE, settings.CELL_SIZE)

    assert sent == [{"type": "jump", "cell": [1, 1]}]


def test_click_below_the_board_bounds_sends_nothing():
    sent = []
    screen = GameScreen(settings, send=sent.append, board_x_offset=SIDE_PANEL_WIDTH)
    screen.update_snapshot(minimal_json())

    screen.handle_click(SIDE_PANEL_WIDTH, 3 * settings.CELL_SIZE + 5)

    assert sent == []
