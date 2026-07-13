from config import settings
from board.board import Board
from rules.game_conditions import LastRankPromotion, PromotionRule
from realtime.real_time_arbiter import RealTimeArbiter


class NoPromotion(PromotionRule):
    def promote(self, piece, row, board_height):
        return piece


def make_arbiter(rows, promotion_rule=None):
    board = Board(rows)
    arbiter = RealTimeArbiter(
        board=board,
        promotion_rule=promotion_rule or NoPromotion(),
        config=settings,
    )
    return arbiter, board


def test_one_square_move_has_not_arrived_before_duration():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    arbiter.start_move("wR", (0, 0), (0, 1))
    arbiter.advance_time(settings.MOVE_DURATION - 1)

    assert board.get(0, 0) == "wR"  # still at source
    assert board.is_empty(0, 1)
    assert arbiter.has_active_motion() is True


def test_one_square_move_arrives_at_duration():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    arbiter.start_move("wR", (0, 0), (0, 1))
    events = arbiter.advance_time(settings.MOVE_DURATION)

    assert board.is_empty(0, 0)
    assert board.get(0, 1) == "wR"
    assert arbiter.has_active_motion() is False
    assert len(events) == 1
    assert events[0].destination == (0, 1)
    assert events[0].captured is None


def test_arrival_time_scales_with_distance():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    arbiter.start_move("wR", (0, 0), (0, 2))  # two squares -> 2000ms
    arbiter.advance_time(settings.MOVE_DURATION)
    assert board.get(0, 0) == "wR"  # not yet arrived after one duration
    arbiter.advance_time(settings.MOVE_DURATION)
    assert board.get(0, 2) == "wR"


def test_partial_waits_accumulate():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    arbiter.start_move("wR", (0, 0), (0, 1))
    arbiter.advance_time(settings.MOVE_DURATION // 2)
    arbiter.advance_time(settings.MOVE_DURATION - settings.MOVE_DURATION // 2)
    assert board.get(0, 1) == "wR"


def test_capture_reported_on_arrival():
    arbiter, board = make_arbiter([["wR", ".", "bK"]])
    arbiter.start_move("wR", (0, 0), (0, 2))
    events = arbiter.advance_time(2 * settings.MOVE_DURATION)
    assert board.get(0, 2) == "wR"
    assert events[0].captured == "bK"


def test_promotion_applied_on_arrival():
    arbiter, board = make_arbiter(
        [[".", ".", "."], ["wP", ".", "."]],
        promotion_rule=LastRankPromotion(settings.PAWN_DIRECTION),
    )
    arbiter.start_move("wP", (1, 0), (0, 0))
    events = arbiter.advance_time(settings.MOVE_DURATION)
    assert board.get(0, 0) == "wQ"
    assert events[0].piece == "wQ"


def test_jump_intercepts_arriving_enemy_and_emits_no_event():
    arbiter, board = make_arbiter([["wR", "bP", "."]])
    arbiter.start_move("wR", (0, 0), (0, 1))
    arbiter.start_jump("bP", (0, 1))
    events = arbiter.advance_time(settings.JUMP_DURATION)

    assert board.get(0, 1) == "bP"  # target unchanged
    assert board.is_empty(0, 0)  # mover captured mid-flight
    assert events == []


def test_friendly_piece_at_destination_cancels_arrival():
    # If a friendly piece occupies the destination on arrival, the mover does
    # not land and no event is emitted.
    arbiter, board = make_arbiter([["wR", ".", "."], ["wP", ".", "."]])
    arbiter.start_move("wR", (0, 0), (0, 2))
    # Drop a friendly piece on the destination before arrival.
    board.set(0, 2, "wP")
    events = arbiter.advance_time(2 * settings.MOVE_DURATION)
    assert board.get(0, 0) == "wR"  # mover survives in place
    assert board.get(0, 2) == "wP"
    assert events == []


def test_clock_advances_with_time():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    assert arbiter.clock == 0
    arbiter.advance_time(250)
    assert arbiter.clock == 250


def test_is_moving_from_and_is_jumping_on():
    arbiter, board = make_arbiter([["wR", "bP", "."]])
    arbiter.start_move("wR", (0, 0), (0, 2))
    arbiter.start_jump("bP", (0, 1))
    assert arbiter.is_moving_from((0, 0)) is True
    assert arbiter.is_moving_from((0, 2)) is False
    assert arbiter.is_jumping_on((0, 1)) is True
