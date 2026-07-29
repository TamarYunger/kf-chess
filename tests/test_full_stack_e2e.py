"""End-to-end system test against a REAL, already-running docker-compose
stack - not fakes, and not even the real-socket-with-faked-NATS/Redis tier
tests/test_client_server_integration.py's own real-socket tests use.
Needs the full stack already up (`docker compose up -d --scale
game-shard=2` - matching Server_Design.md's own scale-out story), same
"requires real reachable infra" idea as tests/test_db_postgres.py, just
for the whole system instead of one database.

Unlike test_db_postgres.py, this file's tests *skip* (not fail) when the
stack isn't reachable, checked fresh inside each test rather than once at
collection time (so a plain `pytest` run elsewhere in this project pays no
network-timeout cost at all unless one of these tests actually runs).
That's deliberate: CI (.github/workflows/tests.yml) starts a real
PostgreSQL for test_db_postgres.py's sake, but doesn't bring up Docker/
NATS/Redis/the actual service containers at all - there's no equivalent
"start the stack" CI step, and this file is meant for a developer to run
locally against a stack they brought up themselves, exactly the same way
this project's own phased-plan verification has always worked (see
Server_Design.md/the approved plan - "manually run docker compose up and
connect a real client", not something the automated suite does for you).

Drives a genuine REST /login -> WS AUTH -> PLAY -> MOVE round trip for two
players, matched by the real Matchmaker and allocated a room by the real
Allocator to whichever game-shard replica is actually least loaded -
proving the split across every service (API Gateway, WS Gateway,
Matchmaker, Allocator, Game Server Shard) genuinely works together, not
just each piece in isolation (which is all the rest of this project's test
suite checks, against fakes). One test also drives an actual disconnect
through the real DISCONNECT_GRACE_SECONDS wait to a real auto-resign
game_over - no shortcut available here the way tests/test_client_server_
integration.py's own fake-stack version pokes Room._disconnected directly,
since there's no in-process Room to reach into against a real container.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
import urllib.error
import urllib.request

import aiohttp
import pytest
import websockets

from server.room import DISCONNECT_GRACE_SECONDS

API_URL = "http://localhost:8080"
WS_URL = "ws://localhost:8765"


def _stack_is_reachable():
    try:
        urllib.request.urlopen(f"{API_URL}/health", timeout=1)
        return True
    except (OSError, urllib.error.URLError):
        return False


def _skip_unless_stack_reachable():
    if not _stack_is_reachable():
        pytest.skip(
            f"full docker-compose stack not reachable at {API_URL} - run "
            "`docker compose up -d --scale game-shard=2` first (see this module's own docstring)"
        )


def run(coro):
    return asyncio.run(coro)


async def _rest_login(session, username, password="pw"):
    async with session.post(f"{API_URL}/login", json={"username": username, "password": password}) as resp:
        assert resp.status == 200
        body = await resp.json()
        return body["token"]


async def _match_two_players():
    """REST /login for two brand-new usernames (secrets.token_hex per run,
    so repeated runs never collide with an existing account's password),
    AUTH both over a real WebSocket, PLAY both - returns the two open
    connections already matched into the same room, plus each side's own
    "room" message."""
    suffix = secrets.token_hex(4)
    async with aiohttp.ClientSession() as session:
        token_a = await _rest_login(session, f"e2e_{suffix}_a")
        token_b = await _rest_login(session, f"e2e_{suffix}_b")

    a = await websockets.connect(WS_URL)
    b = await websockets.connect(WS_URL)
    await a.send(f"AUTH {token_a}")
    await b.send(f"AUTH {token_b}")
    assert json.loads(await a.recv())["type"] == "login"
    assert json.loads(await b.recv())["type"] == "login"

    await a.send("PLAY")
    await b.send("PLAY")
    room_a = json.loads(await a.recv())
    room_b = json.loads(await b.recv())
    assert room_a["type"] == "room", room_a
    assert room_b["type"] == "room", room_b
    assert room_a["payload"]["room_id"] == room_b["payload"]["room_id"]
    await a.recv()  # initial snapshot
    await b.recv()

    return a, b, room_a, room_b


async def _wait_for_the_landed_move(connection, piece, timeout=10):
    """The snapshot right after MOVE is sent is "still in flight" (an empty
    `moves` list) - the real MOVE_DURATION delay (see config.settings) has
    to actually elapse before a later, tick-driven snapshot reports the
    piece having arrived. Same real-timing wait tests/test_ws_server.py's
    own test_periodic_tick_broadcasts_state_without_a_new_command needs,
    just black-box (no in-process shard to inspect directly)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        message = json.loads(await asyncio.wait_for(connection.recv(), timeout=timeout))
        if message["type"] == "snapshot" and message["payload"]["moves"] \
                and message["payload"]["moves"][0]["piece"] == piece:
            return message
    raise AssertionError(f"{piece} never landed within {timeout}s")


def test_two_real_players_are_matched_across_the_real_stack_and_can_move():
    _skip_unless_stack_reachable()

    async def scenario():
        a, b, room_a, room_b = await _match_two_players()
        try:
            white, black = (a, b) if room_a["payload"]["role"] == "w" else (b, a)
            await white.send("MOVE a2 a3")

            landed_white = await _wait_for_the_landed_move(white, "wP")
            landed_black = await _wait_for_the_landed_move(black, "wP")
            assert landed_white == landed_black
        finally:
            await a.close()
            await b.close()

    run(scenario())


def test_a_real_disconnect_leads_to_a_real_auto_resign_game_over():
    # Slow on purpose (waits out the real DISCONNECT_GRACE_SECONDS) - see
    # this module's own docstring for why no shortcut is available here.
    _skip_unless_stack_reachable()

    async def scenario():
        a, b, room_a, room_b = await _match_two_players()
        survivor, leaving = (a, b) if room_a["payload"]["role"] == "w" else (b, a)
        leaving_color = room_b["payload"]["role"] if leaving is b else room_a["payload"]["role"]
        try:
            await leaving.close()

            disconnected = json.loads(await asyncio.wait_for(survivor.recv(), timeout=10))
            assert disconnected == {
                "type": "opponent_disconnected",
                "payload": {"color": leaving_color, "grace_period_seconds": DISCONNECT_GRACE_SECONDS},
            }

            game_over = None
            deadline = time.time() + DISCONNECT_GRACE_SECONDS + 15
            while time.time() < deadline:
                message = json.loads(await asyncio.wait_for(survivor.recv(), timeout=15))
                if message["type"] == "game_over":
                    game_over = message
                    break
            assert game_over is not None
            assert game_over["payload"]["winner"] != leaving_color
        finally:
            await survivor.close()

    run(scenario())


def test_api_gateway_health_and_metrics_are_reachable():
    _skip_unless_stack_reachable()

    async def scenario():
        async with aiohttp.ClientSession() as session:
            health = await session.get(f"{API_URL}/health")
            assert health.status == 200
            assert await health.text() == "ok"

            await _rest_login(session, f"e2e_{secrets.token_hex(4)}_metrics")
            metrics = await (await session.get(f"{API_URL}/metrics")).text()
            assert "kf_chess_api_gateway_logins_total " in metrics

    run(scenario())
