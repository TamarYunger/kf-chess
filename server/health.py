"""The minimal HTTP surface every service in this system exposes for
docker-compose healthchecks and basic scraping - GET /health (a bare
liveness probe: "this process is up and its event loop is responsive") and
GET /metrics (a handful of Prometheus-style gauges, whatever `metrics_fn`
reports). This is plumbing every service needs identically, not a
per-service policy decision like server/db.py's build_redis_client vs
DB_BACKEND choice - so unlike this project's usual "duplicate small
constants across service boundaries" convention, this one genuinely lives
here once and is imported everywhere.

Deliberately minimal: no `# HELP`/`# TYPE` annotations (optional in the
Prometheus text exposition format, only needed for full spec compliance,
not for basic ingestion) and no alerting/tracing - see Server_Design.md's
own Phase 6 scope note for why.
"""
from __future__ import annotations

from typing import Callable

from aiohttp import web


def build_health_app(metrics_fn: Callable[[], dict] | None = None) -> web.Application:
    """`metrics_fn`, if given, is called fresh on every GET /metrics and
    must return a dict[str, int | float] - e.g. {"kf_chess_shard_active_rooms":
    3}. Defaults to reporting no metrics at all (bare /health only) for
    services like the Allocator that have nothing meaningful to gauge."""
    metrics_fn = metrics_fn or (lambda: {})

    async def handle_health(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def handle_metrics(request: web.Request) -> web.Response:
        lines = [f"{name} {value}" for name, value in metrics_fn().items()]
        return web.Response(text="".join(line + "\n" for line in lines))

    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_get("/metrics", handle_metrics)
    return app


async def start_health_server(host: str, port: int, metrics_fn: Callable[[], dict] | None = None) -> web.AppRunner:
    """Actually binds `build_health_app`'s routes to a real socket - the
    counterpart to server/api_gateway.py's own build_app()/web.run_app()
    split, just using AppRunner+TCPSite directly since these services
    aren't otherwise running aiohttp's own event loop entry point. Returns
    the AppRunner; none of the current callers ever tear it down (they all
    run until the process is killed), but it's returned in case a test
    wants to."""
    app = build_health_app(metrics_fn)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    return runner
