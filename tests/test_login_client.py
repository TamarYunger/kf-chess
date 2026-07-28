"""client/session/login_client.py's own tests - a real local HTTP server
(aiohttp.test_utils.TestServer, an actual bound socket) and a real
LoginClient hitting it over urllib on a background thread, matching this
project's own convention (tests/test_network_client.py) of a genuine
client/server round trip rather than mocking urllib away.
"""
import asyncio

from aiohttp import web
from aiohttp.test_utils import TestServer

from bus.event_types import LOGIN_REJECTED
from client.session.login_client import AUTH_TOKEN_RECEIVED, LoginClient

POLL_TIMEOUT = 5.0


def _drain_one(q, timeout=POLL_TIMEOUT):
    return q.get(timeout=timeout)


def _run(coro):
    return asyncio.run(coro)


def test_successful_login_pushes_the_token():
    async def scenario():
        async def handle_login(request):
            return web.json_response({"token": "tok-abc", "username": "alice", "rating": 1200})

        app = web.Application()
        app.router.add_post("/login", handle_login)
        async with TestServer(app) as server:
            client = LoginClient(str(server.make_url("")))
            client.login("alice", "secret123")

            message = await asyncio.to_thread(_drain_one, client.incoming)
            assert message == {
                "type": AUTH_TOKEN_RECEIVED,
                "payload": {"token": "tok-abc", "username": "alice", "rating": 1200},
            }

    _run(scenario())


def test_rejected_login_pushes_a_login_rejected_message():
    async def scenario():
        async def handle_login(request):
            return web.json_response({"message": "Invalid password"}, status=401)

        app = web.Application()
        app.router.add_post("/login", handle_login)
        async with TestServer(app) as server:
            client = LoginClient(str(server.make_url("")))
            client.login("alice", "wrong-password")

            message = await asyncio.to_thread(_drain_one, client.incoming)
            assert message == {"type": LOGIN_REJECTED, "payload": {"message": "Invalid password"}}

    _run(scenario())


def test_unreachable_server_pushes_a_login_rejected_message():
    # Port 1 is privileged/unlikely to have anything listening - same
    # "fails fast with a real OSError" reasoning as
    # tests/test_network_client.py's connection_error test.
    client = LoginClient("http://127.0.0.1:1")
    client.login("alice", "secret123")

    message = _drain_one(client.incoming)
    assert message["type"] == LOGIN_REJECTED
    assert "message" in message["payload"]


def test_drain_returns_everything_queued_without_blocking():
    client = LoginClient("http://unused")
    client.incoming.put({"type": "a"})
    client.incoming.put({"type": "b"})

    messages = client.drain()

    assert messages == [{"type": "a"}, {"type": "b"}]
    assert client.drain() == []  # queue is now empty; must not block
