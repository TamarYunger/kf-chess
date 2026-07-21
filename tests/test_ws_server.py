import asyncio
import json
import time

import websockets

from config import settings
from server.db import AccountStore
from server.protocol import parse_command
from server.ws_server import GameServer, serve_forever

# Fine-grained per-game mechanics (seat/viewer assignment, disconnect grace
# period, reconnect reclaim, Elo update on game_over) are already covered
# in isolation by tests/test_room.py against server.room.Room directly -
# this file is about GameServer as a *lobby*: LOGIN, routing PLAY/ROOM
# CREATE/JOIN to the right (possibly brand new) Room, and routing a
# connection's MOVE/JUMP to whichever room it's actually in.


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


def make_server(board_lines=None, accounts=None):
    return GameServer(config=settings, accounts=accounts, board_lines=board_lines or ["wK . .", ". . .", ". . ."])


# -- Bare connection lifecycle (no room yet) ---------------------------------


def test_bare_connection_receives_nothing_until_it_joins_a_room():
    async def scenario():
        server = make_server()
        conn = FakeConnection()

        await server.handle_connection(conn)

        assert conn.sent == []

    run(scenario())


def test_disconnect_without_ever_logging_in_is_harmless():
    async def scenario():
        server = make_server()
        conn = FakeConnection()

        await server.handle_connection(conn)  # connects, sends nothing, "disconnects"

        assert conn not in server._clients

    run(scenario())


def test_move_before_joining_any_room_is_rejected():
    async def scenario():
        server = make_server(["wR . .", ". . .", ". . ."])
        conn = FakeConnection(incoming=["MOVE a3 c3"])

        await server.handle_connection(conn)

        error = json.loads(conn.sent[0])
        assert error == {"type": "error", "payload": {"message": "Not in a room"}}

    run(scenario())


# -- LOGIN: authentication only, no room -------------------------------------


def test_login_authenticates_without_joining_a_room():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["LOGIN alice pw1"])

        await server.handle_connection(conn)

        login = json.loads(conn.sent[0])
        assert login == {"type": "login", "payload": {"username": "alice", "rating": 1200}}
        assert conn not in server._connection_room

    run(scenario())


def test_relogin_confirms_the_same_identity():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["LOGIN alice pw1", "LOGIN alice pw1"])

        await server.handle_connection(conn)

        assert json.loads(conn.sent[0]) == json.loads(conn.sent[1])

    run(scenario())


def test_wrong_password_is_rejected():
    async def scenario():
        accounts = AccountStore()
        accounts.authenticate("alice", "correct-password")
        server = make_server(accounts=accounts)
        conn = FakeConnection(incoming=["LOGIN alice wrong-password"])

        await server.handle_connection(conn)

        rejected = json.loads(conn.sent[0])
        assert rejected == {"type": "login_rejected", "payload": {"message": "Invalid password"}}

    run(scenario())


def test_correct_password_reports_the_stored_rating():
    async def scenario():
        accounts = AccountStore()
        accounts.authenticate("alice", "correct-password")
        accounts.update_rating("alice", 1350)
        server = make_server(accounts=accounts)
        conn = FakeConnection(incoming=["LOGIN alice correct-password"])

        await server.handle_connection(conn)

        login = json.loads(conn.sent[0])
        assert login == {"type": "login", "payload": {"username": "alice", "rating": 1350}}

    run(scenario())


# -- PLAY / matchmaking -> creates a Room ------------------------------------


def test_play_before_login_is_rejected():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["PLAY"])

        await server.handle_connection(conn)

        error = json.loads(conn.sent[0])
        assert error == {"type": "error", "payload": {"message": "Must LOGIN before PLAY"}}

    run(scenario())


def test_a_lone_play_request_just_queues_with_no_immediate_room():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["LOGIN alice pw1", "PLAY"])

        await server.handle_connection(conn)

        assert len(conn.sent) == 1  # login confirmation only
        assert conn not in server._connection_room

    run(scenario())


def test_matched_pair_gets_seated_in_the_same_new_room():
    async def scenario():
        server = make_server()
        alice, bob = FakeConnection(), FakeConnection()
        await server._handle_login(alice, "alice", "pw1")
        await server._handle_login(bob, "bob", "pw2")

        await server._handle_play(alice)
        await server._handle_play(bob)

        assert len(server._rooms) == 1
        room_id = server._connection_room[alice]
        assert server._connection_room[bob] == room_id
        room = server._rooms[room_id]
        assert {room.role_of(alice), room.role_of(bob)} == set(settings.COLORS)

    run(scenario())


def test_matched_pair_each_receive_a_room_message_with_distinct_colors():
    async def scenario():
        server = make_server()
        alice, bob = FakeConnection(), FakeConnection()
        await server._handle_login(alice, "alice", "pw1")
        await server._handle_login(bob, "bob", "pw2")

        await server._handle_play(alice)
        await server._handle_play(bob)

        alice_room = json.loads(alice.sent[-2])  # "room" then "snapshot"
        bob_room = json.loads(bob.sent[-2])
        assert alice_room["type"] == "room"
        assert bob_room["type"] == "room"
        assert alice_room["payload"]["room_id"] == bob_room["payload"]["room_id"]
        assert {alice_room["payload"]["role"], bob_room["payload"]["role"]} == set(settings.COLORS)

    run(scenario())


def test_incompatible_ratings_are_not_matched():
    async def scenario():
        accounts = AccountStore()
        accounts.authenticate("alice", "pw1")
        accounts.update_rating("alice", 1000)
        accounts.authenticate("bob", "pw2")
        accounts.update_rating("bob", 1500)  # 500 apart - outside the default +-100 range
        server = make_server(accounts=accounts)
        alice, bob = FakeConnection(), FakeConnection()
        await server._handle_login(alice, "alice", "pw1")
        await server._handle_login(bob, "bob", "pw2")

        await server._handle_play(alice)
        await server._handle_play(bob)

        assert alice in server._queue
        assert bob in server._queue
        assert len(server._rooms) == 0

    run(scenario())


def test_matched_players_are_removed_from_the_queue():
    async def scenario():
        server = make_server()
        alice, bob = FakeConnection(), FakeConnection()
        await server._handle_login(alice, "alice", "pw1")
        await server._handle_login(bob, "bob", "pw2")

        await server._handle_play(alice)
        await server._handle_play(bob)

        assert server._queue == {}

    run(scenario())


def test_play_again_once_already_matched_is_a_no_op():
    async def scenario():
        server = make_server()
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
        server = make_server()
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
        server = make_server()
        conn = FakeConnection()
        await server._handle_login(conn, "alice", "pw1")
        await server._handle_play(conn)
        sent_before = len(conn.sent)

        await server._resolve_matchmaking_timeouts(time.monotonic())  # not yet 60s

        assert conn in server._queue
        assert len(conn.sent) == sent_before

    run(scenario())


# -- ROOM CREATE / JOIN -------------------------------------------------------


def test_room_create_before_login_is_rejected():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["ROOM CREATE"])

        await server.handle_connection(conn)

        error = json.loads(conn.sent[0])
        assert error == {"type": "error", "payload": {"message": "Must LOGIN before ROOM CREATE"}}

    run(scenario())


def test_room_join_before_login_is_rejected():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["ROOM JOIN abc123"])

        await server.handle_connection(conn)

        error = json.loads(conn.sent[0])
        assert error == {"type": "error", "payload": {"message": "Must LOGIN before ROOM JOIN"}}

    run(scenario())


def test_room_create_seats_the_creator_as_the_first_color():
    async def scenario():
        server = make_server()
        creator = FakeConnection()
        await server._handle_login(creator, "alice", "pw1")

        await server._handle_room_create(creator)

        room_id = server._connection_room[creator]
        room = server._rooms[room_id]
        assert room.role_of(creator) == settings.COLORS[0]
        room_msg = json.loads(creator.sent[-2])
        assert room_msg == {"type": "room", "payload": {"room_id": room_id, "role": settings.COLORS[0]}}

    run(scenario())


def test_room_join_seats_the_second_connection_as_the_second_color():
    async def scenario():
        server = make_server()
        creator, joiner = FakeConnection(), FakeConnection()
        await server._handle_login(creator, "alice", "pw1")
        await server._handle_login(joiner, "bob", "pw2")
        await server._handle_room_create(creator)
        room_id = server._connection_room[creator]

        await server._handle_room_join(joiner, room_id)

        room = server._rooms[room_id]
        assert room.role_of(joiner) == settings.COLORS[1]

    run(scenario())


def test_third_joiner_becomes_a_viewer():
    async def scenario():
        server = make_server()
        creator, second, third = FakeConnection(), FakeConnection(), FakeConnection()
        await server._handle_login(creator, "alice", "pw1")
        await server._handle_login(second, "bob", "pw2")
        await server._handle_login(third, "carol", "pw3")
        await server._handle_room_create(creator)
        room_id = server._connection_room[creator]
        await server._handle_room_join(second, room_id)

        await server._handle_room_join(third, room_id)

        room = server._rooms[room_id]
        assert room.role_of(third) == "viewer"
        room_msg = json.loads(third.sent[-2])
        assert room_msg["payload"]["role"] == "viewer"

    run(scenario())


def test_room_join_with_an_unknown_id_is_rejected():
    async def scenario():
        server = make_server()
        conn = FakeConnection()
        await server._handle_login(conn, "alice", "pw1")

        await server._handle_room_join(conn, "nonexistent")

        error = json.loads(conn.sent[-1])
        assert error == {"type": "error", "payload": {"message": "Room 'nonexistent' not found"}}

    run(scenario())


# -- MOVE/JUMP routing --------------------------------------------------------


def test_move_in_a_room_broadcasts_only_within_that_room():
    async def scenario():
        server = make_server(["wR . .", ". . .", ". . ."])
        alice, bob = FakeConnection(), FakeConnection()
        carol, dave = FakeConnection(), FakeConnection()
        for conn, name in ((alice, "alice"), (bob, "bob"), (carol, "carol"), (dave, "dave")):
            await server._handle_login(conn, name, "pw")
        await server._handle_room_create(alice)
        room_a_id = server._connection_room[alice]
        await server._handle_room_join(bob, room_a_id)
        await server._handle_room_create(carol)
        room_b_id = server._connection_room[carol]
        await server._handle_room_join(dave, room_b_id)
        assert room_a_id != room_b_id

        await server._rooms[room_a_id].handle_command(alice, parse_command("MOVE a3 c3"))

        moved = json.loads(bob.sent[-1])
        assert moved["payload"]["moves"][0]["piece"] == "wR"
        # Room B never saw any move.
        untouched = json.loads(dave.sent[-1])
        assert untouched["payload"]["moves"] == []

    run(scenario())


def test_disconnecting_a_seated_player_is_routed_to_their_room():
    async def scenario():
        server = make_server(["wK . .", ". . .", ". . ."])
        alice, bob = FakeConnection(), FakeConnection()
        await server._handle_login(alice, "alice", "pw1")
        await server._handle_login(bob, "bob", "pw2")
        await server._handle_play(alice)
        await server._handle_play(bob)
        room_id = server._connection_room[alice]
        room = server._rooms[room_id]
        alice_color = room.role_of(alice)

        # alice's incoming queue is empty - handle_connection's async-for
        # ends immediately, running its own finally block for real (the
        # thing under test), rather than this test replicating those steps.
        await server.handle_connection(alice)

        assert alice not in server._connection_room
        assert alice_color in room._disconnected

    run(scenario())


# -- Real integration tests: actual websockets.serve + websockets.connect ---


def test_two_real_clients_login_play_and_move():
    async def scenario():
        server = make_server(["wR . .", ". . .", ". . ."])

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"

            async with websockets.connect(url) as alice, websockets.connect(url) as bob:
                await alice.send("LOGIN alice pw1")
                await bob.send("LOGIN bob pw2")
                assert json.loads(await alice.recv())["type"] == "login"
                assert json.loads(await bob.recv())["type"] == "login"

                await alice.send("PLAY")
                await bob.send("PLAY")
                alice_room = json.loads(await alice.recv())
                bob_room = json.loads(await bob.recv())
                assert alice_room["type"] == "room"
                assert bob_room["type"] == "room"
                assert alice_room["payload"]["room_id"] == bob_room["payload"]["room_id"]
                await alice.recv()  # initial snapshot
                await bob.recv()

                white_conn = alice if alice_room["payload"]["role"] == "w" else bob
                await white_conn.send("MOVE a3 c3")

                updated_a = json.loads(await alice.recv())
                updated_b = json.loads(await bob.recv())
                assert updated_a == updated_b
                assert updated_a["payload"]["moves"][0]["piece"] == "wR"

    asyncio.run(scenario())


def test_three_real_clients_room_create_join_and_viewer_rejection():
    async def scenario():
        server = make_server(["wR . .", ". . .", ". . ."])

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"

            async with (
                websockets.connect(url) as alice,
                websockets.connect(url) as bob,
                websockets.connect(url) as carol,
            ):
                await alice.send("LOGIN alice pw1")
                await bob.send("LOGIN bob pw2")
                await carol.send("LOGIN carol pw3")
                await alice.recv()
                await bob.recv()
                await carol.recv()

                await alice.send("ROOM CREATE")
                alice_room = json.loads(await alice.recv())
                await alice.recv()  # snapshot
                room_id = alice_room["payload"]["room_id"]

                await bob.send(f"ROOM JOIN {room_id}")
                bob_room = json.loads(await bob.recv())
                await bob.recv()
                assert bob_room["payload"]["role"] != alice_room["payload"]["role"]

                await carol.send(f"ROOM JOIN {room_id}")
                carol_room = json.loads(await carol.recv())
                await carol.recv()
                assert carol_room["payload"]["role"] == "viewer"

                await carol.send("MOVE a3 c3")
                rejection = json.loads(await carol.recv())
                assert rejection == {"type": "error", "payload": {"message": "Only seated players can make moves"}}

    asyncio.run(scenario())


def test_periodic_tick_broadcasts_state_without_a_new_command():
    # The point of serve_forever's tick loop (a real asyncio timer wired to
    # RealTimeArbiter): a move landing must reach clients even if nobody
    # sends another command - driven purely by the background tick.
    async def scenario():
        bound = {}

        def on_ready(ws_server, game_server):
            bound["port"] = ws_server.sockets[0].getsockname()[1]

        serve_task = asyncio.create_task(
            serve_forever(host="127.0.0.1", port=0, on_ready=on_ready, board_lines=["wR . .", ". . .", ". . ."]),
        )
        try:
            while "port" not in bound:
                await asyncio.sleep(0.01)
            url = f"ws://127.0.0.1:{bound['port']}"

            async with websockets.connect(url) as client:
                await client.send("LOGIN alice pw1")
                await client.recv()
                await client.send("ROOM CREATE")
                await client.recv()  # "room"
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
