import asyncio
import json
import time

import websockets

from client.session.network_client import NetworkClient

POLL_TIMEOUT = 5.0


def make_client(url):
    # Short timeouts so a stop()'s closing handshake doesn't wait out
    # websockets' real-world (10s) defaults on every test.
    return NetworkClient(url, close_timeout=0.5, open_timeout=5, reconnect_delay=0.1)


def _drain_one(q, timeout=POLL_TIMEOUT):
    return q.get(timeout=timeout)


def _run(coro):
    """Runs `coro` to completion on a fresh event loop - the whole test body
    is async so it can run a real `websockets.serve` loopback server
    concurrently with the NetworkClient under test, without depending on
    pytest-asyncio (not installed in this project)."""
    return asyncio.run(coro)


def test_connecting_pushes_a_connected_message():
    async def scenario():
        async def handler(connection):
            await connection.wait_closed()

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = make_client(f"ws://127.0.0.1:{port}")
            client.start()
            try:
                message = await asyncio.to_thread(_drain_one, client.incoming)
                assert message == {"type": "connected", "payload": None}
            finally:
                client.stop()

    _run(scenario())


def test_server_message_is_json_decoded_and_queued():
    async def scenario():
        async def handler(connection):
            await connection.send(json.dumps({"type": "snapshot", "payload": {"width": 3}}))
            await connection.wait_closed()

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = make_client(f"ws://127.0.0.1:{port}")
            client.start()
            try:
                first = await asyncio.to_thread(_drain_one, client.incoming)
                assert first == {"type": "connected", "payload": None}
                second = await asyncio.to_thread(_drain_one, client.incoming)
                assert second == {"type": "snapshot", "payload": {"width": 3}}
            finally:
                client.stop()

    _run(scenario())


def test_send_reaches_the_server():
    async def scenario():
        received = []
        connected = asyncio.Event()

        async def handler(connection):
            connected.set()
            async for raw in connection:
                received.append(json.loads(raw))

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = make_client(f"ws://127.0.0.1:{port}")
            client.start()
            try:
                await asyncio.to_thread(_drain_one, client.incoming)  # "connected"
                await asyncio.wait_for(connected.wait(), timeout=POLL_TIMEOUT)
                client.send({"type": "click", "cell": [1, 2]})

                deadline = time.time() + POLL_TIMEOUT
                while not received and time.time() < deadline:
                    await asyncio.sleep(0.02)
                assert received == [{"type": "click", "cell": [1, 2]}]
            finally:
                client.stop()

    _run(scenario())


def test_send_with_a_string_reaches_the_server_raw_not_json_encoded():
    # server/protocol.py's wire format is plain text ("MOVE e2 e4"), not
    # JSON - a str given to send() must arrive exactly as typed, not
    # wrapped in quotes by an extra json.dumps().
    async def scenario():
        received = []
        connected = asyncio.Event()

        async def handler(connection):
            connected.set()
            async for raw in connection:
                received.append(raw)

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = make_client(f"ws://127.0.0.1:{port}")
            client.start()
            try:
                await asyncio.to_thread(_drain_one, client.incoming)  # "connected"
                await asyncio.wait_for(connected.wait(), timeout=POLL_TIMEOUT)
                client.send("MOVE e2 e4")

                deadline = time.time() + POLL_TIMEOUT
                while not received and time.time() < deadline:
                    await asyncio.sleep(0.02)
                assert received == ["MOVE e2 e4"]
            finally:
                client.stop()

    _run(scenario())


def test_server_closing_the_connection_pushes_a_disconnected_message():
    async def scenario():
        async def handler(connection):
            pass  # returning immediately closes the connection server-side

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = make_client(f"ws://127.0.0.1:{port}")
            client.start()
            try:
                first = await asyncio.to_thread(_drain_one, client.incoming)
                assert first == {"type": "connected", "payload": None}
                second = await asyncio.to_thread(_drain_one, client.incoming)
                assert second == {"type": "disconnected", "payload": None}
            finally:
                client.stop()

    _run(scenario())


def test_connection_refused_pushes_a_connection_error_message():
    # Port 1 is privileged/unlikely to have anything listening - connecting
    # there fails fast with a real OSError, the same family of failure a
    # dropped server or a wrong port would produce.
    client = NetworkClient("ws://127.0.0.1:1", close_timeout=0.2, open_timeout=2, reconnect_delay=10)
    client.start()
    try:
        message = _drain_one(client.incoming)
        assert message["type"] == "connection_error"
        assert "error" in message["payload"]
    finally:
        client.stop()


def test_send_before_ever_connecting_is_a_silent_no_op():
    client = NetworkClient("ws://unused")
    client.send("MOVE e2 e4")  # never started - no loop, no connection yet


def test_send_async_is_a_no_op_once_the_connection_is_already_gone():
    # A narrow real race: send() schedules _send_async on the network
    # thread's loop while self._connection still looked live, but by the
    # time it actually runs there the connection may already be gone (e.g.
    # a disconnect landed in between) - _send_async re-checks and must not
    # try to use a None connection.
    client = NetworkClient("ws://unused")
    asyncio.run(client._send_async("MOVE e2 e4"))


def test_drain_returns_everything_queued_without_blocking():
    client = NetworkClient("ws://unused")
    client.incoming.put({"type": "a"})
    client.incoming.put({"type": "b"})

    messages = client.drain()

    assert messages == [{"type": "a"}, {"type": "b"}]
    assert client.drain() == []  # queue is now empty; must not block


def test_stop_before_start_does_not_raise():
    client = NetworkClient("ws://unused")
    client.stop()  # no background thread was ever started


def test_stop_called_immediately_after_start_does_not_block():
    # Regression: stop() used to read self._loop/self._task without
    # synchronizing with _run() setting them on the background thread -
    # calling stop() this soon after start() (nothing unusual about that
    # timing) could race ahead of that assignment, silently skip
    # cancelling anything, and fall through to a useless full 5s join()
    # timeout instead of actually stopping quickly.
    client = NetworkClient("ws://127.0.0.1:1", close_timeout=0.5, open_timeout=2, reconnect_delay=0.1)
    client.start()

    start = time.time()
    client.stop()
    elapsed = time.time() - start

    assert elapsed < 2.0


def test_stop_twice_does_not_raise():
    # Regression: a second stop() (e.g. a caller that both explicitly
    # closes a session and then closes it again in a `finally`) used to
    # try scheduling a callback on the background loop after it had
    # already closed itself, raising "RuntimeError: Event loop is closed"
    # instead of being a harmless no-op.
    client = NetworkClient("ws://127.0.0.1:1", close_timeout=0.2, open_timeout=1, reconnect_delay=0.1)
    client.start()

    client.stop()
    client.stop()  # must not raise


class _AlwaysAliveThread:
    """A fake background thread that never reports itself as finished -
    forces stop() into the narrow real race the test below targets,
    instead of depending on timing to land in it by chance."""

    def is_alive(self):
        return True

    def join(self, timeout=None):
        pass


class _FakeTask:
    def cancel(self):
        pass


def test_stop_swallows_a_runtime_error_from_scheduling_onto_an_already_closed_loop():
    # The real race stop()'s own comment describes: the background
    # thread's loop can close itself (see _run's finally) in the narrow
    # window between stop()'s liveness check and its own
    # call_soon_threadsafe call. A genuinely closed loop raises a real
    # RuntimeError from call_soon_threadsafe - not mocked - so this forces
    # that exact condition via a fake "still alive" thread instead of
    # racing a real one.
    client = NetworkClient("ws://unused")
    client._loop = asyncio.new_event_loop()
    client._loop.close()
    client._task = _FakeTask()
    client._thread = _AlwaysAliveThread()
    client._ready.set()

    client.stop()  # must not raise


def test_stop_joins_the_background_thread():
    async def scenario():
        async def handler(connection):
            await connection.wait_closed()

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = make_client(f"ws://127.0.0.1:{port}")
            client.start()
            await asyncio.to_thread(_drain_one, client.incoming)  # "connected"

            await asyncio.to_thread(client.stop)
            assert not client._thread.is_alive()

    _run(scenario())
