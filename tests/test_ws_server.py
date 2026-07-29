import asyncio
import json
import time

import fakeredis
import websockets

from config import settings
from server.allocator_service import AllocatorService
from server.matchmaker_service import MatchmakerService
from server.protocol import parse_command
from server.shard import GameShard
from server.ws_server import GameServer, _default_nats_client, serve_forever

# GameServer (the WS Gateway) no longer owns any server.room.Room/GameEngine
# at all - it only forwards to server.shard.py's GameShard over NATS (see
# both modules' own docstrings). Fine-grained per-game mechanics (seating,
# disconnect grace, Elo update, MOVE actually landing) are covered against
# GameShard directly in tests/test_shard.py and against server.room.Room
# directly in tests/test_room.py - this file is about GameServer as a
# *lobby*: AUTH, the matchmaking queue, and forwarding the right envelope
# to the right place - plus a handful of full-stack tests (GameServer +
# GameShard sharing one FakeNatsClient) proving the round trip these two
# processes depend on actually works, not just that each side works alone.


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


class FakeNatsClient:
    """In-memory stand-in for nats.aio.client.Client - just enough of
    publish()/subscribe() to drive GameServer (and, in the full-stack
    tests below, a real GameShard alongside it) without a running NATS
    server. publish() dispatches to subscribers synchronously, so a whole
    Gateway -> Shard -> Gateway round trip completes within one awaited
    call - no polling/sleeping needed to observe the result."""

    def __init__(self):
        self.published = []  # (subject, payload) pairs
        self._subscribers = {}  # subject -> list of async callbacks

    async def publish(self, subject, payload):
        self.published.append((subject, payload))
        for callback in self._subscribers.get(subject, []):
            await callback(_FakeMsg(subject, payload))

    async def subscribe(self, subject, cb):
        self._subscribers.setdefault(subject, []).append(cb)


class _FakeMsg:
    def __init__(self, subject, data):
        self.subject = subject
        self.data = data


def run(coro):
    return asyncio.run(coro)


def make_server(redis_client=None, nats_client=None, instance_id="instance-a"):
    # Tests generally want to inspect what got published, so this helper's
    # default is the FakeNatsClient test double, not GameServer's own
    # silently-drops-everything production default (_NullNatsClient).
    nats_client = nats_client if nats_client is not None else FakeNatsClient()
    return GameServer(config=settings, redis_client=redis_client, nats_client=nats_client, instance_id=instance_id)


def seed_token(redis_client, username, rating=1200, token=None):
    """Puts a token in `redis_client` exactly as server.api_gateway.py's
    real POST /login handler would after checking a password - this file
    never touches a password at all."""
    token = token or f"tok-{username}"
    redis_client.set(f"token:{token}", json.dumps({"username": username, "rating": rating}))
    return token


async def authenticate(server, connection, username, rating=1200):
    """seed_token + AUTH in one call - the test-side equivalent of "this
    connection already did a real REST login and is now presenting the
    token it got back"."""
    token = seed_token(server._redis, username, rating)
    await server._handle_auth(connection, token)


async def make_stack(board_lines=None):
    """A GameServer + a GameShard + a MatchmakerService + an
    AllocatorService sharing one FakeNatsClient and one fakeredis - the
    whole split, end to end, without a real NATS/Redis or even real
    sockets. This is what proves the round trip (WS Gateway -> NATS ->
    Matchmaker/Allocator/Shard -> NATS -> WS Gateway -> real connection)
    genuinely works, not just that each side works in isolation (which is
    all the rest of this file's tests check). The Shard's own tick() is
    called once up front to seed its heartbeat in Redis before returning -
    real docker-compose has it already ticking continuously by the time
    any request arrives, and the Allocator can't pick an instance that
    hasn't heartbeated at all yet (see server/allocator_service.py's own
    docstring)."""
    nats_client = FakeNatsClient()
    redis_client = fakeredis.FakeRedis()
    server = make_server(redis_client=redis_client, nats_client=nats_client)
    await server.start()
    shard = GameShard(nats_client, redis_client, config=settings,
                       board_lines=board_lines or ["wK . .", ". . .", ". . ."], instance_id="shard-a")
    await nats_client.subscribe("shard.inbox.shard-a", cb=shard.handle_message)
    await shard.tick()
    matchmaker = MatchmakerService(nats_client, redis_client)
    await nats_client.subscribe("matchmaker.inbox", cb=matchmaker.handle_message)
    allocator = AllocatorService(nats_client, redis_client)
    await nats_client.subscribe("allocator.inbox", cb=allocator.handle_message)
    return server, shard, redis_client


def test_default_nats_client_publish_and_subscribe_are_harmless_no_ops():
    # Mirrors _default_redis_client's own standalone-usability guarantee -
    # a GameServer with nothing injected (no real NATS reachable) must
    # still be constructible and usable; publish()/subscribe() on the
    # default just silently do nothing rather than raising.
    async def scenario():
        client = _default_nats_client()

        await client.publish("some.subject", b"payload")
        await client.subscribe("some.subject", cb=lambda msg: None)

    run(scenario())


# -- Bare connection lifecycle (no room yet) ---------------------------------


def test_bare_connection_receives_nothing_until_it_joins_a_room():
    async def scenario():
        server = make_server()
        conn = FakeConnection()

        await server.handle_connection(conn)

        assert conn.sent == []

    run(scenario())


def test_disconnect_without_ever_authenticating_is_harmless():
    async def scenario():
        server = make_server()
        conn = FakeConnection()

        await server.handle_connection(conn)  # connects, sends nothing, "disconnects"

        assert conn not in server._clients

    run(scenario())


def test_move_before_joining_any_room_is_rejected():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["MOVE a3 c3"])

        await server.handle_connection(conn)

        error = json.loads(conn.sent[0])
        assert error == {"type": "error", "payload": {"message": "Not in a room"}}

    run(scenario())


def test_malformed_command_replies_with_a_protocol_error():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["BOGUS"])

        await server.handle_connection(conn)

        error = json.loads(conn.sent[0])
        assert error == {"type": "error", "payload": {"message": "Unknown command: 'BOGUS'"}}

    run(scenario())


class FakeClosedConnection(FakeConnection):
    """A connection that's already gone by the time something tries to
    send to it - `_safe_send` must swallow this, not let it propagate."""

    async def send(self, message):
        raise websockets.exceptions.ConnectionClosed(None, None)


def test_safe_send_swallows_a_send_to_an_already_closed_connection():
    async def scenario():
        server = make_server()
        conn = FakeClosedConnection(incoming=["BOGUS"])

        await server.handle_connection(conn)  # must not raise despite the malformed command

        assert conn not in server._clients

    run(scenario())


# -- AUTH: authentication only, no room --------------------------------------


def test_auth_authenticates_without_joining_a_room():
    async def scenario():
        server = make_server()
        token = seed_token(server._redis, "alice")
        conn = FakeConnection(incoming=[f"AUTH {token}"])

        await server.handle_connection(conn)

        login = json.loads(conn.sent[0])
        assert login == {"type": "login", "payload": {"username": "alice", "rating": 1200}}
        assert conn not in server._connection_room

    run(scenario())


def test_auth_assigns_a_connection_id_and_registers_it_in_redis():
    async def scenario():
        server = make_server()
        token = seed_token(server._redis, "alice")
        conn = FakeConnection()

        await server._handle_auth(conn, token)

        connection_id = server._connection_ids[conn]
        assert server._connections_by_id[connection_id] is conn
        assert server._redis.get(f"connection:{connection_id}").decode() == "instance-a"

    run(scenario())


def test_reauth_confirms_the_same_identity():
    async def scenario():
        server = make_server()
        token = seed_token(server._redis, "alice")
        conn = FakeConnection(incoming=[f"AUTH {token}", f"AUTH {token}"])

        await server.handle_connection(conn)

        assert json.loads(conn.sent[0]) == json.loads(conn.sent[1])

    run(scenario())


def test_auth_with_an_unknown_token_is_rejected():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["AUTH nonexistent-token"])

        await server.handle_connection(conn)

        rejected = json.loads(conn.sent[0])
        assert rejected == {"type": "login_rejected", "payload": {"message": "Invalid or expired token"}}

    run(scenario())


def test_auth_token_is_single_use():
    async def scenario():
        server = make_server()
        token = seed_token(server._redis, "alice")
        first_conn = FakeConnection(incoming=[f"AUTH {token}"])
        await server.handle_connection(first_conn)
        assert json.loads(first_conn.sent[0])["type"] == "login"

        second_conn = FakeConnection(incoming=[f"AUTH {token}"])
        await server.handle_connection(second_conn)

        rejected = json.loads(second_conn.sent[0])
        assert rejected == {"type": "login_rejected", "payload": {"message": "Invalid or expired token"}}

    run(scenario())


# -- PLAY / matchmaking: forwarding only, actual matching is -----------------
# tests/test_matchmaker_service.py's - GameServer no longer runs
# find_opponent or holds a waiting queue itself (see server/ws_server.py's
# own docstring for why: a queue here would be per-Gateway-instance).


def test_play_before_auth_is_rejected():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["PLAY"])

        await server.handle_connection(conn)

        error = json.loads(conn.sent[0])
        assert error == {"type": "error", "payload": {"message": "Must AUTH before PLAY"}}

    run(scenario())


def test_play_forwards_a_play_envelope_to_the_matchmaker():
    async def scenario():
        server = make_server()
        conn = FakeConnection()
        await authenticate(server, conn, "alice")

        await server._handle_play(conn)

        subject, payload = server._nats.published[0]
        assert subject == "matchmaker.inbox"
        envelope = json.loads(payload)
        assert envelope == {
            "connection_id": server._connection_ids[conn], "username": "alice", "rating": 1200,
        }

    run(scenario())


def test_play_again_once_already_in_a_room_is_a_no_op():
    async def scenario():
        server = make_server()
        conn = FakeConnection()
        await authenticate(server, conn, "alice")
        # Simulates the "room" outbox message having already arrived (see
        # _handle_outbox_message) - normally only known once the Shard
        # replies, not immediately after PLAY.
        server._connection_room[conn] = "abc123"

        await server._handle_play(conn)

        assert server._nats.published == []  # nothing forwarded to the matchmaker

    run(scenario())


# -- ROOM CREATE / JOIN / MOVE: forwarding only -------------------------------
# ROOM CREATE forwards to the Allocator (tests/test_allocator_service.py's
# job from there); ROOM_JOIN/MOVE/JUMP/SELECT resolve room_owner:{room_id}
# from Redis to find which Shard instance to forward to - a missing entry
# is reported to the client as "Room not found" without ever reaching any
# Shard (see server/ws_server.py's own docstring).


def test_room_create_before_auth_is_rejected():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["ROOM CREATE"])

        await server.handle_connection(conn)

        error = json.loads(conn.sent[0])
        assert error == {"type": "error", "payload": {"message": "Must AUTH before ROOM CREATE"}}

    run(scenario())


def test_room_join_before_auth_is_rejected():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["ROOM JOIN abc123"])

        await server.handle_connection(conn)

        error = json.loads(conn.sent[0])
        assert error == {"type": "error", "payload": {"message": "Must AUTH before ROOM JOIN"}}

    run(scenario())


def test_room_create_forwards_a_need_room_envelope_to_the_allocator():
    async def scenario():
        server = make_server()
        conn = FakeConnection()
        await authenticate(server, conn, "alice")

        await server._handle_room_create(conn)

        subject, payload = server._nats.published[-1]
        assert subject == "allocator.inbox"
        envelope = json.loads(payload)
        assert envelope == {
            "players": [{
                "connection_id": server._connection_ids[conn], "username": "alice", "rating": 1200,
            }],
        }

    run(scenario())


def test_move_forwards_a_command_envelope_to_the_room_owning_shard():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["MOVE a3 c3"])
        await authenticate(server, conn, "alice")
        server._connection_room[conn] = "abc123"
        server._redis.set("room_owner:abc123", "shard-x")
        connection_id = server._connection_ids[conn]  # before handle_connection's own disconnect pops it

        await server.handle_connection(conn)

        subject, payload = server._nats.published[-2]  # last is the disconnect envelope, not this MOVE
        assert subject == "shard.inbox.shard-x"
        envelope = json.loads(payload)
        assert envelope == {
            "kind": "command", "connection_id": connection_id,
            "username": "alice", "rating": 1200, "room_id": "abc123", "raw": "MOVE a3 c3",
        }

    run(scenario())


def test_move_to_a_room_with_no_known_owner_is_rejected():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["MOVE a3 c3"])
        await authenticate(server, conn, "alice")
        server._connection_room[conn] = "abc123"  # no room_owner:abc123 registered - lease expired or never was

        await server.handle_connection(conn)

        error = json.loads(conn.sent[-1])
        assert error == {"type": "error", "payload": {"message": "Room 'abc123' not found"}}

    run(scenario())


def test_room_join_to_an_unregistered_room_is_rejected_without_reaching_any_shard():
    async def scenario():
        server = make_server()
        conn = FakeConnection(incoming=["ROOM JOIN nonexistent"])
        await authenticate(server, conn, "alice")

        await server.handle_connection(conn)

        error = json.loads(conn.sent[-1])
        assert error == {"type": "error", "payload": {"message": "Room 'nonexistent' not found"}}
        assert server._nats.published == []

    run(scenario())


# -- Outbox relay: the reply/broadcast path back from the Shard --------------


def test_outbox_message_is_relayed_to_the_right_local_connection():
    async def scenario():
        server = make_server()
        conn = FakeConnection()
        await authenticate(server, conn, "alice")
        connection_id = server._connection_ids[conn]

        envelope = json.dumps({
            "connection_id": connection_id,
            "message": json.dumps({"type": "no_match", "payload": None}),
        }).encode("utf-8")
        await server._handle_outbox_message(_FakeMsg("outbox.instance-a", envelope))

        assert json.loads(conn.sent[-1]) == {"type": "no_match", "payload": None}

    run(scenario())


def test_outbox_room_message_updates_local_connection_room_tracking():
    async def scenario():
        server = make_server()
        conn = FakeConnection()
        await authenticate(server, conn, "alice")
        connection_id = server._connection_ids[conn]

        room_message = json.dumps({"type": "room", "payload": {"room_id": "abc123", "role": "w"}})
        envelope = json.dumps({"connection_id": connection_id, "message": room_message}).encode("utf-8")
        await server._handle_outbox_message(_FakeMsg("outbox.instance-a", envelope))

        assert server._connection_room[conn] == "abc123"

    run(scenario())


def test_outbox_message_for_an_already_disconnected_connection_is_harmless():
    async def scenario():
        server = make_server()
        envelope = json.dumps({
            "connection_id": "nobody-here",
            "message": json.dumps({"type": "no_match", "payload": None}),
        }).encode("utf-8")

        await server._handle_outbox_message(_FakeMsg("outbox.instance-a", envelope))  # must not raise

    run(scenario())


# -- Disconnect: notifying the Shard ------------------------------------------


def test_disconnecting_a_seated_connection_publishes_a_disconnect_envelope():
    async def scenario():
        server = make_server()
        conn = FakeConnection()  # empty incoming - handle_connection's loop ends right away
        await authenticate(server, conn, "alice")
        connection_id = server._connection_ids[conn]
        server._connection_room[conn] = "abc123"
        server._redis.set("room_owner:abc123", "shard-x")

        await server.handle_connection(conn)

        subject, payload = server._nats.published[-1]
        assert subject == "shard.inbox.shard-x"
        assert json.loads(payload) == {"kind": "disconnect", "connection_id": connection_id, "room_id": "abc123"}
        assert connection_id not in server._connections_by_id
        assert server._redis.get(f"connection:{connection_id}") is None

    run(scenario())


def test_disconnecting_with_no_known_room_owner_publishes_nothing():
    async def scenario():
        server = make_server()
        conn = FakeConnection()  # empty incoming - handle_connection's loop ends right away
        await authenticate(server, conn, "alice")
        server._connection_room[conn] = "abc123"  # no room_owner:abc123 registered - lease expired or never was

        await server.handle_connection(conn)

        assert server._nats.published == []

    run(scenario())


def test_disconnecting_an_unauthenticated_connection_publishes_nothing():
    async def scenario():
        server = make_server()
        conn = FakeConnection()

        await server.handle_connection(conn)

        assert server._nats.published == []

    run(scenario())


# -- Full stack: GameServer + GameShard sharing one FakeNatsClient -----------


def test_full_stack_room_create_and_join_seats_both_players():
    async def scenario():
        server, shard, redis_client = await make_stack(["wR . .", ". . .", ". . ."])
        creator, joiner = FakeConnection(), FakeConnection()
        await authenticate(server, creator, "alice")
        await authenticate(server, joiner, "bob")

        await server._handle_message(creator, "ROOM CREATE")
        room_id = server._connection_room[creator]

        await server._handle_message(joiner, f"ROOM JOIN {room_id}")

        assert server._connection_room[creator] == room_id
        assert server._connection_room[joiner] == room_id
        room = shard._rooms[room_id]
        assert {room.role_of(shard._proxy_for(server._connection_ids[creator])),
                room.role_of(shard._proxy_for(server._connection_ids[joiner]))} == set(settings.COLORS)

    run(scenario())


def test_full_stack_matched_pair_can_then_move():
    async def scenario():
        server, shard, redis_client = await make_stack(["wR . .", ". . .", ". . ."])
        alice, bob = FakeConnection(), FakeConnection()
        await authenticate(server, alice, "alice")
        await authenticate(server, bob, "bob")

        await server._handle_message(alice, "PLAY")
        await server._handle_message(bob, "PLAY")

        assert server._connection_room[alice] == server._connection_room[bob]

        def role_of(conn):
            for message in conn.sent:
                decoded = json.loads(message)
                if decoded["type"] == "room":
                    return decoded["payload"]["role"]
            return None

        white_conn = alice if role_of(alice) == "w" else bob
        await server._handle_message(white_conn, "MOVE a3 c3")

        def saw_the_move(conn):
            return any(
                json.loads(m).get("type") == "snapshot" and json.loads(m)["payload"]["moves"]
                and json.loads(m)["payload"]["moves"][0]["piece"] == "wR"
                for m in conn.sent
            )

        assert saw_the_move(alice)
        assert saw_the_move(bob)

    run(scenario())


def test_full_stack_disconnect_starts_the_shard_side_grace_period():
    async def scenario():
        server, shard, redis_client = await make_stack()
        alice, bob = FakeConnection(), FakeConnection()
        await authenticate(server, alice, "alice")
        await authenticate(server, bob, "bob")
        await server._handle_message(alice, "PLAY")
        await server._handle_message(bob, "PLAY")
        room_id = server._connection_room[alice]
        room = shard._rooms[room_id]
        alice_color = room.role_of(shard._proxy_for(server._connection_ids[alice]))

        await server.handle_connection(alice)  # empty incoming - "disconnects" immediately

        assert alice_color in room._disconnected

    run(scenario())


# -- Real integration tests: actual websockets.serve + websockets.connect ---
# Still real sockets and real GameShard logic - only NATS itself is faked
# (see FakeNatsClient), the same way tests/test_client_server_integration.py
# already fakes Redis (fakeredis) for its own real-socket tests.


async def _shard_tick_loop(shard):
    while True:
        await asyncio.sleep(0.05)
        await shard.tick()


def test_two_real_clients_auth_play_and_move():
    async def scenario():
        server, shard, redis_client = await make_stack(["wR . .", ". . .", ". . ."])
        shard_tick_task = asyncio.create_task(_shard_tick_loop(shard))

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"

            async with websockets.connect(url) as alice, websockets.connect(url) as bob:
                alice_token = seed_token(redis_client, "alice", token="tok-alice-real")
                bob_token = seed_token(redis_client, "bob", token="tok-bob-real")
                await alice.send(f"AUTH {alice_token}")
                await bob.send(f"AUTH {bob_token}")
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
        shard_tick_task.cancel()

    asyncio.run(scenario())


def test_three_real_clients_room_create_join_and_viewer_rejection():
    async def scenario():
        server, shard, redis_client = await make_stack(["wR . .", ". . .", ". . ."])
        shard_tick_task = asyncio.create_task(_shard_tick_loop(shard))

        async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"

            async with (
                websockets.connect(url) as alice,
                websockets.connect(url) as bob,
                websockets.connect(url) as carol,
            ):
                await alice.send(f"AUTH {seed_token(redis_client, 'alice', token='tok-a')}")
                await bob.send(f"AUTH {seed_token(redis_client, 'bob', token='tok-b')}")
                await carol.send(f"AUTH {seed_token(redis_client, 'carol', token='tok-c')}")
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
        shard_tick_task.cancel()

    asyncio.run(scenario())


def test_periodic_tick_broadcasts_state_without_a_new_command():
    # The point of the Shard's own tick loop (a real asyncio timer wired to
    # RealTimeArbiter): a move landing must reach clients even if nobody
    # sends another command - driven purely by the background tick, now
    # running on the Shard side rather than the Gateway's (see
    # server/shard.py's run_forever vs server/ws_server.py's serve_forever -
    # the Gateway's own tick only resolves matchmaking timeouts these days).
    async def scenario():
        nats_client = FakeNatsClient()
        redis_client = fakeredis.FakeRedis()
        bound = {}

        def on_ready(ws_server, game_server):
            bound["port"] = ws_server.sockets[0].getsockname()[1]

        serve_task = asyncio.create_task(
            serve_forever(host="127.0.0.1", port=0, on_ready=on_ready,
                           redis_client=redis_client, nats_client=nats_client),
        )
        shard = GameShard(nats_client, redis_client, config=settings,
                           board_lines=["wR . .", ". . .", ". . ."], instance_id="shard-a")
        await nats_client.subscribe("shard.inbox.shard-a", cb=shard.handle_message)
        await shard.tick()  # seed the heartbeat before ROOM CREATE needs the Allocator to pick anything
        allocator = AllocatorService(nats_client, redis_client)
        await nats_client.subscribe("allocator.inbox", cb=allocator.handle_message)
        shard_tick_task = asyncio.create_task(_shard_tick_loop(shard))
        try:
            while "port" not in bound:
                await asyncio.sleep(0.01)
            url = f"ws://127.0.0.1:{bound['port']}"
            alice_token = seed_token(redis_client, "alice", token="tok-alice-tick")
            bob_token = seed_token(redis_client, "bob", token="tok-bob-tick")

            async with websockets.connect(url) as client, websockets.connect(url) as opponent:
                await client.send(f"AUTH {alice_token}")
                await client.recv()
                await client.send("ROOM CREATE")
                room_msg = json.loads(await client.recv())  # "room"
                room_id = room_msg["payload"]["room_id"]
                await client.recv()  # "waiting_for_opponent" - alone until someone joins
                await client.recv()  # initial snapshot

                await opponent.send(f"AUTH {bob_token}")
                await opponent.recv()
                await opponent.send(f"ROOM JOIN {room_id}")
                await opponent.recv()  # "room"
                await opponent.recv()  # snapshot
                await client.recv()  # "room_started" - alice's own waiting overlay clears

                await client.send("MOVE a3 c3")
                await client.recv()  # snapshot right after the move is accepted (still in flight)

                landed = False
                deadline = time.time() + (2 * settings.MOVE_DURATION) / 1000 + 3
                while time.time() < deadline:
                    message = json.loads(await asyncio.wait_for(client.recv(), timeout=2))
                    if message["type"] == "snapshot" and message["payload"]["cells"][0][2] == "wR":
                        landed = True
                        break
                assert landed
        finally:
            serve_task.cancel()
            shard_tick_task.cancel()

    asyncio.run(scenario())
