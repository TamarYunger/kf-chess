"""The WS Gateway: a WebSocket server that authenticates connections
(AUTH, checked against a token server.api_gateway.py issued after its own
REST /login - this class never sees a password) and forwards PLAY/ROOM
CREATE/ROOM JOIN/MOVE/JUMP/SELECT to server/shard.py's Game Shard replicas
over NATS - it owns no server.room.Room/GameEngine itself at all anymore
(see that module's own docstring for why: a Room and the real socket now
live in two different processes, and Room can't reach a connection it
doesn't have).

The one piece of game-adjacent state this class still keeps is
`_connection_room` (connection -> room_id) - purely local bookkeeping so
a later MOVE/JUMP/SELECT from an already-seated connection knows which
room_id to attach to its own outgoing envelope. It learns a room_id the
same way it learns everything else the shard did - by relaying a "room"
message back to the client (see _handle_outbox_message) - it never asks
the shard directly.

Unlike the single-Shard days, there's no one shared shard inbox subject to
publish room-scoped commands to anymore - see server/shard.py's own
docstring for why (more than one Shard replica subscribing to the same
subject would each independently act on the same message). Instead, every
ROOM_JOIN/MOVE/JUMP/SELECT/disconnect looks up `room_owner:{room_id}` in
Redis (server/allocator_service.py writes it when a room is first
allocated; server/shard.py's own tick() renews it for as long as that
instance still hosts the room) to find which Shard instance's own inbox
subject to publish to - see _publish_to_shard. A missing/expired entry
means "no such room right now" either way (never allocated, or its
lease lapsed because the owning Shard crashed), so it's reported to the
client the same way in both cases. ROOM CREATE has no room_id yet at all
(that's exactly what needs deciding) - it forwards to server/
allocator_service.py's Allocator instead, the same way PLAY forwards to
the Matchmaker.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import socket
from types import ModuleType
from typing import Callable

import websockets

from config import settings
from server.db import build_redis_client
from server.health import start_health_server
from server.logging_config import configure_server_logging
from server.protocol import ProtocolError, encode_error, encode_login, encode_login_rejected, parse_command
from server.safe_send import Connection, safe_send

logger = logging.getLogger(__name__)

# Same constant as server/shard.py's own INBOX_SUBJECT_TEMPLATE - keyed by
# instance_id, not a plain subject string, since there's no single shared
# shard inbox anymore (see this module's own docstring). Duplicated rather
# than imported, so this module never pulls in the GameEngine/Room import
# chain it no longer has any business needing.
SHARD_INBOX_SUBJECT_TEMPLATE = "shard.inbox.{instance_id}"

# The subject server/matchmaker_service.py's MatchmakerService subscribes
# to for every PLAY request - same "duplicated constant, not imported"
# reasoning as SHARD_INBOX_SUBJECT_TEMPLATE above.
MATCHMAKER_INBOX_SUBJECT = "matchmaker.inbox"

# The subject server/allocator_service.py's AllocatorService subscribes to
# for every need_room request (ROOM CREATE, or a Matchmaker-found match) -
# same reasoning again.
ALLOCATOR_INBOX_SUBJECT = "allocator.inbox"

# Overridable via env because inside a container "localhost" means the
# container's own loopback, which Docker's port-mapping can't reach - the
# process there needs to bind 0.0.0.0 instead. Bare-metal/local runs are
# unaffected (env var unset -> same "localhost" default as before).
DEFAULT_HOST = os.environ.get("KF_CHESS_HOST", "localhost")
DEFAULT_PORT = 8765

# Internal only (see docker-compose.yml's healthcheck: for this service -
# it curls this from inside the same container, never mapped to the host)
# - see server/health.py's own docstring for what's served here.
HEALTH_PORT = 9100


def _default_redis_client() -> object:
    """GameServer's redis_client=None default - an in-memory fake, not a
    real connection, for exactly the reason AccountStore()'s own default
    used to be in-memory SQLite: a GameServer must stay constructible
    standalone (tests, `python -m server.ws_server` outside docker-compose)
    without requiring a real Redis to be reachable. main() explicitly
    builds and passes a real one (server.db.build_redis_client) for actual
    deployment - this default is never used there."""
    import fakeredis

    return fakeredis.FakeRedis()


def _default_nats_client() -> object:
    """Same reasoning as _default_redis_client, for NATS: a GameServer
    must stay constructible/testable standalone, without a real NATS
    server reachable. This fake only supports publish() (GameServer never
    subscribes to anything but its own outbox subject, which it does
    explicitly via start() - a bare default that silently drops every
    publish() is enough for a GameServer nothing ever talks back to)."""

    class _NullNatsClient:
        async def publish(self, subject: str, payload: bytes) -> None:
            pass

        async def subscribe(self, subject: str, cb: object) -> None:
            pass

    return _NullNatsClient()


class GameServer:
    """The WS Gateway. Holds every live connection on this instance and
    forwards commands to whichever Game Shard owns the relevant room -
    over NATS, never directly - see this module's own docstring.

    Collaborators:
      - `redis_client`: where AUTH's token is looked up (server.api_gateway.py
        wrote it there) and where this connection's own
        `connection_id -> instance_id` registry entry is written once
        authenticated (server.nats_connection.NatsConnectionProxy reads
        that same registry from the Shard side, to know which Gateway
        instance's outbox to publish a reply/broadcast to). Defaults to
        an in-memory fake (see _default_redis_client) so a GameServer is
        usable standalone (tests) without a real Redis.
      - `nats_client`: how a command actually reaches the Shard, and how
        a reply/broadcast actually reaches this connection - see
        start()/_handle_outbox_message. Defaults similarly to an
        in-memory fake (see _default_nats_client).
      - `instance_id`: identifies *this* Gateway process/container in the
        registry above - defaults to socket.gethostname() (the container
        ID, inside Docker). One instance can hold many connections; NATS
        traffic addressed to this instance arrives on one shared outbox
        subject (`outbox.<instance_id>`), not one subject per connection -
        see Server_Design.md for why that distinction matters at scale.
      - PLAY only forwards to server/matchmaker_service.py's Matchmaker
        (a "play" envelope, on MATCHMAKER_INBOX_SUBJECT) - AUTH only
        authenticates, it does NOT put anyone in a room, and this class no
        longer runs server.matchmaking.find_opponent or holds a waiting
        queue itself (see that module's own docstring for why: a queue
        here would be per-Gateway-*instance*, so two players PLAY-ing on
        two different instances would never be compared against each
        other). ROOM CREATE forwards to server/allocator_service.py's
        Allocator the same way, since there's no room_id yet to route by.
        ROOM_JOIN/MOVE/JUMP/SELECT instead resolve `room_owner:{room_id}`
        from Redis to find which Shard instance to publish a "command"
        envelope to - see this module's own docstring.
    """

    def __init__(
        self,
        config: ModuleType = settings,
        redis_client: object = None,
        nats_client: object = None,
        instance_id: str | None = None,
    ) -> None:
        self._config = config
        self._redis = redis_client if redis_client is not None else _default_redis_client()
        self._nats = nats_client if nats_client is not None else _default_nats_client()
        self._instance_id = instance_id or socket.gethostname()
        self._clients: set[Connection] = set()
        self._players: dict[Connection, dict] = {}  # connection -> {"username", "rating"} (authenticated, connected)
        self._connection_room: dict[Connection, str] = {}  # connection -> room_id (from a relayed "room" message)
        self._connection_ids: dict[Connection, str] = {}  # connection -> connection_id
        self._connections_by_id: dict[str, Connection] = {}  # connection_id -> connection

    async def start(self) -> None:
        """Subscribes to this instance's own outbox - must be awaited once
        before any connection can complete a round trip through the Shard
        (see serve_forever). Separate from __init__ because subscribing is
        an async operation."""
        await self._nats.subscribe(f"outbox.{self._instance_id}", cb=self._handle_outbox_message)

    async def handle_connection(self, connection: Connection) -> None:
        """The per-connection coroutine websockets.serve runs for as long
        as that connection is open. Nothing is sent immediately on
        connect - there's no default game to show until AUTH, then PLAY/
        ROOM CREATE/ROOM JOIN, actually put this connection in a room."""
        self._clients.add(connection)
        try:
            async for raw in connection:
                await self._handle_message(connection, raw)
        finally:
            self._clients.discard(connection)
            self._players.pop(connection, None)
            room_id = self._connection_room.pop(connection, None)
            connection_id = self._connection_ids.pop(connection, None)
            if connection_id is not None:
                self._connections_by_id.pop(connection_id, None)
                self._redis.delete(f"connection:{connection_id}")
                # Unconditional, not just when room_id is set: a connection
                # that dropped while still waiting in the Matchmaker's queue
                # (PLAY sent, no room yet) has no room_id here at all, but
                # would otherwise be left in server/matchmaker_service.py's
                # queue forever - reachable by some later PLAY, matching it
                # against an opponent who can never actually join. A no-op
                # if this connection was never queued (or already matched).
                await self._nats.publish(MATCHMAKER_INBOX_SUBJECT, json.dumps({
                    "kind": "leave", "connection_id": connection_id,
                }).encode("utf-8"))
                if room_id is not None:
                    # The Shard's Room needs to know too, to start this
                    # seat's disconnect grace period (server/room.py's
                    # handle_disconnect) - it can't detect a dropped socket
                    # itself, since it never held one. A no-op if room_id's
                    # lease is already gone (see _publish_to_shard) - the
                    # room isn't reachable either way, and this connection
                    # is closing regardless.
                    await self._publish_to_shard(room_id, {
                        "kind": "disconnect", "connection_id": connection_id, "room_id": room_id,
                    })

    async def _handle_message(self, connection: Connection, raw: str) -> None:
        try:
            command = parse_command(raw)
        except ProtocolError as error:
            await self._safe_send(connection, json.dumps(encode_error(str(error))))
            return

        if command.verb == "AUTH":
            await self._handle_auth(connection, command.args[0])
            return
        if command.verb == "PLAY":
            await self._handle_play(connection)
            return
        if command.verb == "ROOM_CREATE":
            await self._handle_room_create(connection)
            return
        if command.verb == "ROOM_JOIN":
            await self._forward_command(connection, raw, room_id=command.args[0], verb_for_error="ROOM JOIN")
            return

        # MOVE / JUMP / SELECT - the only verbs left; route to this
        # connection's current room, if it has one.
        room_id = self._connection_room.get(connection)
        if room_id is None:
            await self._safe_send(connection, json.dumps(encode_error("Not in a room")))
            return
        await self._forward_command(connection, raw, room_id=room_id, verb_for_error=command.verb)

    # -- AUTH: authentication only, no room ---------------------------------

    async def _handle_auth(self, connection: Connection, token: str) -> None:
        if connection in self._players:
            # Re-AUTH from an already-authenticated connection just
            # confirms the same identity again.
            player = self._players[connection]
            await self._safe_send(connection, json.dumps(encode_login(player["username"], player["rating"])))
            return

        key = f"token:{token}"
        raw_identity = self._redis.get(key)
        if raw_identity is None:
            logger.warning("AUTH rejected: invalid or expired token")
            await self._safe_send(connection, json.dumps(encode_login_rejected("Invalid or expired token")))
            return
        # One-time use: a token that's already been redeemed (or replayed
        # by an eavesdropper) doesn't authenticate a second connection.
        self._redis.delete(key)

        identity = json.loads(raw_identity)
        username, rating = identity["username"], identity["rating"]
        self._players[connection] = {"username": username, "rating": rating}

        connection_id = secrets.token_hex(8)
        self._connection_ids[connection] = connection_id
        self._connections_by_id[connection_id] = connection
        self._redis.set(f"connection:{connection_id}", self._instance_id)

        logger.info("%s authenticated (rating=%s)", username, rating)
        await self._safe_send(connection, json.dumps(encode_login(username, rating)))

    # -- PLAY / matchmaking ---------------------------------------------------

    async def _handle_play(self, connection: Connection) -> None:
        """Forwards to server/matchmaker_service.py's Matchmaker - see this
        class's own docstring for why the waiting queue isn't kept here.
        "Already searching" is deliberately not checked here (this class no
        longer tracks a queue to check against) - the Matchmaker guards
        that itself against its own Redis-backed queue."""
        player = self._players.get(connection)
        if player is None:
            await self._safe_send(connection, json.dumps(encode_error("Must AUTH before PLAY")))
            return
        if connection in self._connection_room:
            return  # already in a room - PLAY is a no-op

        await self._nats.publish(MATCHMAKER_INBOX_SUBJECT, json.dumps({
            "kind": "play",
            "connection_id": self._connection_ids[connection],
            "username": player["username"], "rating": player["rating"],
        }).encode("utf-8"))

    # -- ROOM CREATE: allocator hop -------------------------------------------

    async def _handle_room_create(self, connection: Connection) -> None:
        """Forwards to server/allocator_service.py's Allocator, the same
        way _handle_play forwards to the Matchmaker - there's no room_id
        yet for this class to resolve a Shard instance from (that's
        exactly what the Allocator decides), so it can't go through
        _forward_command/_publish_to_shard like an existing room's
        commands do."""
        player = self._players.get(connection)
        if player is None:
            await self._safe_send(connection, json.dumps(encode_error("Must AUTH before ROOM CREATE")))
            return
        await self._nats.publish(ALLOCATOR_INBOX_SUBJECT, json.dumps({
            "players": [{
                "connection_id": self._connection_ids[connection],
                "username": player["username"], "rating": player["rating"],
            }],
        }).encode("utf-8"))

    # -- Forwarding to the Shard ---------------------------------------------

    async def _forward_command(self, connection: Connection, raw: str, room_id: str, verb_for_error: str) -> None:
        player = self._players.get(connection)
        if player is None:
            await self._safe_send(connection, json.dumps(encode_error(f"Must AUTH before {verb_for_error}")))
            return
        instance_id = await self._publish_to_shard(room_id, {
            "kind": "command",
            "connection_id": self._connection_ids[connection],
            "username": player["username"], "rating": player["rating"],
            "room_id": room_id, "raw": raw,
        })
        if instance_id is None:
            await self._safe_send(connection, json.dumps(encode_error(f"Room {room_id!r} not found")))

    async def _publish_to_shard(self, room_id: str, envelope: dict) -> str | None:
        """Looks up room_id's current owner in the room_owner registry
        (see this module's own docstring for how that entry gets there
        and why a missing one means "no such room right now" either way)
        and publishes to that instance's own inbox subject. Returns the
        instance_id published to, or None if there wasn't one - callers
        decide for themselves whether that's worth telling the client
        about (_forward_command does; the disconnect notification in
        handle_connection doesn't need to, the connection's closing
        regardless)."""
        instance_id = self._redis.get(f"room_owner:{room_id}")
        if instance_id is None:
            return None
        if isinstance(instance_id, bytes):
            instance_id = instance_id.decode("utf-8")
        await self._nats.publish(SHARD_INBOX_SUBJECT_TEMPLATE.format(instance_id=instance_id),
                                  json.dumps(envelope).encode("utf-8"))
        return instance_id

    async def _handle_outbox_message(self, msg: object) -> None:
        """The NATS subscription callback for this instance's own outbox
        (see start()) - one message per reply/broadcast the Shard's Room
        addressed to a connection_id this instance is holding. Relays it
        to the real socket, and - the one bit of local bookkeeping this
        class still needs - remembers the room_id from a "room" message,
        so a later MOVE/JUMP/SELECT from the same connection knows where
        to route to (see _handle_message)."""
        envelope = json.loads(msg.data)
        connection = self._connections_by_id.get(envelope["connection_id"])
        if connection is None:
            return  # this connection already disconnected from this instance
        message = envelope["message"]
        await self._safe_send(connection, message)
        decoded = json.loads(message)
        if decoded.get("type") == "room":
            self._connection_room[connection] = decoded["payload"]["room_id"]

    async def _safe_send(self, connection: Connection, message: str) -> None:
        # A client can disconnect between being read from self._clients and
        # actually being sent to (e.g. mid-broadcast) - that's not this
        # server's problem to raise about; handle_connection's own loop
        # ending is what removes it from self._clients.
        await safe_send(connection, message)

    def metrics(self) -> dict:
        """Fed to server/health.py's GET /metrics by serve_forever - see
        that module's own docstring for the format."""
        return {"kf_chess_ws_active_connections": len(self._clients)}


async def serve_forever(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    on_ready: Callable | None = None,
    config: ModuleType = settings,
    redis_client: object = None,
    nats_client: object = None,
    instance_id: str | None = None,
    health_port: int = HEALTH_PORT,
) -> None:
    """Runs the gateway until cancelled. `on_ready(bound_server, game_server,
    health_runner)` is called once both sockets are actually listening -
    mainly so tests can ask for an OS-assigned port (port=0/health_port=0)
    and learn what they became; not otherwise needed to run the server for
    real. No periodic tick of its own anymore (see GameServer's own
    docstring - matchmaking timeouts are server/matchmaker_service.py's
    job now, and the Shard runs its own tick for in-room real-time motion)
    - this just has to stay alive for as long as `bound_server` does.
    `health_port=0` is how tests avoid colliding on the fixed default
    HEALTH_PORT across separate test runs, same reason `port=0` already
    exists for the main socket."""
    game_server = GameServer(config=config, redis_client=redis_client, nats_client=nats_client,
                              instance_id=instance_id)
    await game_server.start()
    health_runner = await start_health_server(host, health_port, game_server.metrics)
    async with websockets.serve(game_server.handle_connection, host, port) as bound_server:
        if on_ready is not None:
            on_ready(bound_server, game_server, health_runner)
        await asyncio.Future()


def main():  # pragma: no cover
    configure_server_logging()

    # AUTH checks a token against Redis (see GameServer._handle_auth), and
    # the connection_id registry (see GameServer._handle_auth/start) lives
    # there too - both needed unconditionally, unlike server/api_gateway.py's
    # and server/shard.py's own DB_BACKEND choice (this module doesn't
    # touch AccountStore/Postgres at all anymore - see this module's own
    # docstring for why Room, not GameServer, owns that now).
    redis_client = build_redis_client()

    async def _main():
        import nats

        nats_client = await nats.connect(os.environ["NATS_URL"])
        logger.info("starting KungFu Chess WS Gateway on %s:%s", DEFAULT_HOST, DEFAULT_PORT)
        await serve_forever(redis_client=redis_client, nats_client=nats_client)

    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
