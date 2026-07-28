"""server/api_gateway.py's own tests - POST /login is the only endpoint
with real logic (/rooms, /history are still stubs - see that module's own
docstring); exercised through a real aiohttp TestClient (an actual local
HTTP round trip), matching this project's own convention of a genuine
client/server round trip over mocking the framework away (see
tests/test_ws_server.py's own real websockets.serve/connect tests).
"""
import asyncio
import json

import fakeredis
from aiohttp.test_utils import TestClient, TestServer

from server.api_gateway import build_app
from server.db import AccountStore


def run(coro):
    return asyncio.run(coro)


def make_client_and_deps():
    accounts = AccountStore()
    redis_client = fakeredis.FakeRedis()
    app = build_app(accounts=accounts, redis_client=redis_client)
    return TestClient(TestServer(app)), accounts, redis_client


def test_first_login_creates_the_account_and_returns_a_token():
    async def scenario():
        client, _, redis_client = make_client_and_deps()
        async with client:
            response = await client.post("/login", json={"username": "alice", "password": "secret123"})
            assert response.status == 200
            body = await response.json()
            assert body["username"] == "alice"
            assert body["rating"] == 1200
            assert "token" in body

            stored = redis_client.get(f"token:{body['token']}")
            assert json.loads(stored) == {"username": "alice", "rating": 1200}

    run(scenario())


def test_wrong_password_is_rejected_with_401():
    async def scenario():
        client, accounts, _ = make_client_and_deps()
        accounts.authenticate("alice", "correct-password")
        async with client:
            response = await client.post("/login", json={"username": "alice", "password": "wrong-password"})
            assert response.status == 401
            body = await response.json()
            assert body["message"] == "Invalid password"

    run(scenario())


def test_correct_password_returns_the_stored_rating():
    async def scenario():
        client, accounts, _ = make_client_and_deps()
        accounts.authenticate("alice", "correct-password")
        accounts.update_rating("alice", 1350)
        async with client:
            response = await client.post("/login", json={"username": "alice", "password": "correct-password"})
            assert response.status == 200
            body = await response.json()
            assert body["rating"] == 1350

    run(scenario())


def test_malformed_request_body_is_rejected_with_400():
    async def scenario():
        client, _, _ = make_client_and_deps()
        async with client:
            response = await client.post("/login", json={"username": "alice"})  # missing password
            assert response.status == 400

    run(scenario())


def test_two_logins_issue_different_tokens():
    async def scenario():
        client, _, _ = make_client_and_deps()
        async with client:
            first = await (await client.post("/login", json={"username": "alice", "password": "pw1"})).json()
            second = await (await client.post("/login", json={"username": "alice", "password": "pw1"})).json()
            assert first["token"] != second["token"]

    run(scenario())


def test_build_app_works_standalone_with_no_injected_dependencies():
    # Mirrors server.ws_server.GameServer's own "constructible standalone"
    # guarantee - build_app() with nothing injected still falls back to an
    # in-memory AccountStore and an in-memory fakeredis (see
    # _default_redis_client), not a real database/Redis connection.
    async def scenario():
        client = TestClient(TestServer(build_app()))
        async with client:
            response = await client.post("/login", json={"username": "alice", "password": "secret123"})
            assert response.status == 200
            body = await response.json()
            assert body["username"] == "alice"
            assert body["rating"] == 1200

    run(scenario())


def test_rooms_stub_returns_an_empty_list():
    async def scenario():
        client, _, _ = make_client_and_deps()
        async with client:
            response = await client.get("/rooms")
            assert response.status == 200
            assert await response.json() == {"rooms": []}

    run(scenario())


def test_history_stub_returns_an_empty_list():
    async def scenario():
        client, _, _ = make_client_and_deps()
        async with client:
            response = await client.get("/history")
            assert response.status == 200
            assert await response.json() == {"history": []}

    run(scenario())
