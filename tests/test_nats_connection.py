"""server/nats_connection.py's own tests - NatsConnectionProxy against a
fake NATS client and a real fakeredis registry (same in-memory-fake
convention as tests/test_ws_server.py uses for Redis)."""
import asyncio
import json

import fakeredis

from server.nats_connection import NatsConnectionProxy


class FakeNatsClient:
    """Stands in for nats.aio.client.Client - just enough of publish() to
    drive NatsConnectionProxy in tests without a running NATS server (see
    tests/test_shard_nats_integration.py for the one test against a real
    NATS)."""

    def __init__(self):
        self.published = []  # (subject, payload) pairs

    async def publish(self, subject, payload):
        self.published.append((subject, payload))


def run(coro):
    return asyncio.run(coro)


def test_send_publishes_to_the_owning_instances_outbox():
    async def scenario():
        nats_client = FakeNatsClient()
        redis_client = fakeredis.FakeRedis()
        redis_client.set("connection:conn-1", "instance-a")
        proxy = NatsConnectionProxy(nats_client, redis_client, "conn-1")

        await proxy.send('{"type": "snapshot"}')

        assert len(nats_client.published) == 1
        subject, payload = nats_client.published[0]
        assert subject == "outbox.instance-a"
        assert json.loads(payload) == {"connection_id": "conn-1", "message": '{"type": "snapshot"}'}

    run(scenario())


def test_send_looks_up_a_different_instance_for_a_different_connection():
    async def scenario():
        nats_client = FakeNatsClient()
        redis_client = fakeredis.FakeRedis()
        redis_client.set("connection:conn-1", "instance-a")
        redis_client.set("connection:conn-2", "instance-b")

        await NatsConnectionProxy(nats_client, redis_client, "conn-1").send("one")
        await NatsConnectionProxy(nats_client, redis_client, "conn-2").send("two")

        subjects = [subject for subject, _ in nats_client.published]
        assert subjects == ["outbox.instance-a", "outbox.instance-b"]

    run(scenario())


def test_send_is_a_no_op_if_the_registry_entry_is_gone():
    # The owning Gateway instance's registration expired/was never there -
    # nothing to deliver to, and nothing should be published.
    async def scenario():
        nats_client = FakeNatsClient()
        redis_client = fakeredis.FakeRedis()
        proxy = NatsConnectionProxy(nats_client, redis_client, "conn-unknown")

        await proxy.send("hello")

        assert nats_client.published == []

    run(scenario())
