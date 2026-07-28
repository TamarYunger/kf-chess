"""NatsConnectionProxy: looks like a live connection to server/room.py's
Room (it only ever calls `.send(message)` on whatever it's given - see
server/safe_send.py) but isn't one. Reaching the real socket needs going
through NATS, because Room/GameEngine (server/shard.py) and the real
socket (server/ws_server.py) now live in two different processes - a
proxy is how Room stays completely unaware that split ever happened.

The registry (`connection:{id}` in Redis, written by ws_server.py when a
connection authenticates) is what makes this scale-appropriate rather
than a shortcut: a message is published to the *owning WS Gateway
instance's* channel (`outbox.{instance_id}`), not to a channel per
connection - one Gateway process subscribes to exactly one channel no
matter how many connections it's holding, not one channel per connection.
See Server_Design.md for why that distinction matters at real scale, and
why switching between the two later would need both sides changed at
once - this is the scale-appropriate version chosen up front instead.
"""
from __future__ import annotations

import json


class NatsConnectionProxy:
    def __init__(self, nats_client, redis_client, connection_id):
        self._nats = nats_client
        self._redis = redis_client
        self.connection_id = connection_id

    async def send(self, message):
        instance_id = self._redis.get(f"connection:{self.connection_id}")
        if instance_id is None:
            return  # the owning Gateway instance is gone - nothing to deliver to
        if isinstance(instance_id, bytes):
            instance_id = instance_id.decode("utf-8")
        envelope = json.dumps({"connection_id": self.connection_id, "message": message})
        await self._nats.publish(f"outbox.{instance_id}", envelope.encode("utf-8"))
