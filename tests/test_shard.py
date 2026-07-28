"""server/shard.py's own tests - GameShard driven directly with envelope
dicts (the shape server/ws_server.py publishes to INBOX_SUBJECT), against
a fake NATS client and a fakeredis registry - mirrors tests/test_ws_server.py's
FakeConnection convention, just one layer further down the stack (a NATS
message instead of a raw websocket frame).
"""
import asyncio
import json
from types import SimpleNamespace

import fakeredis

from config import settings
from server.shard import GameShard, INBOX_SUBJECT, run_forever


class FakeNatsClient:
    def __init__(self):
        self.published = []  # (subject, payload) pairs
        self._subscribers = {}  # subject -> list of async callbacks

    async def publish(self, subject, payload):
        self.published.append((subject, payload))
        for callback in self._subscribers.get(subject, []):
            await callback(SimpleNamespace(subject=subject, data=payload))

    async def subscribe(self, subject, cb):
        self._subscribers.setdefault(subject, []).append(cb)


def run(coro):
    return asyncio.run(coro)


def make_shard(board_lines=None, accounts=None):
    nats_client = FakeNatsClient()
    redis_client = fakeredis.FakeRedis()
    shard = GameShard(
        nats_client, redis_client, config=settings, accounts=accounts,
        board_lines=board_lines or ["wK . .", ". . .", ". . ."],
    )
    return shard, nats_client, redis_client


def register(redis_client, connection_id, instance_id="instance-a"):
    redis_client.set(f"connection:{connection_id}", instance_id)


def messages_for(nats_client, connection_id):
    """Every message actually addressed to connection_id, decoded, in the
    order they were published - regardless of which instance's outbox
    subject they went out on. Only looks at outbox.* publishes - other
    tests in this file also publish directly to INBOX_SUBJECT themselves
    (see send()/test_run_forever_...), whose envelopes aren't shaped like
    an outbox one at all (no "message" key)."""
    messages = []
    for subject, payload in nats_client.published:
        if not subject.startswith("outbox."):
            continue
        envelope = json.loads(payload)
        if envelope["connection_id"] == connection_id:
            messages.append(json.loads(envelope["message"]))
    return messages


async def send(shard, envelope):
    await shard.handle_message(SimpleNamespace(data=json.dumps(envelope).encode("utf-8")))


def test_room_create_seats_the_creator_and_replies_with_a_room_message():
    async def scenario():
        shard, nats_client, redis_client = make_shard()
        register(redis_client, "conn-1")

        await send(shard, {
            "kind": "command", "connection_id": "conn-1", "username": "alice", "rating": 1200,
            "room_id": None, "raw": "ROOM CREATE",
        })

        replies = messages_for(nats_client, "conn-1")
        assert replies[0]["type"] == "room"
        assert replies[0]["payload"]["role"] in settings.COLORS
        assert len(shard._rooms) == 1

    run(scenario())


def test_room_join_seats_the_second_connection_as_the_second_color():
    async def scenario():
        shard, nats_client, redis_client = make_shard()
        register(redis_client, "conn-1")
        register(redis_client, "conn-2")

        await send(shard, {
            "kind": "command", "connection_id": "conn-1", "username": "alice", "rating": 1200,
            "room_id": None, "raw": "ROOM CREATE",
        })
        room_id = messages_for(nats_client, "conn-1")[0]["payload"]["room_id"]

        await send(shard, {
            "kind": "command", "connection_id": "conn-2", "username": "bob", "rating": 1200,
            "room_id": None, "raw": f"ROOM JOIN {room_id}",
        })

        joiner_reply = messages_for(nats_client, "conn-2")[0]
        assert joiner_reply["type"] == "room"
        assert joiner_reply["payload"]["room_id"] == room_id
        room = shard._rooms[room_id]
        assert {room.role_of(shard._proxy_for("conn-1")), room.role_of(shard._proxy_for("conn-2"))} == \
            set(settings.COLORS)

    run(scenario())


def test_room_join_with_an_unknown_id_is_rejected():
    async def scenario():
        shard, nats_client, redis_client = make_shard()
        register(redis_client, "conn-1")

        await send(shard, {
            "kind": "command", "connection_id": "conn-1", "username": "alice", "rating": 1200,
            "room_id": None, "raw": "ROOM JOIN nonexistent",
        })

        error = messages_for(nats_client, "conn-1")[0]
        assert error == {"type": "error", "payload": {"message": "Room 'nonexistent' not found"}}

    run(scenario())


def test_matched_pair_are_both_welcomed_into_the_same_new_room():
    async def scenario():
        shard, nats_client, redis_client = make_shard()
        register(redis_client, "conn-1")
        register(redis_client, "conn-2")

        await send(shard, {
            "kind": "match",
            "players": [
                {"connection_id": "conn-1", "username": "alice", "rating": 1200},
                {"connection_id": "conn-2", "username": "bob", "rating": 1200},
            ],
        })

        alice_room = messages_for(nats_client, "conn-1")[0]
        bob_room = messages_for(nats_client, "conn-2")[0]
        assert alice_room["type"] == "room"
        assert bob_room["type"] == "room"
        assert alice_room["payload"]["room_id"] == bob_room["payload"]["room_id"]
        assert {alice_room["payload"]["role"], bob_room["payload"]["role"]} == set(settings.COLORS)

    run(scenario())


def test_move_in_a_room_broadcasts_to_both_seated_connections():
    async def scenario():
        shard, nats_client, redis_client = make_shard(["wR . .", ". . .", ". . ."])
        register(redis_client, "conn-1")
        register(redis_client, "conn-2")

        await send(shard, {
            "kind": "match",
            "players": [
                {"connection_id": "conn-1", "username": "alice", "rating": 1200},
                {"connection_id": "conn-2", "username": "bob", "rating": 1200},
            ],
        })
        room_id = messages_for(nats_client, "conn-1")[0]["payload"]["room_id"]

        await send(shard, {
            "kind": "command", "connection_id": "conn-1", "username": "alice", "rating": 1200,
            "room_id": room_id, "raw": "MOVE a3 c3",
        })

        # Both sides should have received a snapshot reflecting the move -
        # not just the mover.
        def saw_the_move(connection_id):
            for message in messages_for(nats_client, connection_id):
                if message["type"] == "snapshot" and message["payload"]["moves"]:
                    return message["payload"]["moves"][0]["piece"] == "wR"
            return False

        assert saw_the_move("conn-1")
        assert saw_the_move("conn-2")

    run(scenario())


def test_move_outside_any_room_is_rejected():
    async def scenario():
        shard, nats_client, redis_client = make_shard()
        register(redis_client, "conn-1")

        await send(shard, {
            "kind": "command", "connection_id": "conn-1", "username": "alice", "rating": 1200,
            "room_id": None, "raw": "MOVE a3 c3",
        })

        error = messages_for(nats_client, "conn-1")[0]
        assert error == {"type": "error", "payload": {"message": "Not in a room"}}

    run(scenario())


def test_malformed_command_replies_with_a_protocol_error_not_a_crash():
    async def scenario():
        shard, nats_client, redis_client = make_shard()
        register(redis_client, "conn-1")

        await send(shard, {
            "kind": "command", "connection_id": "conn-1", "username": "alice", "rating": 1200,
            "room_id": None, "raw": "BOGUS",
        })

        error = messages_for(nats_client, "conn-1")[0]
        assert error == {"type": "error", "payload": {"message": "Unknown command: 'BOGUS'"}}

    run(scenario())


def test_a_malformed_envelope_is_logged_not_raised():
    async def scenario():
        shard, nats_client, redis_client = make_shard()

        # Missing every expected key - handle_message must swallow this,
        # not crash the whole shard process over one bad message.
        await shard.handle_message(SimpleNamespace(data=b"{}"))

    run(scenario())  # must not raise


def test_disconnect_starts_the_room_grace_period():
    async def scenario():
        shard, nats_client, redis_client = make_shard()
        register(redis_client, "conn-1")
        register(redis_client, "conn-2")

        await send(shard, {
            "kind": "match",
            "players": [
                {"connection_id": "conn-1", "username": "alice", "rating": 1200},
                {"connection_id": "conn-2", "username": "bob", "rating": 1200},
            ],
        })
        room_id = messages_for(nats_client, "conn-1")[0]["payload"]["room_id"]
        room = shard._rooms[room_id]
        alice_color = room.role_of(shard._proxy_for("conn-1"))  # before disconnect pops the seat

        await send(shard, {"kind": "disconnect", "connection_id": "conn-1", "room_id": room_id})

        assert alice_color in room._disconnected

    run(scenario())


def test_disconnect_for_an_unknown_room_or_connection_is_harmless():
    async def scenario():
        shard, nats_client, redis_client = make_shard()

        await send(shard, {"kind": "disconnect", "connection_id": "conn-nobody", "room_id": "nonexistent"})

    run(scenario())  # must not raise


def test_new_room_regenerates_its_id_on_a_collision(monkeypatch):
    # secrets.token_hex(3) is 16M+ combinations - a real collision is not
    # something a test can wait for, so this forces one: the first id it
    # returns is already taken, so _generate_room_id must retry.
    shard, nats_client, redis_client = make_shard()
    shard._rooms["aaaaaa"] = object()
    ids = iter(["aaaaaa", "bbbbbb"])
    monkeypatch.setattr("server.shard.secrets.token_hex", lambda n: next(ids))

    room = shard._new_room()

    assert room.room_id == "bbbbbb"


def test_room_join_reconnect_notifies_the_opponent_still_in_the_room():
    async def scenario():
        shard, nats_client, redis_client = make_shard()
        register(redis_client, "conn-1")
        register(redis_client, "conn-2")

        await send(shard, {
            "kind": "match",
            "players": [
                {"connection_id": "conn-1", "username": "alice", "rating": 1200},
                {"connection_id": "conn-2", "username": "bob", "rating": 1200},
            ],
        })
        room_id = messages_for(nats_client, "conn-1")[0]["payload"]["room_id"]
        room = shard._rooms[room_id]
        bob_role = room.role_of(shard._proxy_for("conn-2"))

        await send(shard, {"kind": "disconnect", "connection_id": "conn-2", "room_id": room_id})

        # A fresh connection_id reconnecting as the same username reclaims
        # bob's seat - a real WS Gateway would give the reconnecting socket
        # a brand new connection_id, same as any other new connection.
        register(redis_client, "conn-2-reconnect")
        await send(shard, {
            "kind": "command", "connection_id": "conn-2-reconnect", "username": "bob", "rating": 1200,
            "room_id": None, "raw": f"ROOM JOIN {room_id}",
        })

        assert room.role_of(shard._proxy_for("conn-2-reconnect")) == bob_role
        reconnected_notice = [
            m for m in messages_for(nats_client, "conn-1") if m["type"] == "opponent_reconnected"
        ]
        assert reconnected_notice == [{"type": "opponent_reconnected", "payload": {"color": bob_role}}]

    run(scenario())


def test_run_forever_subscribes_and_ticks_until_cancelled():
    async def scenario():
        nats_client = FakeNatsClient()
        redis_client = fakeredis.FakeRedis()
        ready = {}

        task = asyncio.create_task(run_forever(
            nats_client, redis_client, config=settings, board_lines=["wK . .", ". . .", ". . ."],
            on_ready=lambda shard: ready.setdefault("shard", shard),
        ))
        await asyncio.sleep(0.15)  # let it subscribe and tick at least once
        task.cancel()

        assert "shard" in ready
        register(redis_client, "conn-1")
        await nats_client.publish(INBOX_SUBJECT, json.dumps({
            "kind": "command", "connection_id": "conn-1", "username": "alice", "rating": 1200,
            "room_id": None, "raw": "ROOM CREATE",
        }).encode("utf-8"))
        assert messages_for(nats_client, "conn-1")[0]["type"] == "room"

    run(scenario())
