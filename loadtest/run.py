"""A standalone load-test client for the KungFu Chess server: simulates N
concurrent players logging in (REST), matching via PLAY, and exchanging
SELECT commands for a fixed duration, then reports login/matchmaking/
command round-trip latency and error counts.

Not part of the pytest suite - this drives a real deployment over the
network, the same relationship main.py/main_gui.py/main_online.py have to
the test suite (see CLAUDE.md). Run directly against a running
docker-compose stack (or any reachable deployment):

    python -m loadtest.run --players 100 --duration 30

Exists to put real numbers behind Server_Design.md's own Assumptions
table (average game length, matchmaking/move latency under load) instead
of leaving them purely theoretical - see that document's own note on each
assumption's "how we'd find out" column.

run_player is the one function that actually drives a session; `login`/
`connect` are injected into it (an async (username, password) -> dict
callable, and an async () -> websocket-like object callable) so its
message-handling logic is unit-testable against fakes without a real
server reachable - the same dependency-injection shape every other
network-facing class in this codebase already uses (NetworkClient,
GameServer, ...). main() is the one place that wires the real aiohttp/
websockets calls in.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

DEFAULT_API_URL = "http://localhost:8080"
DEFAULT_WS_URL = "ws://localhost:8765"
DEFAULT_PLAYERS = 50
DEFAULT_DURATION_SECONDS = 30.0
DEFAULT_RAMP_UP_SECONDS = 5.0

# How often a matched player issues a SELECT command per snapshot it
# receives - just enough to generate realistic, click-paced client->server
# traffic without flooding faster than a real UI ever would.
DEFAULT_COMMAND_PROBABILITY = 0.1
DEFAULT_COMMAND_TIMEOUT_SECONDS = 2.0
BOARD_SIZE = 8


@dataclass
class Metrics:
    """Everything one load-test run collects, across every simulated
    player - a plain dataclass so run_player only ever appends to it.
    asyncio's single-threaded cooperative scheduling means concurrent
    tasks never actually interleave mid-append, so no lock is needed."""

    login_latencies: list[float] = field(default_factory=list)
    match_latencies: list[float] = field(default_factory=list)
    command_latencies: list[float] = field(default_factory=list)
    login_errors: int = 0
    connect_errors: int = 0
    command_timeouts: int = 0
    games_matched: int = 0


def random_cell() -> str:
    """A random algebraic square (e.g. "d4") - deliberately not aimed at
    any particular piece; a SELECT on an empty/enemy cell is still a real,
    measurable round trip, and this script's job is generating realistic
    *traffic* under load, not playing a correct game."""
    col = chr(ord("a") + random.randrange(BOARD_SIZE))
    row = random.randint(1, BOARD_SIZE)
    return f"{col}{row}"


async def run_player(
    player_id: int,
    login: Callable[[str, str], Awaitable[dict]],
    connect: Callable[[], Awaitable[object]],
    duration: float,
    metrics: Metrics,
    command_probability: float = DEFAULT_COMMAND_PROBABILITY,
    command_timeout: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
) -> None:
    """One simulated player's full session: REST login, WebSocket AUTH,
    PLAY (matchmaking), then a stream of random SELECT commands once
    matched, for `duration` seconds - reusing the exact verbs/flow
    main_online.py's NetworkGameSession drives for a real client."""
    username = f"loadtest-{player_id}-{random.randrange(10 ** 6)}"
    login_start = time.monotonic()
    try:
        identity = await login(username, "loadtest-password")
    except Exception:
        metrics.login_errors += 1
        return
    metrics.login_latencies.append(time.monotonic() - login_start)

    try:
        ws = await connect()
    except Exception:
        metrics.connect_errors += 1
        return

    try:
        await ws.send(f"AUTH {identity['token']}")
        await ws.recv()  # login confirmation

        play_start = time.monotonic()
        await ws.send("PLAY")
        deadline = time.monotonic() + duration
        matched = False

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            message = json.loads(raw)

            if message["type"] == "room" and not matched:
                matched = True
                metrics.games_matched += 1
                metrics.match_latencies.append(time.monotonic() - play_start)
            elif message["type"] == "no_match":
                break
            elif message["type"] == "snapshot" and matched and random.random() < command_probability:
                command_start = time.monotonic()
                await ws.send(f"SELECT {random_cell()}")
                try:
                    await asyncio.wait_for(ws.recv(), timeout=command_timeout)
                    metrics.command_latencies.append(time.monotonic() - command_start)
                except asyncio.TimeoutError:
                    metrics.command_timeouts += 1
    finally:
        await ws.close()


def _percentile(sorted_values: list[float], fraction: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * fraction))]


def summarize(name: str, values: list[float]) -> str:
    """Formats one metric's mean/p50/p95/max in milliseconds, or a "no
    samples" line - pulled out of report() so it's testable on its own,
    without driving a whole load-test run."""
    if not values:
        return f"{name}: no samples"
    ordered = sorted(values)
    return (
        f"{name}: n={len(ordered)} mean={statistics.mean(ordered) * 1000:.1f}ms "
        f"p50={_percentile(ordered, 0.5) * 1000:.1f}ms p95={_percentile(ordered, 0.95) * 1000:.1f}ms "
        f"max={ordered[-1] * 1000:.1f}ms"
    )


def report(metrics: Metrics, players: int, duration: float) -> str:
    return "\n".join([
        f"=== Load test: {players} players, {duration:.0f}s each ===",
        f"games matched: {metrics.games_matched}  "
        f"login errors: {metrics.login_errors}  connect errors: {metrics.connect_errors}  "
        f"command timeouts: {metrics.command_timeouts}",
        summarize("login latency", metrics.login_latencies),
        summarize("matchmaking latency", metrics.match_latencies),
        summarize("command round-trip latency", metrics.command_latencies),
    ])


async def main() -> None:  # pragma: no cover - real network I/O; run_player's own docstring is the DI seam tests use instead
    import aiohttp
    import websockets

    parser = argparse.ArgumentParser(description="Load-test the KungFu Chess server (see Server_Design.md)")
    parser.add_argument("--players", type=int, default=DEFAULT_PLAYERS)
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION_SECONDS,
                         help="seconds each simulated player stays connected")
    parser.add_argument("--ramp-up", type=float, default=DEFAULT_RAMP_UP_SECONDS,
                         help="seconds to spread player connections over, instead of all at once")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--ws-url", default=DEFAULT_WS_URL)
    args = parser.parse_args()

    metrics = Metrics()
    async with aiohttp.ClientSession() as session:
        async def login(username: str, password: str) -> dict:
            async with session.post(
                f"{args.api_url}/login", json={"username": username, "password": password},
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"login failed: HTTP {resp.status}")
                return await resp.json()

        async def connect() -> object:
            return await websockets.connect(args.ws_url, open_timeout=10)

        tasks = []
        for player_id in range(args.players):
            tasks.append(asyncio.create_task(run_player(player_id, login, connect, args.duration, metrics)))
            if args.ramp_up:
                await asyncio.sleep(args.ramp_up / args.players)
        await asyncio.gather(*tasks)

    print(report(metrics, args.players, args.duration))


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
