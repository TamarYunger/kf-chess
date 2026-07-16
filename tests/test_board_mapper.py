from board.board import Board
from game.board_mapper import BoardMapper

CELL_SIZE = 100


def make_mapper(rows=3, cols=3, x_offset=0, y_offset=0):
    board = Board([["."] * cols for _ in range(rows)])
    return BoardMapper(board, CELL_SIZE, x_offset=x_offset, y_offset=y_offset)


def test_pixel_to_cell_with_no_offset():
    mapper = make_mapper()
    assert mapper.pixel_to_cell(0, 0) == (0, 0)
    assert mapper.pixel_to_cell(150, 250) == (2, 1)


def test_pixel_to_cell_outside_board_is_none():
    mapper = make_mapper()
    assert mapper.pixel_to_cell(1000, 1000) is None


def test_pixel_to_cell_accounts_for_x_offset():
    # Regression: a left-hand side panel (e.g. GraphicsRenderer's score
    # panel) shifts the board's own left edge away from window-x=0 - a
    # click at the board's real on-screen position must still map to the
    # same cell it would without the panel.
    mapper = make_mapper(x_offset=220)
    assert mapper.pixel_to_cell(220, 0) == (0, 0)
    assert mapper.pixel_to_cell(220 + 150, 250) == (2, 1)


def test_click_on_the_side_panel_itself_is_outside_the_board():
    mapper = make_mapper(x_offset=220)
    assert mapper.pixel_to_cell(50, 50) is None


def test_pixel_to_cell_accounts_for_y_offset():
    mapper = make_mapper(y_offset=40)
    assert mapper.pixel_to_cell(0, 40) == (0, 0)
    assert mapper.pixel_to_cell(150, 40 + 250) == (2, 1)
