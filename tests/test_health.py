"""server/health.py's own tests - build_health_app through a real aiohttp
TestClient (matching tests/test_api_gateway.py's own convention), plus one
real-socket test for start_health_server proving it actually binds a
listening port, not just that the app object is shaped right.
"""
import asyncio

import aiohttp
from aiohttp.test_utils import TestClient, TestServer

from server.health import build_health_app, start_health_server


def run(coro):
    return asyncio.run(coro)


def test_health_returns_ok():
    async def scenario():
        client = TestClient(TestServer(build_health_app()))
        async with client:
            response = await client.get("/health")
            assert response.status == 200
            assert await response.text() == "ok"

    run(scenario())


def test_metrics_defaults_to_empty_when_no_metrics_fn_given():
    async def scenario():
        client = TestClient(TestServer(build_health_app()))
        async with client:
            response = await client.get("/metrics")
            assert response.status == 200
            assert await response.text() == ""

    run(scenario())


def test_metrics_reports_whatever_metrics_fn_returns_fresh_each_time():
    async def scenario():
        counts = {"kf_chess_test_active_rooms": 0}
        client = TestClient(TestServer(build_health_app(lambda: dict(counts))))
        async with client:
            first = await (await client.get("/metrics")).text()
            assert first == "kf_chess_test_active_rooms 0\n"

            counts["kf_chess_test_active_rooms"] = 3
            second = await (await client.get("/metrics")).text()
            assert second == "kf_chess_test_active_rooms 3\n"

    run(scenario())


def test_start_health_server_binds_a_real_listening_port():
    async def scenario():
        runner = await start_health_server("127.0.0.1", 0, lambda: {"kf_chess_test_gauge": 7})
        try:
            port = runner.addresses[0][1]
            async with aiohttp.ClientSession() as session:
                health = await session.get(f"http://127.0.0.1:{port}/health")
                assert health.status == 200
                metrics = await session.get(f"http://127.0.0.1:{port}/metrics")
                assert await metrics.text() == "kf_chess_test_gauge 7\n"
        finally:
            await runner.cleanup()

    run(scenario())
