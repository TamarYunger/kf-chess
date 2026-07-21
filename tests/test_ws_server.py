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


# -- LOGIN: authentication only, no seat -------------------------------------


def test_login_authenticates_without_seating_anyone():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)

        conn = FakeConnection(incoming=["LOGIN alice pw1"])
        await server.handle_connection(conn)

        login = json.loads(conn.sent[1])
        assert login == {"type": "login", "payload": {"username": "alice", "rating": 1200}}
        assert len(server._seats) == 0

    run(scenario())


def test_relogin_confirms_the_same_identity():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)

        conn = FakeConnection(incoming=["LOGIN alice pw1", "LOGIN alice pw1"])
        await server.handle_connection(conn)

        assert json.loads(conn.sent[1]) == json.loads(conn.sent[2])

    run(scenario())


def test_two_different_logins_never_reject_each_other():
    # LOGIN itself has no "room full" concept any more - PLAY does the
    # seating, and only two colors can ever be seated at once (see the
    # matchmaking tests below).
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)

        alice = FakeConnection(incoming=["LOGIN alice pw1"])
        await server.handle_connection(alice)
        bob = FakeConnection(incoming=["LOGIN bob pw2"])
        await server.handle_connection(bob)
        carol = FakeConnection(incoming=["LOGIN carol pw3"])
        await server.handle_connection(carol)

        for conn in (alice, bob, carol):
            assert json.loads(conn.sent[1])["type"] == "login"

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


def test_wrong_password_is_rejected():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        accounts = AccountStore()
        accounts.authenticate("alice", "correct-password")  # pre-register the account
        server = GameServer(engine, accounts=accounts)

        conn = FakeConnection(incoming=["LOGIN alice wrong-password"])
        await server.handle_connection(conn)

        rejected = json.loads(conn.sent[1])
        assert rejected == {"type": "login_rejected", "payload": {"message": "Invalid password"}}

    run(scenario())


def test_correct_password_on_an_existing_account_reports_its_rating():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        accounts = AccountStore()
        accounts.authenticate("alice", "correct-password")
        accounts.update_rating("alice", 1350)
        server = GameServer(engine, accounts=accounts)

        conn = FakeConnection(incoming=["LOGIN alice correct-password"])
        await server.handle_connection(conn)

        login = json.loads(conn.sent[1])
        assert login == {"type": "login", "payload": {"username": "alice", "rating": 1350}}

    run(scenario())


# -- PLAY / matchmaking (fake connections) -----------------------------------


def test_play_before_login_is_rejected():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)

        conn = FakeConnection(incoming=["PLAY"])
        await server.handle_connection(conn)

        error = json.loads(conn.sent[1])
        assert error == {"type": "error", "payload": {"message": "Must LOGIN before PLAY"}}

    run(scenario())


def test_a_lone_play_request_just_queues_and_gets_no_immediate_reply():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)

        conn = FakeConnection(incoming=["LOGIN alice pw1", "PLAY"])
        await server.handle_connection(conn)

        # login confirmation only - PLAY produced no reply of its own yet.
        assert len(conn.sent) == 2
        assert conn not in server._seats.values()

    run(scenario())


def test_two_compatible_ratings_get_matched_with_different_colors():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)

        alice, bob = FakeConnection(), FakeConnection()
        await server._handle_login(alice, "alice", "pw1")
        await server._handle_login(bob, "bob", "pw2")
        await server._handle_play(alice)
        await server._handle_play(bob)

        alice_matched = json.loads(alice.sent[-1])
        bob_matched = json.loads(bob.sent[-1])
        assert alice_matched["type"] == "matched"
        assert bob_matched["type"] == "matched"
        assert {alice_matched["payload"]["color"], bob_matched["payload"]["color"]} == set(settings.COLORS)

    run(scenario())


def test_incompatible_ratings_are_not_matched():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        accounts = AccountStore()
        accounts.authenticate("alice", "pw1")
        accounts.update_rating("alice", 1000)
        accounts.authenticate("bob", "pw2")
        accounts.update_rating("bob", 1500)  # 500 apart - outside the default +-100 range
        server = GameServer(engine, accounts=accounts)

        alice, bob = FakeConnection(), FakeConnection()
        await server._handle_login(alice, "alice", "pw1")
        await server._handle_login(bob, "bob", "pw2")
        await server._handle_play(alice)
        await server._handle_play(bob)

        assert alice in server._queue
        assert bob in server._queue

    run(scenario())


def test_matched_players_are_removed_from_the_queue():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)

        alice, bob = FakeConnection(), FakeConnection()
        await server._handle_login(alice, "alice", "pw1")
        await server._handle_login(bob, "bob", "pw2")
        await server._handle_play(alice)
        await server._handle_play(bob)

        assert server._queue == {}
        assert len(server._seats) == 2

    run(scenario())


def test_play_again_once_already_seated_is_a_no_op():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)
        alice, bob = FakeConnection(), FakeConnection()
        await server._handle_login(alice, "alice", "pw1")
        await server._handle_login(bob, "bob", "pw2")
        await server._handle_play(alice)
        await server._handle_play(bob)
        sent_before = len(alice.sent)

        await server._handle_play(alice)

        assert len(alice.sent) == sent_before

    run(scenario())


def test_matchmaking_timeout_sends_no_match_and_clears_the_queue():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)
        conn = FakeConnection()
        await server._handle_login(conn, "alice", "pw1")
        await server._handle_play(conn)
        assert conn in server._queue

        server._queue[conn]["queued_at"] -= 61  # older than MATCHMAKING_TIMEOUT_SECONDS
        await server._resolve_matchmaking_timeouts(time.monotonic())

        assert conn not in server._queue
        no_match = json.loads(conn.sent[-1])
        assert no_match == {"type": "no_match", "payload": None}

    run(scenario())


def test_matchmaking_timeout_does_not_fire_early():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)
        conn = FakeConnection()
        await server._handle_login(conn, "alice", "pw1")
        await server._handle_play(conn)
        sent_before = len(conn.sent)

        await server._resolve_matchmaking_timeouts(time.monotonic())  # not yet 60s

        assert conn in server._queue
        assert len(conn.sent) == sent_before

    run(scenario())


# -- Disconnect grace period / auto-resign (fake connections) ---------------


def test_seated_players_disconnect_starts_a_grace_period():
    async def scenario():
        events = EventBus()
        engine = build_engine(["wK . .", ". . .", ". . ."], settings, events=events)
        server = GameServer(engine, events=events)
        alice, bob = FakeConnection(), FakeConnection()
        await server._handle_login(alice, "alice", "pw1")
        await server._handle_login(bob, "bob", "pw2")
        await server._handle_play(alice)
        await server._handle_play(bob)
        alice_color = server._seats[alice]
        server._clients.add(alice)
        server._clients.add(bob)

        server._clients.discard(alice)  # simulate the disconnect directly
        server._players.pop(alice, None)
        color = server._seats.pop(alice, None)
        await server._start_disconnect_countdown(color)

        assert alice_color in server._disconnected
        notice = json.loads(bob.sent[-1])
        assert notice == {
            "type": "opponent_disconnected", "payload": {"color": alice_color, "grace_period_seconds": 20},
        }

    run(scenario())


def test_reconnect_with_the_same_username_reclaims_the_seat_and_notifies():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)
        alice, bob = FakeConnection(), FakeConnection()
        await server._handle_login(alice, "alice", "pw1")
        await server._handle_login(bob, "bob", "pw2")
        await server._handle_play(alice)
        await server._handle_play(bob)
        alice_color = server._seats[alice]
        server._clients.add(bob)
        server._seats.pop(alice, None)
        await server._start_disconnect_countdown(alice_color)

        new_connection = FakeConnection()
        server._clients.add(new_connection)
        await server._handle_login(new_connection, "alice", "pw1")

        assert alice_color not in server._disconnected
        assert server._seats[new_connection] == alice_color
        reconnect_notice = json.loads(bob.sent[-1])
        assert reconnect_notice == {"type": "opponent_reconnected", "payload": {"color": alice_color}}

    run(scenario())


def test_a_different_username_cannot_reclaim_someone_elses_disconnected_seat():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)
        alice, bob = FakeConnection(), FakeConnection()
        await server._handle_login(alice, "alice", "pw1")
        await server._handle_login(bob, "bob", "pw2")
        await server._handle_play(alice)
        await server._handle_play(bob)
        alice_color = server._seats[alice]
        server._seats.pop(alice, None)
        await server._start_disconnect_countdown(alice_color)

        carol = FakeConnection()
        await server._handle_login(carol, "carol", "pw3")

        assert carol not in server._seats  # carol did not steal alice's reserved seat

    run(scenario())


def test_disconnect_timeout_auto_resigns_in_favor_of_the_other_color():
    async def scenario():
        events = EventBus()
        engine = build_engine(["wK . .", ". . .", ". . ."], settings, events=events)
        server = GameServer(engine, events=events)
        alice, bob = FakeConnection(), FakeConnection()
        await server._handle_login(alice, "alice", "pw1")
        await server._handle_login(bob, "bob", "pw2")
        await server._handle_play(alice)
        await server._handle_play(bob)
        alice_color = server._seats[alice]
        bob_color = server._seats[bob]
        server._seats.pop(alice, None)
        await server._start_disconnect_countdown(alice_color)

        server._disconnected[alice_color] = time.monotonic() - 1  # already past the deadline
        server._resolve_disconnect_timeouts(time.monotonic())

        assert engine.game_over is True
        assert engine.winner == bob_color
        assert alice_color not in server._disconnected

    run(scenario())


def test_no_disconnect_countdown_starts_once_the_game_is_already_over():
    async def scenario():
        engine = build_engine(["wR . .", ". . .", "bK . ."], settings)
        server = GameServer(engine)
        alice, bob = FakeConnection(), FakeConnection()
        await server._handle_login(alice, "alice", "pw1")
        await server._handle_login(bob, "bob", "pw2")
        await server._handle_play(alice)
        await server._handle_play(bob)
        engine.request_move((0, 0), (2, 0))
        engine.wait(3 * settings.MOVE_DURATION)
        assert engine.game_over is True
        server._clients.add(bob)

        server._clients.discard(alice)
        server._players.pop(alice, None)
        color = server._seats.pop(alice, None)
        if color is not None and not engine.game_over:
            await server._start_disconnect_countdown(color)  # mirrors handle_connection's own guard

        assert server._disconnected == {}

    run(scenario())


# -- Rating updates on game over ---------------------------------------------


def test_ratings_update_when_the_game_ends():
    async def scenario():
        events = EventBus()
        engine = build_engine(["wR . .", ". . .", "bK . ."], settings, events=events)
        accounts = AccountStore()
        server = GameServer(engine, accounts=accounts, events=events)

        conn_alice, conn_bob = FakeConnection(), FakeConnection()
        await server._handle_login(conn_alice, "alice", "pw1")
        await server._handle_login(conn_bob, "bob", "pw2")
        await server._handle_play(conn_alice)  # queues first (no opponent yet)
        await server._handle_play(conn_bob)  # matches - which connection gets which color is an
        # implementation detail (matchmaking assigns colors[0] to whoever calls PLAY *second*
        # here, since the first caller was the one already waiting) - read it back either way.
        alice_color = server._seats[conn_alice]
        assert accounts.get_rating("alice") == 1200
        assert accounts.get_rating("bob") == 1200

        # Whichever connection ended up seated "w" captures the other's
        # king with its rook - an immediate game over (KingCaptureWinCondition).
        engine.request_move((0, 0), (2, 0))
        engine.wait(3 * settings.MOVE_DURATION)

        assert engine.game_over is True
        winner_username = "alice" if alice_color == engine.winner else "bob"
        loser_username = "bob" if winner_username == "alice" else "alice"
        assert accounts.get_rating(winner_username) > 1200
        assert accounts.get_rating(loser_username) < 1200

    run(scenario())


def test_no_events_bus_means_ratings_are_simply_never_updated():
    # GameServer(engine) without events= (the default) - a valid, tested
    # configuration (every earlier test in this file uses it) - must not
    # crash when a game ends; it just doesn't touch the accounts store.
    async def scenario():
        engine = build_engine(["wR . .", ". . .", "bK . ."], settings)
        accounts = AccountStore()
        server = GameServer(engine, accounts=accounts)  # no events=

        conn_alice, conn_bob = FakeConnection(), FakeConnection()
        await server._handle_login(conn_alice, "alice", "pw1")
        await server._handle_login(conn_bob, "bob", "pw2")
        await server._handle_play(conn_alice)
        await server._handle_play(conn_bob)

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


def test_three_real_clients_can_all_log_in_no_room_full_rejection():
    # LOGIN itself never rejects for "room full" any more - only PLAY seats
    # a color, and only two of these three ever request that.
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

                assert alice_login == {"type": "login", "payload": {"username": "alice", "rating": 1200}}
                assert bob_login == {"type": "login", "payload": {"username": "bob", "rating": 1200}}
                assert carol_login == {"type": "login", "payload": {"username": "carol", "rating": 1200}}

    asyncio.run(scenario())


def test_two_real_clients_play_and_get_matched():
    async def scenario():
        engine = build_engine(["wK . .", ". . .", ". . ."], settings)
        server = GameServer(engine)

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"

            async with websockets.connect(url) as alice, websockets.connect(url) as bob:
                await alice.recv()
                await bob.recv()
                await alice.send("LOGIN alice pw1")
                await bob.send("LOGIN bob pw2")
                await alice.recv()
                await bob.recv()

                await alice.send("PLAY")
                await bob.send("PLAY")

                alice_matched = json.loads(await alice.recv())
                bob_matched = json.loads(await bob.recv())
                assert alice_matched["type"] == "matched"
                assert bob_matched["type"] == "matched"
                assert {alice_matched["payload"]["color"], bob_matched["payload"]["color"]} == set(settings.COLORS)

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
