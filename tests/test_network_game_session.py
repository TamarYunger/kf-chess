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


def snapshot_message(width=3, height=3):
    return {
        "type": "snapshot",
        "payload": {
            "cells": [["." for _ in range(width)] for _ in range(height)],
            "width": width, "height": height, "game_over": False,
        },
    }


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

    session.tick()
    snapshot = session.latest_snapshot()

    assert snapshot.width == 3
    assert snapshot.cells[0][0] == "wK"


def test_latest_snapshot_keeps_the_last_decoded_snapshot_once_the_queue_is_drained():
    session, client, events = make_session()
    client.push({"type": "snapshot", "payload": {
        "cells": [["wK"]], "width": 1, "height": 1, "game_over": False,
    }})
    session.tick()
    session.latest_snapshot()

    second = session.latest_snapshot()  # nothing new queued, no further tick() needed

    assert second is not None
    assert second.cells == (("wK",),)


def test_every_message_is_republished_on_the_bus_by_type():
    session, client, events = make_session()
    received = []
    events.subscribe("connected", lambda payload: received.append(("connected", payload)))
    events.subscribe("connection_error", lambda payload: received.append(("connection_error", payload)))
    client.push({"type": "connected", "payload": None})
    client.push({"type": "connection_error", "payload": {"error": "boom"}})

    session.tick()

    assert received == [
        ("connected", None),
        ("connection_error", {"error": "boom"}),
    ]


def test_close_stops_the_network_client():
    session, client, events = make_session()

    session.close()

    assert client.stopped is True


def test_string_commands_are_forwarded_as_is():
    # LoginScreen's "LOGIN <username>" needs no cell/square translation.
    session, client, events = make_session()

    session.submit_command("LOGIN alice")

    assert client.sent == ["LOGIN alice"]


def test_click_before_any_snapshot_sends_nothing():
    # No board height is known yet to turn a cell into a square - matches
    # GameScreen never producing a click before it has a snapshot to
    # bounds-check against in the first place.
    session, client, events = make_session()

    session.submit_command({"type": "click", "cell": (0, 0)})

    assert client.sent == []


def test_first_click_does_not_send_anything_yet():
    session, client, events = make_session()
    client.push(snapshot_message())
    session.tick()

    session.submit_command({"type": "click", "cell": (0, 0)})

    assert client.sent == []


def test_second_click_sends_a_move_with_both_squares():
    session, client, events = make_session()
    client.push(snapshot_message())  # 3x3 board: (0,0) -> "a3", (0,2) -> "c3"
    session.tick()

    session.submit_command({"type": "click", "cell": (0, 0)})
    session.submit_command({"type": "click", "cell": (0, 2)})

    assert client.sent == ["MOVE a3 c3"]


def test_clicking_the_same_cell_twice_deselects_without_sending():
    session, client, events = make_session()
    client.push(snapshot_message())
    session.tick()

    session.submit_command({"type": "click", "cell": (0, 0)})
    session.submit_command({"type": "click", "cell": (0, 0)})
    session.tick()

    assert client.sent == []
    assert session.latest_snapshot().selected is None


def test_a_third_click_starts_a_new_selection():
    session, client, events = make_session()
    client.push(snapshot_message())
    session.tick()
    session.submit_command({"type": "click", "cell": (0, 0)})
    session.submit_command({"type": "click", "cell": (0, 0)})  # deselect

    session.submit_command({"type": "click", "cell": (1, 1)})
    session.tick()

    assert session.latest_snapshot().selected == (1, 1)


def test_jump_command_sends_jump_immediately():
    session, client, events = make_session()
    client.push(snapshot_message())
    session.tick()

    session.submit_command({"type": "jump", "cell": (0, 0)})

    assert client.sent == ["JUMP a3"]


def test_jump_clears_a_pending_selection():
    session, client, events = make_session()
    client.push(snapshot_message())
    session.tick()
    session.submit_command({"type": "click", "cell": (0, 0)})

    session.submit_command({"type": "jump", "cell": (1, 1)})
    session.tick()

    assert session.latest_snapshot().selected is None


def test_pending_selection_is_reflected_in_the_snapshot():
    session, client, events = make_session()
    client.push(snapshot_message())
    session.tick()

    session.submit_command({"type": "click", "cell": (0, 0)})
    session.tick()

    assert session.latest_snapshot().selected == (0, 0)


def test_rejected_message_sets_the_rejection_reason_on_the_snapshot():
    session, client, events = make_session()
    client.push(snapshot_message())
    session.tick()
    client.push({"type": "rejected", "payload": {"reason": "illegal_piece_move"}})

    session.tick()
    snapshot = session.latest_snapshot()

    assert snapshot.rejection_reason == "illegal_piece_move"


def test_a_fresh_first_click_clears_a_stale_rejection_reason():
    session, client, events = make_session()
    client.push(snapshot_message())
    session.tick()
    client.push({"type": "rejected", "payload": {"reason": "illegal_piece_move"}})
    session.tick()
    session.latest_snapshot()

    session.submit_command({"type": "click", "cell": (0, 0)})
    session.tick()

    assert session.latest_snapshot().rejection_reason is None


def test_end_to_end_against_a_real_websocket_server():
    # Confirms the default (no injected fake) wiring - a real NetworkClient
    # underneath - actually round-trips: a server-sent "snapshot" is
    # decoded, and two clicks reach the server as one real MOVE command.
    async def scenario():
        received_from_client = []
        connected = asyncio.Event()

        async def handler(connection):
            connected.set()
            await connection.send(json.dumps({"type": "snapshot", "payload": {
                "cells": [["wR", ".", "."], [".", ".", "."], [".", ".", "."]],
                "width": 3, "height": 3, "game_over": False,
            }}))
            async for raw in connection:
                received_from_client.append(raw)

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            events = EventBus()
            client = NetworkClient(f"ws://127.0.0.1:{port}", close_timeout=0.5, open_timeout=5, reconnect_delay=0.1)
            session = NetworkGameSession("unused", events, network_client=client)
            try:
                await asyncio.wait_for(connected.wait(), timeout=5.0)

                deadline = time.time() + 5.0
                session.tick()
                snapshot = session.latest_snapshot()
                while snapshot is None and time.time() < deadline:
                    await asyncio.sleep(0.02)
                    session.tick()
                    snapshot = session.latest_snapshot()
                assert snapshot is not None and snapshot.width == 3

                session.submit_command({"type": "click", "cell": (0, 0)})
                session.submit_command({"type": "click", "cell": (0, 2)})

                deadline = time.time() + 5.0
                while not received_from_client and time.time() < deadline:
                    await asyncio.sleep(0.02)
                # A genuine text command reached the server - not JSON, and
                # not double-encoded (see NetworkClient.send's str branch).
                assert received_from_client == ["MOVE a3 c3"]
            finally:
                session.close()

    asyncio.run(scenario())
