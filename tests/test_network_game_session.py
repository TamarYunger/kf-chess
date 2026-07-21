import asyncio
import json
import time

import websockets

from bus.event_bus import EventBus
from view.network_client import NetworkClient
from view.network_game_session import NetworkGameSession


class FakeNetworkClient:
    """Stands in for view.network_client.NetworkClient - NetworkGameSession
    is tested against this fake here; NetworkClient itself already has its
    own real-websocket integration tests (tests/test_network_client.py)."""

    def __init__(self):
        self.started = False
        self.stopped = False
        self.sent = []
        self._queue = []

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def send(self, message):
        self.sent.append(message)

    def push(self, message):
        """Test helper: queues a message as if it arrived from the server."""
        self._queue.append(message)

    def drain(self):
        messages, self._queue = self._queue, []
        return messages


def make_session():
    client = FakeNetworkClient()
    events = EventBus()
    session = NetworkGameSession("ws://unused", events, network_client=client)
    return session, client, events


def test_starts_the_network_client_on_construction():
    session, client, events = make_session()

    assert client.started is True


def test_latest_snapshot_is_none_before_any_message_arrives():
    session, client, events = make_session()

    assert session.latest_snapshot() is None


def test_snapshot_message_is_decoded_and_returned():
    session, client, events = make_session()
    client.push({"type": "snapshot", "payload": {
        "cells": [["wK", ".", "."], [".", ".", "."], [".", ".", "."]],
        "width": 3, "height": 3, "game_over": False,
    }})

    snapshot = session.latest_snapshot()

    assert snapshot.width == 3
    assert snapshot.cells[0][0] == "wK"


def test_latest_snapshot_keeps_the_last_decoded_snapshot_once_the_queue_is_drained():
    session, client, events = make_session()
    client.push({"type": "snapshot", "payload": {
        "cells": [["wK"]], "width": 1, "height": 1, "game_over": False,
    }})
    session.latest_snapshot()

    second = session.latest_snapshot()  # nothing new queued

    assert second is not None
    assert second.cells == (("wK",),)


def test_every_message_is_republished_on_the_bus_by_type():
    session, client, events = make_session()
    received = []
    events.subscribe("connected", lambda payload: received.append(("connected", payload)))
    events.subscribe("connection_error", lambda payload: received.append(("connection_error", payload)))
    client.push({"type": "connected", "payload": None})
    client.push({"type": "connection_error", "payload": {"error": "boom"}})

    session.latest_snapshot()

    assert received == [
        ("connected", None),
        ("connection_error", {"error": "boom"}),
    ]


def test_submit_command_forwards_to_the_network_client():
    session, client, events = make_session()

    session.submit_command({"type": "click", "cell": (0, 0)})

    assert client.sent == [{"type": "click", "cell": (0, 0)}]


def test_close_stops_the_network_client():
    session, client, events = make_session()

    session.close()

    assert client.stopped is True


def test_end_to_end_against_a_real_websocket_server():
    # Confirms the default (no injected fake) wiring - a real NetworkClient
    # underneath - actually round-trips: a server-sent "snapshot" message
    # is decoded, and a submitted command reaches the server.
    async def scenario():
        received_from_client = []
        connected = asyncio.Event()

        async def handler(connection):
            connected.set()
            await connection.send(json.dumps({"type": "snapshot", "payload": {
                "cells": [["wK"]], "width": 1, "height": 1, "game_over": False,
            }}))
            async for raw in connection:
                received_from_client.append(json.loads(raw))

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            events = EventBus()
            client = NetworkClient(f"ws://127.0.0.1:{port}", close_timeout=0.5, open_timeout=5, reconnect_delay=0.1)
            session = NetworkGameSession("unused", events, network_client=client)
            try:
                await asyncio.wait_for(connected.wait(), timeout=5.0)

                deadline = time.time() + 5.0
                snapshot = session.latest_snapshot()
                while snapshot is None and time.time() < deadline:
                    await asyncio.sleep(0.02)
                    snapshot = session.latest_snapshot()
                assert snapshot is not None and snapshot.width == 1

                session.submit_command({"type": "click", "cell": (0, 0)})
                deadline = time.time() + 5.0
                while not received_from_client and time.time() < deadline:
                    await asyncio.sleep(0.02)
                assert received_from_client == [{"type": "click", "cell": [0, 0]}]
            finally:
                session.close()

    asyncio.run(scenario())
