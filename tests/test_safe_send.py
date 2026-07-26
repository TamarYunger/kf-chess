import asyncio

import websockets.exceptions

from server.safe_send import safe_send


class FakeConnection:
    def __init__(self, raise_closed=False):
        self.sent = []
        self._raise_closed = raise_closed

    async def send(self, message):
        if self._raise_closed:
            raise websockets.exceptions.ConnectionClosed(None, None)
        self.sent.append(message)


def test_safe_send_delivers_to_a_live_connection():
    connection = FakeConnection()

    asyncio.run(safe_send(connection, "hello"))

    assert connection.sent == ["hello"]


def test_safe_send_swallows_a_closed_connection():
    connection = FakeConnection(raise_closed=True)

    asyncio.run(safe_send(connection, "hello"))  # must not raise
