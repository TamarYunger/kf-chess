from board.board import Board
from config import settings
from view.graphics_renderer import GraphicsRenderer
from view.snapshot import GameSnapshot

ASSETS_DIR = "assets"


def make_renderer():
    return GraphicsRenderer(settings, assets_dir=ASSETS_DIR)


def test_render_produces_a_canvas_sized_to_the_board():
    renderer = make_renderer()
    board = Board([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    snap = GameSnapshot.from_board(board, game_over=False)

    canvas = renderer.render(snap)

    assert canvas.img.shape[:2] == (3 * settings.CELL_SIZE, 3 * settings.CELL_SIZE)


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
