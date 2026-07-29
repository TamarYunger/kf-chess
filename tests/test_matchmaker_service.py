"""server/matchmaker_service.py's own tests - MatchmakerService driven
directly with envelope dicts (the shape server/ws_server.py publishes to
INBOX_SUBJECT), against a fake NATS client and a fakeredis queue - mirrors
tests/test_shard.py's convention, one layer further up the stack (a PLAY
request instead of a MOVE/ROOM command).
"""
import asyncio
import json
from types import SimpleNamespace

import fakeredis

from server.matchmaker_service import (
    INBOX_SUBJECT, MatchmakerService, QUEUE_KEY, SHARD_INBOX_SUBJECT, run_forever,
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
    return MatchmakerService(nats_client, redis_client), nats_client, redis_client


def register(redis_client, connection_id, instance_id="instance-a"):
    """Same registry entry server/ws_server.py's own _handle_auth writes -
    needed so NatsConnectionProxy (used for the "no_match" reply) knows
    where to deliver to."""
    redis_client.set(f"connection:{connection_id}", instance_id)


async def send(service, envelope):
    await service.handle_message(SimpleNamespace(data=json.dumps(envelope).encode("utf-8")))


def outbox_messages_for(nats_client, connection_id):
    messages = []
    for subject, payload in nats_client.published:
        if not subject.startswith("outbox."):
            continue
        envelope = json.loads(payload)
        if envelope["connection_id"] == connection_id:
            messages.append(json.loads(envelope["message"]))
    return messages


def test_a_lone_play_request_just_queues_with_no_match_published():
    async def scenario():
        service, nats_client, redis_client = make_service()

        await send(service, {"connection_id": "conn-1", "username": "alice", "rating": 1200})

        assert redis_client.hexists(QUEUE_KEY, "conn-1")
        assert nats_client.published == []  # nothing to match yet

    run(scenario())


def test_compatible_pair_publishes_a_match_envelope_and_clears_the_queue():
    async def scenario():
        service, nats_client, redis_client = make_service()

        await send(service, {"connection_id": "conn-1", "username": "alice", "rating": 1200})
        await send(service, {"connection_id": "conn-2", "username": "bob", "rating": 1250})

        assert redis_client.hgetall(QUEUE_KEY) == {}
        subject, payload = nats_client.published[0]
        assert subject == SHARD_INBOX_SUBJECT
        envelope = json.loads(payload)
        assert envelope["kind"] == "match"
        connection_ids = {p["connection_id"] for p in envelope["players"]}
        assert connection_ids == {"conn-1", "conn-2"}

    run(scenario())


def test_incompatible_ratings_are_not_matched():
    async def scenario():
        service, nats_client, redis_client = make_service()

        await send(service, {"connection_id": "conn-1", "username": "alice", "rating": 1000})
        await send(service, {"connection_id": "conn-2", "username": "bob", "rating": 1500})  # outside +-100

        assert redis_client.hexists(QUEUE_KEY, "conn-1")
        assert redis_client.hexists(QUEUE_KEY, "conn-2")
        assert nats_client.published == []

    run(scenario())


def test_play_again_while_still_queued_is_a_no_op():
    async def scenario():
        service, nats_client, redis_client = make_service()
        await send(service, {"connection_id": "conn-1", "username": "alice", "rating": 1200})

        await send(service, {"connection_id": "conn-1", "username": "alice", "rating": 1200})

        assert nats_client.published == []  # still just queued, not matched against itself

    run(scenario())


def test_a_malformed_envelope_is_logged_not_raised():
    async def scenario():
        service, nats_client, redis_client = make_service()

        await service.handle_message(SimpleNamespace(data=b"{}"))

    run(scenario())  # must not raise


def test_timeout_sends_no_match_and_clears_the_queue():
    async def scenario():
        service, nats_client, redis_client = make_service()
        register(redis_client, "conn-1")
        await send(service, {"connection_id": "conn-1", "username": "alice", "rating": 1200})

        entry = json.loads(redis_client.hget(QUEUE_KEY, "conn-1"))
        entry["queued_at"] -= 61  # older than MATCHMAKING_TIMEOUT_SECONDS
        redis_client.hset(QUEUE_KEY, "conn-1", json.dumps(entry))

        await service.resolve_timeouts()

        assert not redis_client.hexists(QUEUE_KEY, "conn-1")
        no_match = outbox_messages_for(nats_client, "conn-1")[-1]
        assert no_match == {"type": "no_match", "payload": None}

    run(scenario())


def test_timeout_does_not_fire_early():
    async def scenario():
        service, nats_client, redis_client = make_service()
        register(redis_client, "conn-1")
        await send(service, {"connection_id": "conn-1", "username": "alice", "rating": 1200})

        await service.resolve_timeouts()  # not yet 60s

        assert redis_client.hexists(QUEUE_KEY, "conn-1")
        assert outbox_messages_for(nats_client, "conn-1") == []

    run(scenario())


def test_run_forever_subscribes_and_ticks_until_cancelled():
    async def scenario():
        nats_client = FakeNatsClient()
        redis_client = fakeredis.FakeRedis()
        ready = {}

        task = asyncio.create_task(run_forever(
            nats_client, redis_client, on_ready=lambda service: ready.setdefault("service", service),
        ))
        await asyncio.sleep(0.15)  # let it subscribe and tick at least once
        task.cancel()

        assert "service" in ready
        await nats_client.publish(INBOX_SUBJECT, json.dumps({
            "connection_id": "conn-1", "username": "alice", "rating": 1200,
        }).encode("utf-8"))
        assert redis_client.hexists(QUEUE_KEY, "conn-1")

    run(scenario())
