"""The REST front door: POST /login checks a username/password against
server.db's AccountStore - the only place left in the whole system that
still sees a password (see server/ws_server.py's own docstring, which no
longer does) - and, on success, issues a short-lived opaque token, stored
in Redis, for the WS Gateway's AUTH verb to redeem afterwards
(server/ws_server.py's GameServer._handle_auth). GET /rooms and
GET /history are stubs for now, not backed by real data yet - see
Server_Design.md's phased plan.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path

from aiohttp import web

from server.db import AccountStore, PostgresAccountStore, build_redis_client
from server.logging_config import configure_server_logging

logger = logging.getLogger(__name__)

DEFAULT_HOST = os.environ.get("KF_CHESS_HOST", "localhost")
DEFAULT_PORT = 8080
DEFAULT_DB_PATH = str(Path(__file__).resolve().parent / "accounts.db")

# Long enough to cover "REST reply arrives -> client sends AUTH over the
# already-open WebSocket", not a whole play session - the token is
# redeemed (and deleted, see _handle_auth) within that window or not at
# all, it's not meant to outlive it.
TOKEN_TTL_SECONDS = 60


def _default_redis_client():
    """Same reasoning as server/ws_server.py's own _default_redis_client:
    an in-memory fake so this service is constructible/testable standalone,
    never required just to build the app. main() wires the real one."""
    import fakeredis

    return fakeredis.FakeRedis()


def build_app(accounts=None, redis_client=None):
    """Composition root for this one service, same shape as
    server/ws_server.py's GameServer: safe/standalone defaults (in-memory
    AccountStore, in-memory fakeredis) so this is testable without any
    real database or Redis; main() is the only place that wires the real
    ones in for actual deployment."""
    accounts = accounts if accounts is not None else AccountStore()
    redis_client = redis_client if redis_client is not None else _default_redis_client()
    # In-process only (see handle_metrics) - a per-instance count of logins
    # this one replica handled, not meant to survive a restart or be
    # aggregated exactly; see server/health.py's own docstring for why
    # that's an acceptable level of precision for a basic gauge.
    login_count = {"value": 0}

    async def handle_login(request):
        try:
            body = await request.json()
            username = body["username"]
            password = body["password"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return web.json_response({"message": "Malformed request"}, status=400)

        ok, rating, error = accounts.authenticate(username, password)
        if not ok:
            logger.warning("login failed for %r", username)
            return web.json_response({"message": error}, status=401)

        token = secrets.token_hex(24)
        identity = json.dumps({"username": username, "rating": rating})
        redis_client.setex(f"token:{token}", TOKEN_TTL_SECONDS, identity)
        login_count["value"] += 1
        logger.info("%s logged in (rating=%s), token issued", username, rating)
        return web.json_response({"token": token, "username": username, "rating": rating})

    async def handle_rooms(request):
        return web.json_response({"rooms": []})

    async def handle_history(request):
        return web.json_response({"history": []})

    async def handle_health(request):
        return web.Response(text="ok")

    async def handle_metrics(request):
        return web.Response(text=f"kf_chess_api_gateway_logins_total {login_count['value']}\n")

    app = web.Application()
    app.router.add_post("/login", handle_login)
    app.router.add_get("/rooms", handle_rooms)
    app.router.add_get("/history", handle_history)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/metrics", handle_metrics)
    return app


def main():  # pragma: no cover
    configure_server_logging()

    # Same DB_BACKEND choice as server/ws_server.py's main() - duplicated
    # deliberately, not shared, for the same reason given there: each
    # service is its own composition root (see that module's docstring).
    if os.environ.get("DB_BACKEND", "sqlite") == "postgres":
        dsn = (
            f"host={os.environ['POSTGRES_HOST']} "
            f"port={os.environ['POSTGRES_PORT']} "
            f"dbname={os.environ['POSTGRES_DB']} "
            f"user={os.environ['POSTGRES_USER']} "
            f"password={os.environ['POSTGRES_PASSWORD']}"
        )
        accounts = PostgresAccountStore(dsn)
    else:
        accounts = AccountStore(DEFAULT_DB_PATH)

    redis_client = build_redis_client()
    app = build_app(accounts=accounts, redis_client=redis_client)
    logger.info("starting KungFu Chess API Gateway on %s:%s", DEFAULT_HOST, DEFAULT_PORT)
    web.run_app(app, host=DEFAULT_HOST, port=DEFAULT_PORT)


if __name__ == "__main__":  # pragma: no cover
    main()
