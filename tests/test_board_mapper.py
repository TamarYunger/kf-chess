from board.text_board import TextBoardRepresentation
from game.board_mapper import BoardMapper

CELL_SIZE = 100


def make_mapper(width=3, height=3):
    board = TextBoardRepresentation([["."] * width for _ in range(height)])
    return BoardMapper(board, CELL_SIZE)


def test_maps_top_left_pixel_to_row_0_col_0():
    mapper = make_mapper()
    assert mapper.pixel_to_cell(50, 50) == (0, 0)


def test_maps_second_column():
    mapper = make_mapper()
    assert mapper.pixel_to_cell(150, 50) == (0, 1)


def test_maps_second_row():
    mapper = make_mapper()
    assert mapper.pixel_to_cell(50, 150) == (1, 0)


def test_negative_pixel_is_outside_board():
    mapper = make_mapper()
    assert mapper.pixel_to_cell(-1, -1) is None


def test_pixel_past_board_edge_is_outside_board():
    mapper = make_mapper(width=3, height=3)
    assert mapper.pixel_to_cell(300, 50) is None
