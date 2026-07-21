import asyncio
import json
import logging
import time

from bus.event_bus import EventBus
from config import settings
from server.db import AccountStore
from server.protocol import parse_command
from server.room import DISCONNECT_GRACE_SECONDS, Room
from server.ws_server import build_engine


class FakeConnection:
    """A minimal stand-in - Room only ever needs `.send()` on a connection,
    never the async-iteration handle_connection's own loop uses."""

    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


def run(coro):
    return asyncio.run(coro)


def make_room(rows=None, events=None, accounts=None, room_id="abc123"):
    engine = build_engine(rows or ["wK . .", ". . .", "bK . ."], settings, events=events)
    return Room(room_id, engine, settings.COLORS, accounts if accounts is not None else AccountStore()), engine


def test_first_seat_or_view_gets_the_first_color():
    room, engine = make_room()
    conn = FakeConnection()

    role = room.seat_or_view(conn, "alice", 1200)

    assert role == settings.COLORS[0]
    assert room.role_of(conn) == settings.COLORS[0]


def test_second_seat_or_view_gets_the_second_color():
    room, engine = make_room()
    room.seat_or_view(FakeConnection(), "alice", 1200)
    bob = FakeConnection()

    role = room.seat_or_view(bob, "bob", 1250)

    assert role == settings.COLORS[1]


def test_third_seat_or_view_becomes_a_viewer():
    room, engine = make_room()
    room.seat_or_view(FakeConnection(), "alice", 1200)
    room.seat_or_view(FakeConnection(), "bob", 1250)
    carol = FakeConnection()

    role = room.seat_or_view(carol, "carol", 1180)

    assert role == "viewer"
    assert room.role_of(carol) == "viewer"


def test_role_of_an_unknown_connection_is_none():
    room, engine = make_room()

    assert room.role_of(FakeConnection()) is None


def test_welcome_sends_room_confirmation_then_snapshot():
    async def scenario():
        room, engine = make_room()
        conn = FakeConnection()
        role = room.seat_or_view(conn, "alice", 1200)

        await room.welcome(conn, role)

        assert len(conn.sent) == 2
        room_msg = json.loads(conn.sent[0])
        assert room_msg == {"type": "room", "payload": {"room_id": "abc123", "role": settings.COLORS[0]}}
        snapshot_msg = json.loads(conn.sent[1])
        assert snapshot_msg["type"] == "snapshot"

    run(scenario())


def test_seated_move_is_accepted_and_broadcast_to_everyone_in_the_room():
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", ". . ."])
        mover = FakeConnection()
        other_seat = FakeConnection()
        viewer = FakeConnection()
        room.seat_or_view(mover, "alice", 1200)  # first color
        room.seat_or_view(other_seat, "bob", 1200)  # second color
        room.seat_or_view(viewer, "carol", 1200)  # both colors taken -> viewer

        await room.handle_command(mover, parse_command("MOVE a3 c3"))

        moved = json.loads(viewer.sent[-1])
        assert moved["type"] == "snapshot"
        assert moved["payload"]["moves"][0]["piece"] == "wR"

    run(scenario())


def test_viewer_move_is_rejected_and_logged(caplog):
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", ". . ."])
        room.seat_or_view(FakeConnection(), "alice", 1200)
        room.seat_or_view(FakeConnection(), "bob", 1200)
        viewer = FakeConnection()
        room.seat_or_view(viewer, "carol", 1200)

        with caplog.at_level(logging.WARNING, logger="server.room"):
            await room.handle_command(viewer, parse_command("MOVE a3 c3"))

        error = json.loads(viewer.sent[-1])
        assert error == {"type": "error", "payload": {"message": "Only seated players can make moves"}}
        assert any("rejected" in record.message and "non-seated" in record.message for record in caplog.records)

    run(scenario())


def test_never_joined_connection_move_is_rejected():
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", ". . ."])
        stranger = FakeConnection()

        await room.handle_command(stranger, parse_command("MOVE a3 c3"))

        error = json.loads(stranger.sent[-1])
        assert error["type"] == "error"

    run(scenario())


def test_illegal_move_is_rejected_not_broadcast():
    async def scenario():
        room, engine = make_room(["wN . .", ". . .", ". . ."])
        mover = FakeConnection()
        room.seat_or_view(mover, "alice", 1200)

        await room.handle_command(mover, parse_command("MOVE a3 b3"))  # not a legal knight move

        rejected = json.loads(mover.sent[-1])
        assert rejected["type"] == "rejected"

    run(scenario())


def test_disconnect_of_a_seated_player_starts_a_grace_period_and_notifies_others():
    async def scenario():
        room, engine = make_room()
        alice = FakeConnection()
        bob = FakeConnection()
        role_alice = room.seat_or_view(alice, "alice", 1200)
        room.seat_or_view(bob, "bob", 1200)

        await room.handle_disconnect(alice)

        assert role_alice in room._disconnected
        notice = json.loads(bob.sent[-1])
        assert notice == {
            "type": "opponent_disconnected",
            "payload": {"color": role_alice, "grace_period_seconds": DISCONNECT_GRACE_SECONDS},
        }

    run(scenario())


def test_disconnect_of_a_viewer_does_not_start_a_grace_period():
    async def scenario():
        room, engine = make_room()
        room.seat_or_view(FakeConnection(), "alice", 1200)
        room.seat_or_view(FakeConnection(), "bob", 1200)
        viewer = FakeConnection()
        room.seat_or_view(viewer, "carol", 1200)

        await room.handle_disconnect(viewer)

        assert room._disconnected == {}

    run(scenario())


def test_reconnect_with_the_same_username_reclaims_the_seat():
    async def scenario():
        room, engine = make_room()
        alice = FakeConnection()
        role_alice = room.seat_or_view(alice, "alice", 1200)
        room.seat_or_view(FakeConnection(), "bob", 1200)
        await room.handle_disconnect(alice)

        new_connection = FakeConnection()
        role = room.seat_or_view(new_connection, "alice", 1200)

        assert role == role_alice
        assert role_alice not in room._disconnected
        assert room.role_of(new_connection) == role_alice

    run(scenario())


def test_a_different_username_cannot_steal_a_disconnected_seat():
    async def scenario():
        room, engine = make_room()
        alice = FakeConnection()
        room.seat_or_view(alice, "alice", 1200)
        room.seat_or_view(FakeConnection(), "bob", 1200)
        await room.handle_disconnect(alice)

        carol = FakeConnection()
        role = room.seat_or_view(carol, "carol", 1200)

        assert role == "viewer"  # both colors are already claimed (one mid-grace-period)

    run(scenario())


def test_tick_advances_the_clock_and_resolves_an_expired_disconnect_into_a_resign():
    async def scenario():
        room, engine = make_room(["wK . .", ". . .", "bK . ."])
        alice = FakeConnection()
        bob = FakeConnection()
        role_alice = room.seat_or_view(alice, "alice", 1200)
        role_bob = room.seat_or_view(bob, "bob", 1200)
        await room.handle_disconnect(alice)
        room._disconnected[role_alice] = time.monotonic() - 1  # already expired

        await room.tick(time.monotonic())

        assert engine.game_over is True
        assert engine.winner == role_bob
        assert role_alice not in room._disconnected

    run(scenario())


def test_game_over_updates_both_ratings_via_the_shared_events_bus():
    async def scenario():
        events = EventBus()
        accounts = AccountStore()
        room, engine = make_room(["wR . .", ". . .", "bK . ."], events=events, accounts=accounts)
        # Room.seat_or_view takes a rating as given - registering the
        # account (normally GameServer._handle_login's job, via LOGIN) is
        # what actually creates the row update_rating later writes to.
        accounts.authenticate("alice", "pw1")
        accounts.authenticate("bob", "pw2")
        alice = FakeConnection()
        bob = FakeConnection()
        role_alice = room.seat_or_view(alice, "alice", 1200)
        role_bob = room.seat_or_view(bob, "bob", 1200)
        assert accounts.get_rating("alice") == 1200
        assert accounts.get_rating("bob") == 1200

        engine.request_move((0, 0), (2, 0))  # rook captures the other king
        engine.wait(3 * settings.MOVE_DURATION)

        assert engine.game_over is True
        winner_username = "alice" if role_alice == engine.winner else "bob"
        loser_username = "bob" if winner_username == "alice" else "alice"
        assert accounts.get_rating(winner_username) > 1200
        assert accounts.get_rating(loser_username) < 1200

    run(scenario())
