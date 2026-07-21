"""Full-stack integration tests: the real GameScreen, the real
NetworkGameSession/NetworkClient, and the real server/ws_server.py talking
to each other over an actual local WebSocket connection - no hand-crafted
JSON or text on either side. This is what actually proves a click in the
GUI ends up moving a piece on the server and back, closing the gap between
the client's outgoing protocol and server/protocol.py's text commands.
"""
import asyncio
import time

import websockets

from bus.event_bus import EventBus
from config import settings
from server.ws_server import GameServer, build_engine
from view.game_screen import GameScreen
from view.graphics_renderer import SIDE_PANEL_WIDTH
from view.img import Img
from view.network_game_session import NetworkGameSession


async def _wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def _wait_for_a_snapshot(screen, canvas):
    """Renders (draining the session's queue - see GameScreen.render)
    until a snapshot has actually arrived from the server."""
    def has_snapshot():
        screen.render(canvas)
        return screen._last_snapshot is not None

    await _wait_until(has_snapshot)


async def _tick_loop(server):
    """Stands in for serve_forever's own tick loop - these tests drive
    websockets.serve directly (to reach into `engine` without going
    through serve_forever's port-reporting indirection), so they need to
    advance the server's clock themselves the same way production does."""
    while True:
        await asyncio.sleep(0.05)
        await server.tick()


def test_a_real_gui_click_reaches_the_real_server_and_moves_a_piece():
    async def scenario():
        engine = build_engine(["wR . .", ". . .", ". . bK"], settings)
        server = GameServer(engine)

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            events = EventBus()
            session = NetworkGameSession(f"ws://127.0.0.1:{port}", events)
            screen = GameScreen(settings, session, board_x_offset=SIDE_PANEL_WIDTH)
            canvas = Img.create(1, 1)
            tick_task = asyncio.create_task(_tick_loop(server))
            try:
                await _wait_for_a_snapshot(screen, canvas)
                assert screen._last_snapshot.cells[0][0] == "wR"

                # Two real clicks on the rendered board, exactly like a
                # player's mouse would produce, through the real
                # GameScreen -> NetworkGameSession -> NetworkClient path.
                screen.handle_click(SIDE_PANEL_WIDTH + 0 * settings.CELL_SIZE, 0)
                screen.handle_click(SIDE_PANEL_WIDTH + 2 * settings.CELL_SIZE, 0)

                def rook_is_in_flight():
                    screen.render(canvas)
                    moves = screen._last_snapshot.moves
                    return bool(moves) and moves[0].piece == "wR"

                assert await _wait_until(rook_is_in_flight)
                assert screen._last_snapshot.moves[0].start == (0, 0)
                assert screen._last_snapshot.moves[0].end == (0, 2)

                # And it actually lands on the server-owned GameEngine too,
                # not just in the decoded client-side snapshot.
                assert await _wait_until(lambda: engine.snapshot().cells[0][2] == "wR")
            finally:
                session.close()
                tick_task.cancel()

    asyncio.run(scenario())


def test_two_real_clients_playing_through_the_full_stack_see_the_same_state():
    async def scenario():
        engine = build_engine(["wR . .", ". . .", ". . bK"], settings)
        server = GameServer(engine)

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"
            events_a, events_b = EventBus(), EventBus()
            session_a = NetworkGameSession(url, events_a)
            session_b = NetworkGameSession(url, events_b)
            screen_a = GameScreen(settings, session_a, board_x_offset=SIDE_PANEL_WIDTH)
            screen_b = GameScreen(settings, session_b, board_x_offset=SIDE_PANEL_WIDTH)
            canvas_a, canvas_b = Img.create(1, 1), Img.create(1, 1)
            tick_task = asyncio.create_task(_tick_loop(server))
            try:
                await _wait_for_a_snapshot(screen_a, canvas_a)
                await _wait_for_a_snapshot(screen_b, canvas_b)

                # Player A moves the rook through their own GameScreen.
                screen_a.handle_click(SIDE_PANEL_WIDTH + 0 * settings.CELL_SIZE, 0)
                screen_a.handle_click(SIDE_PANEL_WIDTH + 2 * settings.CELL_SIZE, 0)

                def b_sees_the_move():
                    screen_b.render(canvas_b)
                    moves = screen_b._last_snapshot.moves
                    return bool(moves) and moves[0].piece == "wR"

                assert await _wait_until(b_sees_the_move)
                assert screen_b._last_snapshot.moves[0].start == (0, 0)
                assert screen_b._last_snapshot.moves[0].end == (0, 2)
            finally:
                session_a.close()
                session_b.close()
                tick_task.cancel()

    asyncio.run(scenario())
