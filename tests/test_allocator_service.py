"""server/allocator_service.py's own tests - AllocatorService driven
directly with envelope dicts (the shape server/ws_server.py and server/
matchmaker_service.py publish to INBOX_SUBJECT), against a fake NATS
client and a fakeredis registry - mirrors tests/test_shard.py's and
tests/test_matchmaker_service.py's own conventions.
"""
import asyncio
import json
from types import SimpleNamespace

import aiohttp
import fakeredis

from server.allocator_service import (
    INBOX_SUBJECT, PRESENCE_TTL_SECONDS, AllocatorService, run_forever,
)


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


def make_service():
    nats_client = FakeNatsClient()
    redis_client = fakeredis.FakeRedis()
    return AllocatorService(nats_client, redis_client), nats_client, redis_client


def heartbeat(redis_client, instance_id, room_count):
    redis_client.set(f"shard:heartbeat:{instance_id}", room_count)


async def send(service, players):
    await service.handle_message(SimpleNamespace(data=json.dumps({"players": players}).encode("utf-8")))


ALICE = {"connection_id": "conn-1", "username": "alice", "rating": 1200}
BOB = {"connection_id": "conn-2", "username": "bob", "rating": 1200}


def test_a_single_known_shard_is_picked_regardless_of_load():
    async def scenario():
        service, nats_client, redis_client = make_service()
        heartbeat(redis_client, "shard-a", 5)

        await send(service, [ALICE])

        subject, payload = nats_client.published[0]
        assert subject == "shard.inbox.shard-a"
        envelope = json.loads(payload)
        assert envelope["kind"] == "create_room"
        assert envelope["players"] == [ALICE]

    run(scenario())


def test_power_of_two_choices_picks_the_less_loaded_of_two_known_shards():
    async def scenario():
        service, nats_client, redis_client = make_service()
        heartbeat(redis_client, "shard-busy", 9)
        heartbeat(redis_client, "shard-idle", 1)

        await send(service, [ALICE])

        subject, payload = nats_client.published[0]
        assert subject == "shard.inbox.shard-idle"

    run(scenario())


def test_no_reachable_shard_drops_the_request_without_publishing():
    async def scenario():
        service, nats_client, redis_client = make_service()

        await send(service, [ALICE])

        assert nats_client.published == []

    run(scenario())


def test_create_room_envelope_carries_both_players_for_a_matched_pair():
    async def scenario():
        service, nats_client, redis_client = make_service()
        heartbeat(redis_client, "shard-a", 0)

        await send(service, [ALICE, BOB])

        envelope = json.loads(nats_client.published[0][1])
        assert envelope["players"] == [ALICE, BOB]

    run(scenario())


def test_room_id_reserves_a_lease_with_the_expected_ttl():
    async def scenario():
        service, nats_client, redis_client = make_service()
        heartbeat(redis_client, "shard-a", 0)

        await send(service, [ALICE])

        envelope = json.loads(nats_client.published[0][1])
        room_id = envelope["room_id"]
        assert redis_client.get(f"room_owner:{room_id}").decode() == "shard-a"
        assert redis_client.ttl(f"room_owner:{room_id}") <= PRESENCE_TTL_SECONDS

    run(scenario())


def test_a_room_id_collision_is_retried(monkeypatch):
    async def scenario():
        service, nats_client, redis_client = make_service()
        heartbeat(redis_client, "shard-a", 0)
        redis_client.set("room_owner:aaaaaa", "shard-a", ex=PRESENCE_TTL_SECONDS)  # already taken

        ids = iter(["aaaaaa", "bbbbbb"])
        monkeypatch.setattr("server.allocator_service.secrets.token_hex", lambda n: next(ids))

        await send(service, [ALICE])

        envelope = json.loads(nats_client.published[0][1])
        assert envelope["room_id"] == "bbbbbb"

    run(scenario())


def test_a_malformed_envelope_is_logged_not_raised():
    async def scenario():
        service, nats_client, redis_client = make_service()

        await service.handle_message(SimpleNamespace(data=b"{}"))

    run(scenario())  # must not raise


def test_run_forever_subscribes_until_cancelled():
    async def scenario():
        nats_client = FakeNatsClient()
        redis_client = fakeredis.FakeRedis()
        heartbeat(redis_client, "shard-a", 0)
        ready = {}

        task = asyncio.create_task(run_forever(
            nats_client, redis_client,
            on_ready=lambda service, health_runner: ready.setdefault("service", service), health_port=0,
        ))
        await asyncio.sleep(0.05)
        task.cancel()

        assert "service" in ready
        await nats_client.publish(INBOX_SUBJECT, json.dumps({"players": [ALICE]}).encode("utf-8"))
        subject, payload = nats_client.published[-1]
        assert subject == "shard.inbox.shard-a"

    run(scenario())


def test_run_forever_exposes_a_real_health_endpoint():
    async def scenario():
        nats_client = FakeNatsClient()
        redis_client = fakeredis.FakeRedis()
        ready = {}

        task = asyncio.create_task(run_forever(
            nats_client, redis_client,
            on_ready=lambda service, health_runner: ready.update(service=service, health_runner=health_runner),
            health_port=0,
        ))
        try:
            while "health_runner" not in ready:
                await asyncio.sleep(0.01)

            port = ready["health_runner"].addresses[0][1]
            async with aiohttp.ClientSession() as session:
                health = await session.get(f"http://127.0.0.1:{port}/health")
                assert health.status == 200
                metrics = await session.get(f"http://127.0.0.1:{port}/metrics")
                assert await metrics.text() == ""  # no custom metrics for the Allocator - see run_forever
        finally:
            task.cancel()

    run(scenario())
