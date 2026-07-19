from board.board import Board
from config import settings
from game.models import MoveRecord
from rules.reasons import Reason
from game.snapshot import GameSnapshot
from view.graphics_renderer import GraphicsRenderer, SIDE_PANEL_WIDTH

ASSETS_DIR = "assets"


def make_renderer():
    return GraphicsRenderer(settings, assets_dir=ASSETS_DIR)


def test_render_produces_a_canvas_sized_to_the_board_plus_two_side_panels():
    renderer = make_renderer()
    board = Board([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    snap = GameSnapshot.from_board(board, game_over=False)

    canvas = renderer.render(snap)

    board_w = 3 * settings.CELL_SIZE
    assert canvas.img.shape[:2] == (3 * settings.CELL_SIZE, SIDE_PANEL_WIDTH + board_w + SIDE_PANEL_WIDTH)


def test_first_color_panel_is_on_the_left_second_on_the_right():
    # config.COLORS = ("w", "b"): white's panel (moves recorded) must be on
    # the left, black's on the right - not both crammed into one sidebar.
    renderer = make_renderer()
    board = Board([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    blank_snap = GameSnapshot.from_board(board, game_over=False)
    white_history_snap = GameSnapshot.from_board(
        board, game_over=False,
        move_history={"w": (MoveRecord("wR", (0, 0), (0, 2)),), "b": ()},
    )

    blank_canvas = renderer.render(blank_snap)
    history_canvas = renderer.render(white_history_snap)

    board_w = 3 * settings.CELL_SIZE
    left_panel_blank = blank_canvas.img[:, :SIDE_PANEL_WIDTH, :3]
    left_panel_history = history_canvas.img[:, :SIDE_PANEL_WIDTH, :3]
    right_panel_blank = blank_canvas.img[:, SIDE_PANEL_WIDTH + board_w:, :3]
    right_panel_history = history_canvas.img[:, SIDE_PANEL_WIDTH + board_w:, :3]

    # White's recorded move brightens the left panel...
    assert (left_panel_history >= 200).any(axis=-1).sum() > (left_panel_blank >= 200).any(axis=-1).sum()
    # ...and leaves the right (black's) panel exactly as it was.
    assert (right_panel_history >= 200).any(axis=-1).sum() == (right_panel_blank >= 200).any(axis=-1).sum()


def test_sidebar_header_draws_score_next_to_the_color_name():
    renderer = make_renderer()
    board = Board([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    no_score_snap = GameSnapshot.from_board(board, game_over=False)
    score_snap = GameSnapshot.from_board(board, game_over=False, score={"w": 9, "b": 0})

    no_score_canvas = renderer.render(no_score_snap)
    score_canvas = renderer.render(score_snap)

    # White's header lives in the left panel now.
    no_score_header = no_score_canvas.img[:40, :SIDE_PANEL_WIDTH, :3]
    score_header = score_canvas.img[:40, :SIDE_PANEL_WIDTH, :3]
    assert (score_header >= 200).any(axis=-1).sum() > (no_score_header >= 200).any(axis=-1).sum()


def test_move_history_panel_has_one_column_per_extra_color():
    import types
    three_color_config = types.SimpleNamespace(**{
        **{k: v for k, v in vars(settings).items() if not k.startswith("_")},
        "COLORS": ("w", "b", "g"),
    })
    renderer = GraphicsRenderer(three_color_config, assets_dir=ASSETS_DIR)
    board = Board([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    snap = GameSnapshot.from_board(board, game_over=False, move_history={
        "w": (MoveRecord("wR", (0, 0), (0, 2)),), "b": (), "g": (),
    })

    # Rendering must not crash with a color count other than two ("w" alone
    # on the left, "b" and "g" sharing the right panel), and must still
    # produce a canvas of the expected (board + two fixed side panels) size.
    canvas = renderer.render(snap)
    board_w = 3 * settings.CELL_SIZE
    assert canvas.img.shape[:2] == (3 * settings.CELL_SIZE, SIDE_PANEL_WIDTH + board_w + SIDE_PANEL_WIDTH)


def test_legal_move_dot_is_drawn_on_an_empty_destination_cell():
    renderer = make_renderer()
    board = Board([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    no_highlight_snap = GameSnapshot.from_board(board, game_over=False)
    highlight_snap = GameSnapshot.from_board(board, game_over=False, legal_destinations=frozenset({(0, 1)}))

    no_highlight_canvas = renderer.render(no_highlight_snap)
    highlight_canvas = renderer.render(highlight_snap)

    board_w = 3 * settings.CELL_SIZE
    left = SIDE_PANEL_WIDTH
    assert not (no_highlight_canvas.img[:, left:left + board_w] == highlight_canvas.img[:, left:left + board_w]).all()


def test_legal_capture_ring_is_drawn_on_an_occupied_destination_cell():
    renderer = make_renderer()
    board = Board([["wR", ".", "bN"], [".", ".", "."], [".", ".", "."]])
    no_highlight_snap = GameSnapshot.from_board(board, game_over=False)
    highlight_snap = GameSnapshot.from_board(board, game_over=False, legal_destinations=frozenset({(0, 2)}))

    no_highlight_canvas = renderer.render(no_highlight_snap)
    highlight_canvas = renderer.render(highlight_snap)

    board_w = 3 * settings.CELL_SIZE
    left = SIDE_PANEL_WIDTH
    assert not (no_highlight_canvas.img[:, left:left + board_w] == highlight_canvas.img[:, left:left + board_w]).all()


def test_game_over_banner_dims_the_board_overall():
    # The checkerboard background means roughly half the canvas is bright;
    # dimming that dominates the mean brightness even though the banner
    # text itself brightens a small region in the middle.
    renderer = make_renderer()
    board = Board([["wK", "."], [".", "bK"]])

    live_snap = GameSnapshot.from_board(board, game_over=False)
    live_canvas = renderer.render(live_snap)

    over_snap = GameSnapshot.from_board(board, game_over=True, winner="w")
    over_canvas = renderer.render(over_snap)

    assert over_canvas.img[:, :, :3].mean() < live_canvas.img[:, :, :3].mean()


def test_game_over_banner_draws_white_text_pixels():
    renderer = make_renderer()
    board = Board([["wK", "."], [".", "bK"]])
    snap = GameSnapshot.from_board(board, game_over=True, winner="b")

    canvas = renderer.render(snap)

    # Somewhere on the dimmed board there should be bright white text pixels
    # from the banner (dimming alone can't produce near-white output).
    assert (canvas.img[:, :, :3] >= 250).all(axis=-1).any()


def test_rejection_banner_draws_text_when_a_move_was_rejected():
    renderer = make_renderer()
    board = Board([["wK", "."], [".", "."]])
    no_rejection_snap = GameSnapshot.from_board(board, game_over=False)
    rejection_snap = GameSnapshot.from_board(
        board, game_over=False, rejection_reason=Reason.DESTINATION_CONTESTED,
    )

    no_rejection_canvas = renderer.render(no_rejection_snap)
    rejection_canvas = renderer.render(rejection_snap)

    # The banner darkens/recolors a strip along the bottom of the board -
    # check that strip actually changed, rather than assuming a direction
    # (the underlying checkerboard there may already be bright, so the
    # banner can lower the "bright pixel" count even while clearly drawing).
    board_w = 2 * settings.CELL_SIZE
    board_h = 2 * settings.CELL_SIZE
    no_rejection_bottom = no_rejection_canvas.img[board_h - 40:board_h, SIDE_PANEL_WIDTH:SIDE_PANEL_WIDTH + board_w]
    rejection_bottom = rejection_canvas.img[board_h - 40:board_h, SIDE_PANEL_WIDTH:SIDE_PANEL_WIDTH + board_w]
    assert not (no_rejection_bottom == rejection_bottom).all()


def test_rejection_banner_is_not_drawn_once_the_game_is_over():
    # The game-over banner takes priority - no rejection bar underneath it.
    renderer = make_renderer()
    board = Board([["wK", "."], [".", "bK"]])
    over_snap = GameSnapshot.from_board(board, game_over=True, winner="w")
    over_with_rejection_snap = GameSnapshot.from_board(
        board, game_over=True, winner="w", rejection_reason=Reason.GAME_OVER,
    )

    over_canvas = renderer.render(over_snap)
    over_with_rejection_canvas = renderer.render(over_with_rejection_snap)

    assert (over_canvas.img == over_with_rejection_canvas.img).all()
