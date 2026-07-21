import asyncio
import json
import time

import websockets

from bus.event_bus import EventBus
from config import settings
from server.db import AccountStore
from server.ws_server import GameServer, build_engine, serve_forever


class FakeConnection:
    """Stands in for a websockets connection object in the no-real-socket
    tests below - handle_connection only needs `send()` and async
    iteration (the messages a real client would have sent before
    disconnecting)."""

    def __init__(self, incoming=()):
        self._incoming = list(incoming)
        self.sent = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._incoming:
            raise StopAsyncIteration
        return self._incoming.pop(0)

    async def send(self, message):
        self.sent.append(message)


def run(coro):
    return asyncio.run(coro)


# -- GameServer against fake connections (no real socket) -------------------


def test_new_connection_receives_the_current_snapshot_immediately():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)
        conn = FakeConnection()

        await server.handle_connection(conn)

        assert len(conn.sent) == 1
        message = json.loads(conn.sent[0])
        assert message["type"] == "snapshot"
        assert message["payload"]["cells"][0][0] == "wK"

    run(scenario())


def test_valid_move_command_broadcasts_to_every_connected_client():
    async def scenario():
        engine = build_engine(["wR . .", ". . .", ". . ."], settings)
        server = GameServer(engine)
        listener = FakeConnection()
        server._clients.add(listener)

        mover = FakeConnection(incoming=["MOVE a3 c3"])
        await server.handle_connection(mover)

        # mover: initial snapshot + updated snapshot after the move.
        assert len(mover.sent) == 2
        # listener never sent anything, but still gets the broadcast.
        assert len(listener.sent) == 1
        moved = json.loads(mover.sent[1])
        broadcast = json.loads(listener.sent[0])
        assert moved == broadcast
        assert moved["payload"]["moves"][0]["piece"] == "wR"

    run(scenario())


def test_malformed_command_sends_only_an_error_to_the_sender():
    async def scenario():
        engine = build_engine(["wR . .", ". . .", ". . ."], settings)
        server = GameServer(engine)
        listener = FakeConnection()
        server._clients.add(listener)

        sender = FakeConnection(incoming=["FLY a3 c3"])
        await server.handle_connection(sender)

        error = json.loads(sender.sent[1])
        assert error["type"] == "error"
        assert listener.sent == []  # no broadcast for a rejected/malformed command

    run(scenario())


def test_illegal_move_sends_only_a_rejected_message_to_the_sender():
    async def scenario():
        engine = build_engine(["wN . .", ". . .", ". . ."], settings)
        server = GameServer(engine)
        listener = FakeConnection()
        server._clients.add(listener)

        sender = FakeConnection(incoming=["MOVE a3 b3"])  # not a legal knight move
        await server.handle_connection(sender)

        rejected = json.loads(sender.sent[1])
        assert rejected["type"] == "rejected"
        assert listener.sent == []

    run(scenario())


def test_disconnected_client_is_removed_from_broadcast_set():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)
        conn = FakeConnection()  # empty incoming -> handle_connection returns immediately

        await server.handle_connection(conn)

        assert conn not in server._clients

    run(scenario())


def test_tick_advances_the_engine_clock_and_broadcasts():
    async def scenario():
        engine = build_engine(["wR . .", ". . .", ". . ."], settings)
        server = GameServer(engine)
        engine.request_move((0, 0), (0, 2))
        listener = FakeConnection()
        server._clients.add(listener)

        server._last_tick -= (2 * settings.MOVE_DURATION) / 1000 + 0.1
        await server.tick()

        assert len(listener.sent) == 1
        message = json.loads(listener.sent[0])
        assert message["payload"]["cells"][0][2] == "wR"

    run(scenario())


# -- Seat assignment (fake connections) --------------------------------------


def test_first_login_is_assigned_the_first_configured_color():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)

        conn = FakeConnection(incoming=["LOGIN alice pw1"])
        await server.handle_connection(conn)

        login = json.loads(conn.sent[1])
        assert login == {"type": "login", "payload": {"color": settings.COLORS[0], "username": "alice"}}

    run(scenario())


def test_second_login_from_a_different_connection_gets_the_second_color():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)
        server._seats[FakeConnection()] = settings.COLORS[0]  # someone already seated first

        conn = FakeConnection(incoming=["LOGIN bob pw2"])
        await server.handle_connection(conn)

        login = json.loads(conn.sent[1])
        assert login == {"type": "login", "payload": {"color": settings.COLORS[1], "username": "bob"}}

    run(scenario())


def test_third_login_is_rejected_room_full():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)
        server._seats[FakeConnection()] = settings.COLORS[0]
        server._seats[FakeConnection()] = settings.COLORS[1]

        conn = FakeConnection(incoming=["LOGIN carol pw3"])
        await server.handle_connection(conn)

        rejected = json.loads(conn.sent[1])
        assert rejected == {"type": "login_rejected", "payload": {"message": "Room is full"}}

    run(scenario())


def test_relogin_from_an_already_seated_connection_returns_the_same_color():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)

        conn = FakeConnection(incoming=["LOGIN alice pw1", "LOGIN alice pw1"])
        await server.handle_connection(conn)

        first = json.loads(conn.sent[1])["payload"]["color"]
        second = json.loads(conn.sent[2])["payload"]["color"]
        # If the re-login had consumed a second seat, it would have been
        # assigned settings.COLORS[1] instead of repeating the same color.
        assert first == second

    run(scenario())


def test_disconnecting_frees_the_seat_for_the_next_login():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)

        first = FakeConnection(incoming=["LOGIN alice pw1"])
        await server.handle_connection(first)  # logs in, then "disconnects" (incoming exhausted)
        assert first not in server._seats

        second = FakeConnection(incoming=["LOGIN bob pw2"])
        await server.handle_connection(second)

        login = json.loads(second.sent[1])
        assert login["payload"]["color"] == settings.COLORS[0]  # the freed seat, not a rejection

    run(scenario())


def test_first_login_registers_the_account_at_the_default_rating():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        accounts = AccountStore()
        server = GameServer(engine, accounts=accounts)

        conn = FakeConnection(incoming=["LOGIN alice secret123"])
        await server.handle_connection(conn)

        assert accounts.get_rating("alice") == 1200

    run(scenario())


def test_wrong_password_is_rejected_and_consumes_no_seat():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        accounts = AccountStore()
        accounts.authenticate("alice", "correct-password")  # pre-register the account
        server = GameServer(engine, accounts=accounts)

        conn = FakeConnection(incoming=["LOGIN alice wrong-password"])
        await server.handle_connection(conn)

        rejected = json.loads(conn.sent[1])
        assert rejected == {"type": "login_rejected", "payload": {"message": "Invalid password"}}
        assert len(server._seats) == 0

    run(scenario())


def test_correct_password_on_an_existing_account_is_seated_normally():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        accounts = AccountStore()
        accounts.authenticate("alice", "correct-password")
        server = GameServer(engine, accounts=accounts)

        conn = FakeConnection(incoming=["LOGIN alice correct-password"])
        await server.handle_connection(conn)

        login = json.loads(conn.sent[1])
        assert login == {"type": "login", "payload": {"color": settings.COLORS[0], "username": "alice"}}

    run(scenario())


# -- Rating updates on game over ---------------------------------------------


def test_ratings_update_when_the_game_ends():
    async def scenario():
        events = EventBus()
        engine = build_engine(["wR . .", ". . .", "bK . ."], settings, events=events)
        accounts = AccountStore()
        server = GameServer(engine, accounts=accounts, events=events)

        # Seated directly via _handle_login (not handle_connection's full
        # per-message loop, which - being a FakeConnection whose incoming
        # queue would be immediately exhausted - would already have "hung
        # up" and freed the seat again by the time it returns; these two
        # need to stay seated while the game actually plays out below).
        white, black = FakeConnection(), FakeConnection()
        await server._handle_login(white, "alice", "pw1")
        await server._handle_login(black, "bob", "pw2")
        assert accounts.get_rating("alice") == 1200
        assert accounts.get_rating("bob") == 1200

        # White's rook captures black's king in one move - an immediate
        # game over (KingCaptureWinCondition), no waiting for it to land.
        engine.request_move((0, 0), (2, 0))
        engine.wait(3 * settings.MOVE_DURATION)

        assert engine.game_over is True
        assert accounts.get_rating("alice") > 1200  # winner gained rating
        assert accounts.get_rating("bob") < 1200  # loser lost rating

    run(scenario())


def test_no_events_bus_means_ratings_are_simply_never_updated():
    # GameServer(engine) without events= (the default) - a valid, tested
    # configuration (every earlier test in this file uses it) - must not
    # crash when a game ends; it just doesn't touch the accounts store.
    async def scenario():
        engine = build_engine(["wR . .", ". . .", "bK . ."], settings)
        accounts = AccountStore()
        server = GameServer(engine, accounts=accounts)  # no events=

        white, black = FakeConnection(), FakeConnection()
        await server._handle_login(white, "alice", "pw1")
        await server._handle_login(black, "bob", "pw2")

        engine.request_move((0, 0), (2, 0))
        engine.wait(3 * settings.MOVE_DURATION)

        assert engine.game_over is True
        assert accounts.get_rating("alice") == 1200
        assert accounts.get_rating("bob") == 1200

    run(scenario())


# -- Real integration tests: actual websockets.serve + websockets.connect ---


def test_two_clients_connect_send_moves_and_receive_matching_snapshots():
    async def scenario():
        engine = build_engine(["wR . .", ". . .", ". . ."], settings)
        server = GameServer(engine)

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"

            async with websockets.connect(url) as client_a, websockets.connect(url) as client_b:
                initial_a = json.loads(await client_a.recv())
                initial_b = json.loads(await client_b.recv())
                assert initial_a == initial_b
                assert initial_a["payload"]["cells"][0][0] == "wR"

                await client_a.send("MOVE a3 c3")

                updated_a = json.loads(await client_a.recv())
                updated_b = json.loads(await client_b.recv())
                assert updated_a == updated_b
                assert updated_a["payload"]["moves"][0] == {
                    "piece": "wR", "start": [0, 0], "end": [0, 2],
                    "arrival": updated_a["payload"]["moves"][0]["arrival"], "path": [[0, 1], [0, 2]],
                }

    asyncio.run(scenario())


def test_three_real_clients_login_first_two_seated_third_rejected():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"

            async with (
                websockets.connect(url) as alice,
                websockets.connect(url) as bob,
                websockets.connect(url) as carol,
            ):
                await alice.recv()  # initial snapshot, one per connection
                await bob.recv()
                await carol.recv()

                await alice.send("LOGIN alice pw1")
                await bob.send("LOGIN bob pw2")
                await carol.send("LOGIN carol pw3")

                alice_login = json.loads(await alice.recv())
                bob_login = json.loads(await bob.recv())
                carol_login = json.loads(await carol.recv())

                assert alice_login == {"type": "login", "payload": {"color": "w", "username": "alice"}}
                assert bob_login == {"type": "login", "payload": {"color": "b", "username": "bob"}}
                assert carol_login == {"type": "login_rejected", "payload": {"message": "Room is full"}}

    asyncio.run(scenario())


def test_periodic_tick_broadcasts_state_without_a_new_command():
    # The point of serve_forever's tick loop (a real asyncio timer wired to
    # RealTimeArbiter): a move landing must reach clients even if nobody
    # sends another command - driven purely by the background tick.
    async def scenario():
        engine = build_engine(["wR . .", ". . .", ". . ."], settings)
        bound = {}

        def on_ready(ws_server, game_server):
            bound["port"] = ws_server.sockets[0].getsockname()[1]

        serve_task = asyncio.create_task(
            serve_forever(engine, host="127.0.0.1", port=0, on_ready=on_ready)
        )
        try:
            while "port" not in bound:
                await asyncio.sleep(0.01)
            url = f"ws://127.0.0.1:{bound['port']}"

            async with websockets.connect(url) as client:
                await client.recv()  # initial snapshot
                await client.send("MOVE a3 c3")
                await client.recv()  # snapshot right after the move is accepted (still in flight)

                landed = False
                deadline = time.time() + (2 * settings.MOVE_DURATION) / 1000 + 3
                while time.time() < deadline:
                    message = json.loads(await asyncio.wait_for(client.recv(), timeout=2))
                    if message["payload"]["cells"][0][2] == "wR":
                        landed = True
                        break
                assert landed
        finally:
            serve_task.cancel()

    asyncio.run(scenario())
