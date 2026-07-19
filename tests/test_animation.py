import pytest

from view.piece_assets import StateConfig
from view.animation import (
    resolve_state_chain,
    frame_index_for,
    interpolate_position,
    compute_piece_views,
)
from game.snapshot import GameSnapshot
from realtime.models import Move, Jump, Arrival
from board.board import Board
from config import settings


IDLE = StateConfig(fps=6, is_loop=True, next_state="idle", frame_count=5)
MOVE = StateConfig(fps=12, is_loop=True, next_state="long_rest", frame_count=5)
JUMP = StateConfig(fps=8, is_loop=False, next_state="short_rest", frame_count=5)
SHORT_REST = StateConfig(fps=8, is_loop=True, next_state="idle", frame_count=5)
LONG_REST = StateConfig(fps=6, is_loop=True, next_state="idle", frame_count=5)

CONFIGS = {
    "idle": IDLE,
    "move": MOVE,
    "jump": JUMP,
    "short_rest": SHORT_REST,
    "long_rest": LONG_REST,
}


def test_looping_state_never_advances():
    state, ms = resolve_state_chain(CONFIGS, "idle", 999_999)
    assert state == "idle"
    assert ms == 999_999


def test_non_looping_state_stays_until_its_duration_elapses():
    # jump: 5 frames @ 8fps = 625ms
    state, ms = resolve_state_chain(CONFIGS, "jump", 100)
    assert state == "jump"
    assert ms == 100


def test_chain_walks_multiple_hops_to_terminal_idle():
    # jump (625ms) -> short_rest (625ms) -> idle, landing well past both
    state, ms = resolve_state_chain(CONFIGS, "jump", 625 + 625 + 150)
    assert state == "idle"
    assert ms == 150


def test_chain_lands_exactly_on_a_duration_boundary():
    state, ms = resolve_state_chain(CONFIGS, "jump", 625)
    assert state == "short_rest"
    assert ms == 0


def test_move_settles_into_long_rest_not_short_rest():
    # move (5 frames @ 12fps = ~416.67ms) -> long_rest
    state, ms = resolve_state_chain(CONFIGS, "move", 500)
    assert state == "long_rest"
    assert ms == pytest.approx(500 - (5 / 12 * 1000))


def test_frame_index_wraps_for_looping_state():
    # 6fps, 5 frames: 900ms -> 5.4 frames -> raw=5 -> 5 % 5 == 0
    assert frame_index_for(IDLE, 900) == 0


def test_frame_index_clamps_for_non_looping_state_past_its_duration():
    # jump: 8fps, 5 frames -> duration 625ms; way past that
    assert frame_index_for(JUMP, 10_000) == 4


def test_interpolate_position_endpoints_and_midpoint():
    start, end = (0, 0), (0, 2)
    assert interpolate_position(start, end, 0, 2000, 0, 100) == (0.0, 0.0)
    assert interpolate_position(start, end, 0, 2000, 2000, 100) == (200.0, 0.0)
    assert interpolate_position(start, end, 0, 2000, 1000, 100) == (100.0, 0.0)


def test_interpolate_position_degenerate_zero_duration_snaps_to_end():
    x, y = interpolate_position((0, 0), (0, 2), 100, 100, 100, 100)
    assert (x, y) == (200.0, 0.0)


def _piece_configs():
    return {"RW": CONFIGS, "PB": CONFIGS, "KW": CONFIGS}


def test_compute_piece_views_idle_piece():
    board = Board([["wR", "."]])
    snap = GameSnapshot.from_board(board, game_over=False, clock=12345)
    views = compute_piece_views(snap, _piece_configs(), settings)
    assert len(views) == 1
    assert views[0].token == "wR"
    assert views[0].folder == "RW"
    assert views[0].state == "idle"
    assert views[0].x == 0 and views[0].y == 0


def test_compute_piece_views_mid_move_interpolates():
    board = Board([["wR", ".", "."]])
    move = Move("wR", (0, 0), (0, 2), arrival=2 * settings.MOVE_DURATION)
    snap = GameSnapshot.from_board(board, game_over=False, moves=(move,),
                                    clock=settings.MOVE_DURATION)
    views = compute_piece_views(snap, _piece_configs(), settings)
    assert views[0].state == "move"
    assert views[0].x == settings.CELL_SIZE
    assert views[0].y == 0


def test_compute_piece_views_jump_takeoff_has_no_lift_yet():
    board = Board([[".", "bP"]])
    jump = Jump("bP", (0, 1), end_time=settings.JUMP_DURATION)
    snap = GameSnapshot.from_board(board, game_over=False, jumps=(jump,), clock=0)
    views = compute_piece_views(snap, _piece_configs(), settings)
    assert views[0].state == "jump"
    assert views[0].x == settings.CELL_SIZE
    assert views[0].y == 0


def test_compute_piece_views_jump_lifts_at_midair_and_lands_flat():
    board = Board([[".", "."], [".", "bP"]])
    jump = Jump("bP", (1, 1), end_time=settings.JUMP_DURATION)

    midair = GameSnapshot.from_board(
        board, game_over=False, jumps=(jump,), clock=settings.JUMP_DURATION // 2,
    )
    views = compute_piece_views(midair, _piece_configs(), settings)
    assert views[0].x == settings.CELL_SIZE  # horizontal position unaffected
    assert views[0].y < settings.CELL_SIZE   # lifted above its resting row

    landing = GameSnapshot.from_board(
        board, game_over=False, jumps=(jump,), clock=settings.JUMP_DURATION,
    )
    views = compute_piece_views(landing, _piece_configs(), settings)
    assert views[0].y == pytest.approx(settings.CELL_SIZE, abs=1)


def test_jump_height_offset_never_pushes_a_top_row_piece_above_the_canvas():
    board = Board([["bP", "."]])
    jump = Jump("bP", (0, 0), end_time=settings.JUMP_DURATION)
    snap = GameSnapshot.from_board(
        board, game_over=False, jumps=(jump,), clock=settings.JUMP_DURATION // 2,
    )
    views = compute_piece_views(snap, _piece_configs(), settings)
    assert views[0].y >= 0


def test_compute_piece_views_stale_arrival_falls_through_to_idle():
    # The piece token at the cell no longer matches the recorded arrival
    # (e.g. it was captured and replaced), so the arrival entry is stale.
    board = Board([["wR", "."]])
    stale_arrival = Arrival(piece="bP", cell=(0, 0), at=0, kind="move")
    snap = GameSnapshot.from_board(board, game_over=False,
                                    recent_arrivals=(stale_arrival,), clock=500)
    views = compute_piece_views(snap, _piece_configs(), settings)
    assert views[0].state == "idle"


def test_compute_piece_views_fresh_move_arrival_starts_long_rest():
    board = Board([["wR", "."]])
    arrival = Arrival(piece="wR", cell=(0, 0), at=0, kind="move")
    snap = GameSnapshot.from_board(board, game_over=False,
                                    recent_arrivals=(arrival,), clock=1)
    views = compute_piece_views(snap, _piece_configs(), settings)
    assert views[0].state == "long_rest"


def test_compute_piece_views_fresh_jump_arrival_starts_short_rest():
    board = Board([["wR", "."]])
    arrival = Arrival(piece="wR", cell=(0, 0), at=0, kind="jump")
    snap = GameSnapshot.from_board(board, game_over=False,
                                    recent_arrivals=(arrival,), clock=1)
    views = compute_piece_views(snap, _piece_configs(), settings)
    assert views[0].state == "short_rest"
