"""Full-stack integration tests: the real GameScreen, the real
NetworkGameSession/NetworkClient, and the real server/ws_server.py talking
to each other over an actual local WebSocket connection - no hand-crafted
JSON or text on either side. This is what actually proves a click in the
GUI ends up moving a piece on the server and back, closing the gap between
the client's outgoing protocol and server/protocol.py's text commands.
"""
import asyncio
import json
import time

import fakeredis
import websockets
from aiohttp.test_utils import TestServer

from bus.event_bus import EventBus
from config import settings
from server.api_gateway import build_app as build_api_gateway_app
from server.db import AccountStore
from server.shard import GameShard
from server.ws_server import GameServer
from client.session.network_game_session import NetworkGameSession
from client.view.game_screen import GameScreen
from client.view.graphics_renderer import SIDE_PANEL_WIDTH
from client.view.img import Img
from client.view.screens.login_screen import BUTTON_HEIGHT, BUTTON_WIDTH, BUTTON_X, BUTTON_Y, LoginScreen


class FakeNatsClient:
    """In-memory stand-in for nats.aio.client.Client - lets a real
    GameServer (WS Gateway) and a real GameShard talk to each other with no
    real NATS server running, the same way fakeredis already stands in for
    Redis in these tests. publish() dispatches to subscribers synchronously.
    """

    def __init__(self):
        self._subscribers = {}  # subject -> list of async callbacks

    async def publish(self, subject, payload):
        for callback in self._subscribers.get(subject, []):
            await callback(_FakeMsg(subject, payload))

    async def subscribe(self, subject, cb):
        self._subscribers.setdefault(subject, []).append(cb)


class _FakeMsg:
    def __init__(self, subject, data):
        self.subject = subject
        self.data = data


async def make_gateway_stack(board_lines=None, accounts=None, redis_client=None):
    """A real GameServer (WS Gateway) + a real GameShard, wired together
    exactly as docker-compose.yml wires the two actual services - only
    NATS itself is faked (see FakeNatsClient), the same way this file
    already fakes Redis (fakeredis) for its real-socket tests."""
    nats_client = FakeNatsClient()
    redis_client = redis_client if redis_client is not None else fakeredis.FakeRedis()
    server = GameServer(config=settings, redis_client=redis_client, nats_client=nats_client)
    await server.start()
    shard = GameShard(nats_client, redis_client, config=settings, accounts=accounts, board_lines=board_lines)
    await nats_client.subscribe("shard.inbox", cb=shard.handle_message)
    return server, shard, redis_client


async def _wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def _wait_for_a_snapshot(screen, canvas):
    """Renders until a snapshot has actually arrived from the server - the
    session's own queue is drained by that session's `_pump` task, not by
    this render (see GameSession.tick's own docstring)."""
    def has_snapshot():
        screen.render(canvas)
        return screen._last_snapshot is not None

    await _wait_until(has_snapshot)


async def _tick_loop(server, shard):
    """Stands in for serve_forever's/shard.run_forever's own tick loops -
    these tests drive websockets.serve directly (to reach into
    `shard._rooms` without going through port-reporting indirection), so
    they need to advance both the Gateway's (matchmaking timeouts) and the
    Shard's (in-room real-time motion) clocks themselves, the same way
    production does with two separate processes each ticking their own."""
    while True:
        await asyncio.sleep(0.05)
        await server.tick()
        await shard.tick()


async def _pump(session):
    """Stands in for view/app_loop.py's run_app calling session.tick() once
    per frame, regardless of which screen is current - these tests drive a
    NetworkGameSession directly rather than through a real render loop, so
    something still has to keep draining its incoming-message queue (and
    republishing every message on the bus) for as long as the scenario
    runs, exactly like the real render loop does every frame (see
    GameSession.tick's own docstring for why this can't live inside a
    single screen's render() instead - that's the bug this shape replaced)."""
    while True:
        session.tick()
        await asyncio.sleep(0.02)


async def _connect(url, api_gateway_url="http://unused"):
    """A real NetworkGameSession, together with a background task that
    keeps ticking it (see `_pump`), waited on until the socket is actually
    connected (the "connected" event NetworkClient emits) - submit_command
    silently drops anything sent before then. `api_gateway_url` only
    matters to tests that actually exercise the REST /login hop (see
    test_login_flow_and_rating_update_through_the_full_stack below) -
    every other test here authenticates via `_login`'s token-seeding
    shortcut instead, which never calls the API Gateway at all."""
    events = EventBus()
    session = NetworkGameSession(url, events, api_gateway_url)
    pump = asyncio.create_task(_pump(session))
    connected = []
    events.subscribe("connected", lambda payload: connected.append(payload))
    await _wait_until(lambda: connected)
    return events, session, pump


async def _login(events, session, server, username, rating=1200):
    """Authenticates by seeding a token straight into `server`'s Redis and
    sending AUTH with it directly - the same shortcut
    tests/test_ws_server.py's own seed_token/authenticate use, and for the
    same reason: this file is about proving the real GameScreen ->
    NetworkGameSession -> NetworkClient -> real GameServer path for
    ROOM/PLAY/MOVE, not re-proving the REST /login hop itself (that's
    tests/test_api_gateway.py and tests/test_login_client.py's job -
    the one exception is test_login_flow_and_rating_update_through_the_full_stack
    below, which does go through a real API Gateway on purpose)."""
    token = f"tok-{username}"
    server._redis.set(f"token:{token}", json.dumps({"username": username, "rating": rating}))
    login_seen = []
    events.subscribe("login", lambda payload: login_seen.append(payload))
    session.submit_command(f"AUTH {token}")
    assert await _wait_until(lambda: login_seen)
    return login_seen[0]


async def _create_room(events, session):
    room_seen = []
    events.subscribe("room", lambda payload: room_seen.append(payload))
    session.submit_command("ROOM CREATE")
    assert await _wait_until(lambda: room_seen)
    return room_seen[0]


async def _join_room(events, session, room_id):
    room_seen = []
    events.subscribe("room", lambda payload: room_seen.append(payload))
    session.submit_command(f"ROOM JOIN {room_id}")
    assert await _wait_until(lambda: room_seen)
    return room_seen[0]


def test_a_real_gui_click_reaches_the_real_server_and_moves_a_piece():
    async def scenario():
        server, shard, redis_client = await make_gateway_stack(["wR . .", ". . .", ". . bK"])

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"
            tick_task = asyncio.create_task(_tick_loop(server, shard))
            events, session, pump = await _connect(url)
            events_b, session_b, pump_b = await _connect(url)
            try:
                await _login(events, session, server, "alice")
                await _login(events_b, session_b, server, "bob")
                room = await _create_room(events, session)
                room_id = room["room_id"]
                # A lone creator can't move yet (see server/room.py's own
                # started/waiting_for_opponent gate) - someone has to join.
                await _join_room(events_b, session_b, room_id)

                screen = GameScreen(settings, session, events, board_x_offset=SIDE_PANEL_WIDTH)
                canvas = Img.create(1, 1)
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

                # And it actually lands on the shard-owned room's engine
                # too, not just in the decoded client-side snapshot.
                room_engine = shard._rooms[room_id]._engine
                assert await _wait_until(lambda: room_engine.snapshot().cells[0][2] == "wR")
            finally:
                session.close()
                session_b.close()
                pump.cancel()
                pump_b.cancel()
                tick_task.cancel()

    asyncio.run(scenario())


def test_two_real_clients_playing_through_the_full_stack_see_the_same_state():
    async def scenario():
        server, shard, redis_client = await make_gateway_stack(["wR . .", ". . .", ". . bK"])

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"
            tick_task = asyncio.create_task(_tick_loop(server, shard))
            events_a, session_a, pump_a = await _connect(url)
            events_b, session_b, pump_b = await _connect(url)
            try:
                await _login(events_a, session_a, server, "alice")
                await _login(events_b, session_b, server, "bob")
                room = await _create_room(events_a, session_a)
                await _join_room(events_b, session_b, room["room_id"])

                screen_a = GameScreen(settings, session_a, events_a, board_x_offset=SIDE_PANEL_WIDTH)
                screen_b = GameScreen(settings, session_b, events_b, board_x_offset=SIDE_PANEL_WIDTH)
                canvas_a, canvas_b = Img.create(1, 1), Img.create(1, 1)
                await _wait_for_a_snapshot(screen_a, canvas_a)
                await _wait_for_a_snapshot(screen_b, canvas_b)

                # Player A (the room's creator) moves the rook through
                # their own GameScreen.
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
                pump_a.cancel()
                pump_b.cancel()
                tick_task.cancel()

    asyncio.run(scenario())


def test_three_real_clients_room_third_joiner_is_a_viewer_and_cannot_move():
    async def scenario():
        server, shard, redis_client = await make_gateway_stack(["wR . .", ". . .", ". . bK"])

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"
            tick_task = asyncio.create_task(_tick_loop(server, shard))
            events_a, session_a, pump_a = await _connect(url)
            events_b, session_b, pump_b = await _connect(url)
            events_c, session_c, pump_c = await _connect(url)
            try:
                await _login(events_a, session_a, server, "alice")
                await _login(events_b, session_b, server, "bob")
                await _login(events_c, session_c, server, "carol")
                # screen_c must exist (and so be subscribed to "room")
                # *before* carol joins - "room" is only ever published once,
                # right when the join happens, and GameScreen learning its
                # own role depends on catching that one event, not polling.
                screen_c = GameScreen(settings, session_c, events_c, board_x_offset=SIDE_PANEL_WIDTH)
                canvas_c = Img.create(1, 1)

                room = await _create_room(events_a, session_a)
                await _join_room(events_b, session_b, room["room_id"])
                carol_room = await _join_room(events_c, session_c, room["room_id"])
                assert carol_room["role"] == "viewer"
                await _wait_for_a_snapshot(screen_c, canvas_c)
                assert screen_c._role == "viewer"

                # Carol is a viewer - GameScreen itself won't even submit
                # a command for her click...
                screen_c.handle_click(SIDE_PANEL_WIDTH, 0)
                await asyncio.sleep(0.2)
                assert screen_c._last_snapshot.moves == ()

                # ...and bypassing that client-side gating entirely (e.g. a
                # raw command, not through handle_click) is still rejected
                # server-side, by the room itself.
                rejected = []
                events_c.subscribe("error", lambda payload: rejected.append(payload))
                session_c.submit_command({"type": "click", "cell": (0, 0)})
                session_c.submit_command({"type": "click", "cell": (0, 2)})
                assert await _wait_until(lambda: rejected)
                assert rejected[0]["message"] == "Only seated players can make moves"
            finally:
                session_a.close()
                session_b.close()
                session_c.close()
                pump_a.cancel()
                pump_b.cancel()
                pump_c.cancel()
                tick_task.cancel()

    asyncio.run(scenario())


def test_login_flow_and_rating_update_through_the_full_stack(tmp_path):
    # The whole feature end to end, across *both* services now (not just
    # the WS Gateway): a real LoginScreen click does a real REST POST
    # /login against a real server/api_gateway.py app, which shows the
    # real 401 rejection for a wrong password (not a hand-crafted event),
    # a correct password gets a real token that's redeemed over a real
    # AUTH on the WebSocket, both players join the same room, and
    # finishing a game updates both players' ratings in a real SQLite
    # file - not an in-memory stand-in - shared by both services exactly
    # as docker-compose.yml wires them in production.
    def type_text(field, text):
        for ch in text:
            field.handle_key(ord(ch))

    async def scenario():
        db_path = str(tmp_path / "accounts.db")
        accounts = AccountStore(db_path)
        accounts.authenticate("alice", "correct-password")  # alice already has an account
        redis_client = fakeredis.FakeRedis()  # shared by both services, like a real Redis would be
        server, shard, redis_client = await make_gateway_stack(
            ["wR . .", ". . .", "bK . ."], accounts=accounts, redis_client=redis_client,
        )
        api_gateway_app = build_api_gateway_app(accounts=accounts, redis_client=redis_client)

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server, \
                TestServer(api_gateway_app) as api_gateway:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"
            api_gateway_url = str(api_gateway.make_url(""))
            tick_task = asyncio.create_task(_tick_loop(server, shard))
            events_a, session_a, pump_a = await _connect(url, api_gateway_url)
            login_a = LoginScreen(session_a, events_a)
            session_b = None
            pump_b = None
            try:
                # Wrong password first - the real API Gateway rejects it
                # (a real 401 over a real HTTP connection), and that
                # rejection reaches LoginScreen's own error banner.
                login_a.handle_click(login_a._username_field.x + 5, login_a._username_field.y + 5)
                type_text(login_a._username_field, "alice")
                login_a.handle_click(login_a._password_field.x + 5, login_a._password_field.y + 5)
                type_text(login_a._password_field, "wrong-password")
                login_a.handle_click(BUTTON_X + BUTTON_WIDTH // 2, BUTTON_Y + BUTTON_HEIGHT // 2)

                def saw_the_rejection():
                    return login_a._error_message is not None

                assert await _wait_until(saw_the_rejection)
                assert login_a._error_message == "Invalid password"

                # Now the correct password.
                login_seen = []
                events_a.subscribe("login", lambda payload: login_seen.append(payload))
                login_a._password_field.clear()
                login_a._password_field.focus()
                type_text(login_a._password_field, "correct-password")
                login_a.handle_click(BUTTON_X + BUTTON_WIDTH // 2, BUTTON_Y + BUTTON_HEIGHT // 2)

                assert await _wait_until(lambda: login_seen)
                assert login_seen[0] == {"username": "alice", "rating": 1200}
                assert login_a._error_message is None

                # bob logs in fresh (no pre-existing account), straight
                # through the wire protocol (submit_command's dict shape)
                # rather than a second LoginScreen - LoginScreen's own send
                # path is already covered by the alice half above. Still a
                # real REST call, auto-creating his account exactly as
                # server/db.py's AccountStore.authenticate describes.
                events_b, session_b, pump_b = await _connect(url, api_gateway_url)
                bob_login_seen = []
                events_b.subscribe("login", lambda payload: bob_login_seen.append(payload))
                session_b.submit_command({"type": "login", "username": "bob", "password": "newpassword"})
                assert await _wait_until(lambda: bob_login_seen)
                assert bob_login_seen[0] == {"username": "bob", "rating": 1200}

                assert accounts.get_rating("alice") == 1200
                assert accounts.get_rating("bob") == 1200

                room = await _create_room(events_a, session_a)
                await _join_room(events_b, session_b, room["room_id"])
                alice_color = room["role"]

                # Whichever of the two ended up seated "w" captures the
                # other's king with its rook - an immediate game over
                # (KingCaptureWinCondition).
                room_engine = shard._rooms[room["room_id"]]._engine
                room_engine.request_move((0, 0), (2, 0))

                def game_finished_and_rated():
                    return room_engine.game_over and accounts.get_rating("alice") != 1200

                assert await _wait_until(game_finished_and_rated, timeout=8.0)
                if alice_color == room_engine.winner:
                    assert accounts.get_rating("alice") > 1200  # alice won
                    assert accounts.get_rating("bob") < 1200
                else:
                    assert accounts.get_rating("bob") > 1200  # bob won
                    assert accounts.get_rating("alice") < 1200
            finally:
                session_a.close()
                pump_a.cancel()
                if session_b is not None:
                    session_b.close()
                if pump_b is not None:
                    pump_b.cancel()
                tick_task.cancel()
                accounts.close()

    asyncio.run(scenario())


def test_matchmaking_real_disconnect_shows_countdown_then_auto_resigns():
    # The other half of the full stack this file already covers: two real
    # clients LOGIN and PLAY into a match (server.matchmaking), one of them
    # actually closes its socket (not a hand-crafted "opponent_disconnected"
    # event), and the survivor's real GameScreen picks up the countdown
    # overlay from that real disconnect. The 20s grace period itself is
    # sped up (poking the room's own _disconnected deadline) rather than
    # the test actually sleeping through it - the auto-resign/rating-
    # update timing itself is already covered by tests/test_room.py's
    # fake-connection tests; this test's job is the real-socket wiring
    # around it.
    async def scenario():
        server, shard, redis_client = await make_gateway_stack(["wK . .", ". . .", "bK . ."])

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"
            tick_task = asyncio.create_task(_tick_loop(server, shard))
            events_a, session_a, pump_a = await _connect(url)
            events_b, session_b, pump_b = await _connect(url)
            screen_a = GameScreen(settings, session_a, events_a, board_x_offset=SIDE_PANEL_WIDTH)
            screen_b = GameScreen(settings, session_b, events_b, board_x_offset=SIDE_PANEL_WIDTH)
            canvas_a, canvas_b = Img.create(1, 1), Img.create(1, 1)
            try:
                await _login(events_a, session_a, server, "alice")
                await _login(events_b, session_b, server, "bob")

                matched_a, matched_b = [], []
                events_a.subscribe("room", lambda p: matched_a.append(p))
                events_b.subscribe("room", lambda p: matched_b.append(p))
                session_a.submit_command("PLAY")
                session_b.submit_command("PLAY")
                assert await _wait_until(lambda: matched_a)
                assert await _wait_until(lambda: matched_b)
                alice_color = matched_a[0]["role"]
                bob_color = matched_b[0]["role"]
                room_id = matched_a[0]["room_id"]
                room = shard._rooms[room_id]

                await _wait_for_a_snapshot(screen_a, canvas_a)
                await _wait_for_a_snapshot(screen_b, canvas_b)

                # Bob's client actually drops the connection.
                session_b.close()
                pump_b.cancel()

                def alice_sees_the_countdown():
                    screen_a.render(canvas_a)
                    return screen_a._disconnect_deadline is not None

                assert await _wait_until(alice_sees_the_countdown)
                assert bob_color in room._disconnected

                resign_seen = []
                events_a.subscribe("resign", lambda p: resign_seen.append(p))

                # Speed the grace period up instead of sleeping 20s.
                room._disconnected[bob_color] = time.monotonic() - 1

                def alice_sees_game_over():
                    screen_a.render(canvas_a)
                    return screen_a._last_snapshot.game_over

                assert await _wait_until(alice_sees_game_over)
                assert room._engine.winner == alice_color
                # The real wire round-trip for the "resign" broadcast added
                # alongside "game_over" (server/protocol.py's encode_resign) -
                # tells alice's client *why* the game ended, not just that it did.
                assert resign_seen == [{"color": bob_color}]
            finally:
                session_a.close()
                session_b.close()
                pump_a.cancel()
                tick_task.cancel()

    asyncio.run(scenario())
