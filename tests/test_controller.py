from board.text_board import TextBoardRepresentation
from game.models import MoveResult, JumpResult
from game.board_mapper import BoardMapper
from game.controller import Controller

CELL_SIZE = 100


class FakeGameEngine:
    """Stands in for GameEngine so Controller can be unit tested in
    isolation, without RuleEngine/RealTimeArbiter wiring."""

    def __init__(self, board):
        self.board = board
        self.game_over = False
        self.busy_cells = set()
        self.requested_moves = []
        self.requested_jumps = []
        self.next_move_result = MoveResult(True, "ok")
        self.next_jump_result = JumpResult(True, "ok")

    def is_cell_busy(self, cell):
        return cell in self.busy_cells

    def request_move(self, start, end):
        self.requested_moves.append((start, end))
        return self.next_move_result

    def request_jump(self, cell):
        self.requested_jumps.append(cell)
        return self.next_jump_result


def make_controller(rows):
    board = TextBoardRepresentation(rows)
    engine = FakeGameEngine(board)
    controller = Controller(engine, BoardMapper(board, CELL_SIZE))
    return controller, engine


def cell_to_pixel(row, col):
    return col * CELL_SIZE, row * CELL_SIZE


def test_first_click_on_own_piece_selects_it():
    controller, engine = make_controller([["wK", "."]])
    controller.click(*cell_to_pixel(0, 0))
    assert controller.selected == (0, 0)


def test_first_click_on_empty_cell_selects_nothing():
    controller, engine = make_controller([["wK", "."]])
    controller.click(*cell_to_pixel(0, 1))
    assert controller.selected is None


def test_first_click_outside_board_is_ignored():
    controller, engine = make_controller([["wK", "."]])
    controller.click(-1, -1)
    assert controller.selected is None


def test_second_click_requests_a_move_and_clears_selection():
    controller, engine = make_controller([["wR", ".", "."]])
    controller.click(*cell_to_pixel(0, 0))
    controller.click(*cell_to_pixel(0, 2))

    assert engine.requested_moves == [((0, 0), (0, 2))]
    assert controller.selected is None


def test_rejected_move_keeps_selection():
    controller, engine = make_controller([["wR", ".", "."]])
    engine.next_move_result = MoveResult(False, "illegal_piece_move")
    controller.click(*cell_to_pixel(0, 0))
    controller.click(*cell_to_pixel(0, 2))

    assert engine.requested_moves == [((0, 0), (0, 2))]
    assert controller.selected == (0, 0)


def test_second_click_on_own_piece_reselects_instead_of_requesting_move():
    controller, engine = make_controller([["wR", "wN", "."]])
    controller.click(*cell_to_pixel(0, 0))
    controller.click(*cell_to_pixel(0, 1))

    assert controller.selected == (0, 1)
    assert engine.requested_moves == []


def test_busy_cell_cannot_be_selected():
    controller, engine = make_controller([["wR", "."]])
    engine.busy_cells.add((0, 0))
    controller.click(*cell_to_pixel(0, 0))
    assert controller.selected is None


def test_click_is_ignored_once_game_is_over():
    controller, engine = make_controller([["wR", "."]])
    engine.game_over = True
    controller.click(*cell_to_pixel(0, 0))
    assert controller.selected is None


def test_jump_clears_selection_and_requests_jump():
    controller, engine = make_controller([["wR", "."]])
    controller.click(*cell_to_pixel(0, 0))
    controller.jump(*cell_to_pixel(0, 1))

    assert controller.selected is None
    assert engine.requested_jumps == [(0, 1)]


def test_jump_outside_board_sends_no_request():
    controller, engine = make_controller([["wR", "."]])
    controller.jump(-1, -1)
    assert engine.requested_jumps == []


def test_jump_ignored_once_game_is_over():
    controller, engine = make_controller([["wR", "."]])
    engine.game_over = True
    controller.jump(*cell_to_pixel(0, 0))
    assert engine.requested_jumps == []
