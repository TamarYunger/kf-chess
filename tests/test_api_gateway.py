"""server/api_gateway.py's own tests - exercised through a real aiohttp
TestClient (an actual local HTTP round trip), matching this project's own
convention of a genuine client/server round trip over mocking the framework
away (see tests/test_ws_server.py's own real websockets.serve/connect
tests).
"""
import asyncio
import json

import fakeredis
from aiohttp.test_utils import TestClient, TestServer

from server.api_gateway import build_app
from server.db import AccountStore, GameStore


def run(coro):
    return asyncio.run(coro)


def make_client_and_deps():
    accounts = AccountStore()
    games = GameStore()
    redis_client = fakeredis.FakeRedis()
    app = build_app(accounts=accounts, games=games, redis_client=redis_client)
    return TestClient(TestServer(app)), accounts, games, redis_client


def test_first_login_creates_the_account_and_returns_a_token():
    async def scenario():
        client, _, _, redis_client = make_client_and_deps()
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
        client, accounts, _, _ = make_client_and_deps()
        accounts.authenticate("alice", "correct-password")
        async with client:
            response = await client.post("/login", json={"username": "alice", "password": "wrong-password"})
            assert response.status == 401
            body = await response.json()
            assert body["message"] == "Invalid password"

    run(scenario())


def test_correct_password_returns_the_stored_rating():
    async def scenario():
        client, accounts, _, _ = make_client_and_deps()
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
        client, _, _, _ = make_client_and_deps()
        async with client:
            response = await client.post("/login", json={"username": "alice"})  # missing password
            assert response.status == 400

    run(scenario())


def test_two_logins_issue_different_tokens():
    async def scenario():
        client, _, _, _ = make_client_and_deps()
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


def test_rooms_is_empty_when_no_room_is_currently_active():
    async def scenario():
        client, _, _, _ = make_client_and_deps()
        async with client:
            response = await client.get("/rooms")
            assert response.status == 200
            assert await response.json() == {"rooms": []}

    run(scenario())


def test_rooms_lists_every_active_room_published_to_redis():
    # server/shard.py's GameShard republishes each Room.room_info() to
    # active_room:{room_id} on every tick - this is that same key GET
    # /rooms reads back, without a live Shard involved.
    async def scenario():
        client, _, _, redis_client = make_client_and_deps()
        redis_client.set("active_room:room1", json.dumps({
            "room_id": "room1", "players": {"w": "alice", "b": "bob"}, "started": True,
        }))
        async with client:
            response = await client.get("/rooms")
            assert response.status == 200
            body = await response.json()
            assert body == {
                "rooms": [{"room_id": "room1", "players": {"w": "alice", "b": "bob"}, "started": True}],
            }

    run(scenario())


def test_history_requires_a_username_query_parameter():
    async def scenario():
        client, _, _, _ = make_client_and_deps()
        async with client:
            response = await client.get("/history")
            assert response.status == 400

    run(scenario())


def test_history_is_empty_for_a_user_with_no_games():
    async def scenario():
        client, _, _, _ = make_client_and_deps()
        async with client:
            response = await client.get("/history", params={"username": "carol"})
            assert response.status == 200
            assert await response.json() == {"history": []}

    run(scenario())


def test_history_lists_games_the_user_actually_played():
    # server/room.py's Room writes a GameStore record on game_over - this
    # is that same store, without a live Room involved.
    async def scenario():
        client, _, games, _ = make_client_and_deps()
        games.record_game("room1", "alice", "bob", "alice", started_at=1000.0, ended_at=1060.0, moves="{}")
        async with client:
            response = await client.get("/history", params={"username": "alice"})
            assert response.status == 200
            body = await response.json()
            assert len(body["history"]) == 1
            assert body["history"][0]["opponent"] == "bob"
            assert body["history"][0]["result"] == "win"

    run(scenario())


def test_health_returns_ok():
    async def scenario():
        client, _, _, _ = make_client_and_deps()
        async with client:
            response = await client.get("/health")
            assert response.status == 200
            assert await response.text() == "ok"

    run(scenario())


def test_metrics_counts_logins_handled_by_this_instance():
    async def scenario():
        client, _, _, _ = make_client_and_deps()
        async with client:
            before = await (await client.get("/metrics")).text()
            assert before == "kf_chess_api_gateway_logins_total 0\n"

            await client.post("/login", json={"username": "alice", "password": "pw"})
            await client.post("/login", json={"username": "bob", "password": "pw"})

            after = await (await client.get("/metrics")).text()
            assert after == "kf_chess_api_gateway_logins_total 2\n"

    run(scenario())


def test_metrics_does_not_count_a_failed_login():
    async def scenario():
        client, accounts, _, _ = make_client_and_deps()
        accounts.authenticate("alice", "correct-password")
        async with client:
            await client.post("/login", json={"username": "alice", "password": "wrong-password"})

            after = await (await client.get("/metrics")).text()
            assert after == "kf_chess_api_gateway_logins_total 0\n"

    run(scenario())
