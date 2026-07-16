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


def test_due_moves_settle_in_arrival_order_not_registration_order():
    # wR is registered first but travels 3 squares (arrives later); wP is
    # registered second but travels 1 square (arrives earlier). A single
    # large advance makes both due in the same resolve() call - wP's earlier
    # arrival must be applied to the board before wR's later one, regardless
    # of which start_move call came first.
    arbiter, board = make_arbiter([["wR", ".", ".", "."], ["wP", ".", ".", "."]])
    arbiter.start_move("wR", (0, 0), (0, 3))   # arrives at 3 * MOVE_DURATION
    arbiter.start_move("wP", (1, 0), (1, 1))   # arrives at 1 * MOVE_DURATION
    events = arbiter.advance_time(3 * settings.MOVE_DURATION)

    assert [event.destination for event in events] == [(1, 1), (0, 3)]
    assert board.get(1, 1) == "wP"
    assert board.get(0, 3) == "wR"


def test_enemy_tie_on_a_shared_destination_is_won_by_registration_order():
    # Two enemy rooks with the same distance arrive at the exact same tick,
    # racing for the same empty square. There is no meaningful way to say
    # which one "really" got there first - the tie is broken by whichever
    # was registered second (sort() is stable, so equal arrivals keep their
    # original relative order, and the later one in that order sees the
    # earlier one's piece already sitting on the destination and captures
    # it). This is a deliberate, documented choice - not a designed fairness
    # rule, just the simplest deterministic tie-break - kept as-is because
    # exact-tie races are a rare edge case not worth extra machinery for.
    # If this ever needs to change, it changes here.
    arbiter, board = make_arbiter([["wR", ".", "."], [".", ".", "."], [".", ".", "bR"]])
    arbiter.start_move("wR", (0, 0), (0, 2))   # registered first, distance 2
    arbiter.start_move("bR", (2, 2), (0, 2))   # registered second, distance 2 - same arrival
    arbiter.advance_time(2 * settings.MOVE_DURATION)

    assert board.get(0, 2) == "bR"


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


def test_active_moves_and_jumps_reflect_in_flight_state():
    arbiter, board = make_arbiter([["wR", "bP", "."]])
    assert arbiter.active_moves == ()
    assert arbiter.active_jumps == ()

    arbiter.start_move("wR", (0, 0), (0, 2))
    arbiter.start_jump("bP", (0, 1))
    assert type(arbiter.active_moves) is tuple
    assert type(arbiter.active_jumps) is tuple
    assert len(arbiter.active_moves) == 1
    assert arbiter.active_moves[0].start == (0, 0)
    assert len(arbiter.active_jumps) == 1
    assert arbiter.active_jumps[0].cell == (0, 1)


def test_active_moves_empties_once_settled():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    arbiter.start_move("wR", (0, 0), (0, 1))
    arbiter.advance_time(settings.MOVE_DURATION)
    assert arbiter.active_moves == ()


def test_recent_arrivals_records_settled_move_with_kind_move():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    arbiter.start_move("wR", (0, 0), (0, 1))
    arbiter.advance_time(settings.MOVE_DURATION)

    arrivals = {a.cell: a for a in arbiter.recent_arrivals}
    assert (0, 1) in arrivals
    assert arrivals[(0, 1)].piece == "wR"
    assert arrivals[(0, 1)].kind == "move"
    assert arrivals[(0, 1)].at == settings.MOVE_DURATION


def test_recent_arrivals_records_settled_jump_with_kind_jump():
    arbiter, board = make_arbiter([["bP", ".", "."]])
    arbiter.start_jump("bP", (0, 0))
    arbiter.advance_time(settings.JUMP_DURATION)

    arrivals = {a.cell: a for a in arbiter.recent_arrivals}
    assert (0, 0) in arrivals
    assert arrivals[(0, 0)].piece == "bP"
    assert arrivals[(0, 0)].kind == "jump"


def test_recent_arrivals_drops_stale_entry_once_piece_at_cell_changes():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    arbiter.start_move("wR", (0, 0), (0, 1))
    arbiter.advance_time(settings.MOVE_DURATION)
    assert any(a.cell == (0, 1) for a in arbiter.recent_arrivals)

    # A different piece now occupies that cell - the old arrival must not
    # be reported as still describing it.
    board.set(0, 1, "bK")
    assert not any(a.cell == (0, 1) for a in arbiter.recent_arrivals)


def test_is_resting_true_right_after_a_move_lands():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    arbiter.start_move("wR", (0, 0), (0, 1))
    arbiter.advance_time(settings.MOVE_DURATION)
    assert arbiter.is_resting((0, 1)) is True


def test_is_resting_false_once_long_rest_duration_elapses():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    arbiter.start_move("wR", (0, 0), (0, 1))
    arbiter.advance_time(settings.MOVE_DURATION)
    arbiter.advance_time(settings.LONG_REST_DURATION - 1)
    assert arbiter.is_resting((0, 1)) is True
    arbiter.advance_time(1)
    assert arbiter.is_resting((0, 1)) is False


def test_is_resting_true_right_after_a_jump_lands():
    arbiter, board = make_arbiter([["bP", ".", "."]])
    arbiter.start_jump("bP", (0, 0))
    arbiter.advance_time(settings.JUMP_DURATION)
    assert arbiter.is_resting((0, 0)) is True


def test_is_resting_false_once_short_rest_duration_elapses():
    arbiter, board = make_arbiter([["bP", ".", "."]])
    arbiter.start_jump("bP", (0, 0))
    arbiter.advance_time(settings.JUMP_DURATION)
    arbiter.advance_time(settings.SHORT_REST_DURATION - 1)
    assert arbiter.is_resting((0, 0)) is True
    arbiter.advance_time(1)
    assert arbiter.is_resting((0, 0)) is False


def test_is_resting_false_for_a_cell_with_no_recent_arrival():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    assert arbiter.is_resting((0, 0)) is False


def test_is_resting_false_once_the_resting_piece_is_replaced():
    arbiter, board = make_arbiter([["wR", ".", "."]])
    arbiter.start_move("wR", (0, 0), (0, 1))
    arbiter.advance_time(settings.MOVE_DURATION)
    assert arbiter.is_resting((0, 1)) is True

    board.set(0, 1, "bK")
    assert arbiter.is_resting((0, 1)) is False


def test_recent_arrivals_not_recorded_for_intercepted_move():
    # The interceptor's own jump still lands (and is recorded), but the
    # mover it captured mid-flight never "arrives", so no move-kind
    # arrival is recorded for it.
    arbiter, board = make_arbiter([["wR", "bP", "."]])
    arbiter.start_move("wR", (0, 0), (0, 1))
    arbiter.start_jump("bP", (0, 1))
    arbiter.advance_time(settings.JUMP_DURATION)

    kinds_by_cell = {a.cell: a.kind for a in arbiter.recent_arrivals}
    assert kinds_by_cell.get((0, 1)) == "jump"
    assert (0, 0) not in kinds_by_cell
