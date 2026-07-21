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
from server.db import AccountStore
from server.ws_server import GameServer, build_engine
from view.game_screen import GameScreen
from view.graphics_renderer import SIDE_PANEL_WIDTH
from view.img import Img
from view.network_game_session import NetworkGameSession
from view.screens.login_screen import BUTTON_HEIGHT, BUTTON_WIDTH, BUTTON_X, BUTTON_Y, LoginScreen


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
            screen = GameScreen(settings, session, events, board_x_offset=SIDE_PANEL_WIDTH)
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
            screen_a = GameScreen(settings, session_a, events_a, board_x_offset=SIDE_PANEL_WIDTH)
            screen_b = GameScreen(settings, session_b, events_b, board_x_offset=SIDE_PANEL_WIDTH)
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


def test_login_flow_and_rating_update_through_the_full_stack(tmp_path):
    # The whole feature end to end: a real LoginScreen shows the server's
    # own rejection for a wrong password (not a hand-crafted event), a
    # correct password seats the player, and finishing a game updates both
    # players' ratings in a real SQLite file - not an in-memory stand-in.
    def type_text(field, text):
        for ch in text:
            field.handle_key(ord(ch))

    async def scenario():
        db_path = str(tmp_path / "accounts.db")
        accounts = AccountStore(db_path)
        accounts.authenticate("alice", "correct-password")  # alice already has an account
        events_bus = EventBus()
        engine = build_engine(["wR . .", ". . .", "bK . ."], settings, events=events_bus)
        server = GameServer(engine, accounts=accounts, events=events_bus)

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"
            tick_task = asyncio.create_task(_tick_loop(server))
            events_a = EventBus()
            session_a = NetworkGameSession(url, events_a)
            login_a = LoginScreen(session_a, events_a)
            canvas = Img.create(1, 1)
            session_b = None
            try:
                await _wait_until(lambda: session_a.latest_snapshot() is not None)

                # Wrong password first - the real server rejects it, and
                # that rejection reaches LoginScreen's own error banner.
                login_a.handle_click(login_a._username_field.x + 5, login_a._username_field.y + 5)
                type_text(login_a._username_field, "alice")
                login_a.handle_click(login_a._password_field.x + 5, login_a._password_field.y + 5)
                type_text(login_a._password_field, "wrong-password")
                login_a.handle_click(BUTTON_X + BUTTON_WIDTH // 2, BUTTON_Y + BUTTON_HEIGHT // 2)

                def saw_the_rejection():
                    session_a.latest_snapshot()  # drains the queue, publishing on events_a
                    return login_a._error_message is not None

                assert await _wait_until(saw_the_rejection)
                assert login_a._error_message == "Invalid password"

                # Now the correct password - alice gets seated as white.
                login_seen = []
                events_a.subscribe("login", lambda payload: login_seen.append(payload))
                login_a._password_field.clear()
                login_a._password_field.focus()
                type_text(login_a._password_field, "correct-password")
                login_a.handle_click(BUTTON_X + BUTTON_WIDTH // 2, BUTTON_Y + BUTTON_HEIGHT // 2)

                assert await _wait_until(lambda: (session_a.latest_snapshot() or True) and login_seen)
                assert login_seen[0] == {"username": "alice", "rating": 1200}
                assert login_a._error_message is None

                # bob logs in fresh (no pre-existing account), straight
                # through the wire protocol - LoginScreen's own send path
                # is already covered by the alice half above.
                events_b = EventBus()
                session_b = NetworkGameSession(url, events_b)
                bob_login_seen = []
                events_b.subscribe("login", lambda payload: bob_login_seen.append(payload))
                # submit_command's LOGIN branch is just a raw send() - it's
                # dropped, not queued, if the socket isn't connected yet
                # (NetworkClient.send), so wait for a snapshot (proof of a
                # live connection) before sending it.
                await _wait_until(lambda: session_b.latest_snapshot() is not None)
                session_b.submit_command("LOGIN bob newpassword")
                assert await _wait_until(lambda: (session_b.latest_snapshot() or True) and bob_login_seen)
                assert bob_login_seen[0] == {"username": "bob", "rating": 1200}

                assert accounts.get_rating("alice") == 1200
                assert accounts.get_rating("bob") == 1200

                # LOGIN alone seats nobody - PLAY (matchmaking, compatible
                # ratings) is what does that.
                alice_matched, bob_matched = [], []
                events_a.subscribe("matched", lambda payload: alice_matched.append(payload))
                events_b.subscribe("matched", lambda payload: bob_matched.append(payload))
                session_a.submit_command("PLAY")
                session_b.submit_command("PLAY")
                assert await _wait_until(lambda: (session_a.latest_snapshot() or True) and alice_matched)
                assert await _wait_until(lambda: (session_b.latest_snapshot() or True) and bob_matched)
                alice_color = alice_matched[0]["color"]

                # Whichever of the two ended up seated "w" captures the
                # other's king with its rook - an immediate game over
                # (KingCaptureWinCondition).
                engine.request_move((0, 0), (2, 0))

                def game_finished_and_rated():
                    return engine.game_over and accounts.get_rating("alice") != 1200

                assert await _wait_until(game_finished_and_rated, timeout=8.0)
                if alice_color == engine.winner:
                    assert accounts.get_rating("alice") > 1200  # alice won
                    assert accounts.get_rating("bob") < 1200
                else:
                    assert accounts.get_rating("bob") > 1200  # bob won
                    assert accounts.get_rating("alice") < 1200
            finally:
                session_a.close()
                if session_b is not None:
                    session_b.close()
                tick_task.cancel()
                accounts.close()

    asyncio.run(scenario())


def test_matchmaking_real_disconnect_shows_countdown_then_auto_resigns():
    # The other half of the full stack this file already covers: two real
    # clients LOGIN and PLAY into a match (server.matchmaking), one of them
    # actually closes its socket (not a hand-crafted "opponent_disconnected"
    # event), and the survivor's real GameScreen picks up the countdown
    # overlay from that real disconnect. The 20s grace period itself is
    # sped up (poking server._disconnected's deadline) rather than the test
    # actually sleeping through it - the auto-resign/rating-update timing
    # itself is already covered by tests/test_ws_server.py's fake-connection
    # tests; this test's job is the real-socket wiring around it.
    async def scenario():
        events_bus = EventBus()
        engine = build_engine(["wK . .", ". . .", "bK . ."], settings, events=events_bus)
        server = GameServer(engine, events=events_bus)

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"
            tick_task = asyncio.create_task(_tick_loop(server))
            events_a, events_b = EventBus(), EventBus()
            session_a = NetworkGameSession(url, events_a)
            session_b = NetworkGameSession(url, events_b)
            screen_a = GameScreen(settings, session_a, events_a, board_x_offset=SIDE_PANEL_WIDTH)
            screen_b = GameScreen(settings, session_b, events_b, board_x_offset=SIDE_PANEL_WIDTH)
            canvas_a, canvas_b = Img.create(1, 1), Img.create(1, 1)
            try:
                await _wait_for_a_snapshot(screen_a, canvas_a)
                await _wait_for_a_snapshot(screen_b, canvas_b)

                login_a, login_b = [], []
                events_a.subscribe("login", lambda p: login_a.append(p))
                events_b.subscribe("login", lambda p: login_b.append(p))
                session_a.submit_command("LOGIN alice pw1")
                session_b.submit_command("LOGIN bob pw2")
                assert await _wait_until(lambda: (session_a.latest_snapshot() or True) and login_a)
                assert await _wait_until(lambda: (session_b.latest_snapshot() or True) and login_b)

                matched_a, matched_b = [], []
                events_a.subscribe("matched", lambda p: matched_a.append(p))
                events_b.subscribe("matched", lambda p: matched_b.append(p))
                session_a.submit_command("PLAY")
                session_b.submit_command("PLAY")
                assert await _wait_until(lambda: (session_a.latest_snapshot() or True) and matched_a)
                assert await _wait_until(lambda: (session_b.latest_snapshot() or True) and matched_b)
                alice_color = matched_a[0]["color"]
                bob_color = matched_b[0]["color"]

                # Bob's client actually drops the connection.
                session_b.close()

                def alice_sees_the_countdown():
                    screen_a.render(canvas_a)
                    return screen_a._disconnect_deadline is not None

                assert await _wait_until(alice_sees_the_countdown)
                assert bob_color in server._disconnected

                # Speed the grace period up instead of sleeping 20s.
                server._disconnected[bob_color] = time.monotonic() - 1

                def alice_sees_game_over():
                    screen_a.render(canvas_a)
                    return screen_a._last_snapshot.game_over

                assert await _wait_until(alice_sees_game_over)
                assert engine.winner == alice_color
            finally:
                session_a.close()
                session_b.close()
                tick_task.cancel()

    asyncio.run(scenario())
