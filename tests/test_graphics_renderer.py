from board.board import Board
from config import settings
from game.models import MoveRecord
from view.graphics_renderer import GraphicsRenderer, SIDEBAR_WIDTH
from view.snapshot import GameSnapshot

ASSETS_DIR = "assets"


def make_renderer():
    return GraphicsRenderer(settings, assets_dir=ASSETS_DIR)


def test_render_produces_a_canvas_sized_to_the_board_plus_sidebar():
    renderer = make_renderer()
    board = Board([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    snap = GameSnapshot.from_board(board, game_over=False)

    canvas = renderer.render(snap)

    assert canvas.img.shape[:2] == (3 * settings.CELL_SIZE, 3 * settings.CELL_SIZE + SIDEBAR_WIDTH)


def test_move_history_sidebar_draws_text_for_a_recorded_move():
    renderer = make_renderer()
    board = Board([["wR", ".", "."], [".", ".", "."], [".", ".", "."]])
    no_history_snap = GameSnapshot.from_board(board, game_over=False)
    history_snap = GameSnapshot.from_board(
        board, game_over=False,
        move_history={"w": (MoveRecord("wR", (0, 0), (0, 2)),), "b": ()},
    )

    blank_canvas = renderer.render(no_history_snap)
    history_canvas = renderer.render(history_snap)

    board_w = 3 * settings.CELL_SIZE
    blank_panel = blank_canvas.img[:, board_w:, :3]
    history_panel = history_canvas.img[:, board_w:, :3]
    # The recorded move draws extra bright text pixels in the sidebar that
    # the blank history doesn't have (both still show the column headers).
    assert (history_panel >= 200).any(axis=-1).sum() > (blank_panel >= 200).any(axis=-1).sum()


def test_move_history_sidebar_has_one_column_per_configured_color():
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

    # Rendering must not crash with a color count other than two, and must
    # still produce a canvas of the expected (board + fixed sidebar) size.
    canvas = renderer.render(snap)
    assert canvas.img.shape[:2] == (3 * settings.CELL_SIZE, 3 * settings.CELL_SIZE + SIDEBAR_WIDTH)


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
