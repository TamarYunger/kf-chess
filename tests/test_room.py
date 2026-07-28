import asyncio
import json
import logging
import time

from bus.event_bus import EventBus
from config import settings
from server.db import AccountStore
from server.protocol import parse_command
from server.room import DISCONNECT_GRACE_SECONDS, Room
from server.shard import build_engine


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
        alice = FakeConnection()
        bob = FakeConnection()
        role = room.seat_or_view(alice, "alice", 1200)
        room.seat_or_view(bob, "bob", 1200)  # room is started before welcome() - no waiting message

        await room.welcome(alice, role)

        assert len(alice.sent) == 2
        room_msg = json.loads(alice.sent[0])
        assert room_msg == {"type": "room", "payload": {"room_id": "abc123", "role": settings.COLORS[0]}}
        snapshot_msg = json.loads(alice.sent[1])
        assert snapshot_msg["type"] == "snapshot"

    run(scenario())


def test_welcome_of_a_lone_creator_also_sends_waiting_for_opponent():
    async def scenario():
        room, engine = make_room()
        conn = FakeConnection()
        role = room.seat_or_view(conn, "alice", 1200)

        await room.welcome(conn, role)

        assert len(conn.sent) == 3
        assert json.loads(conn.sent[1]) == {"type": "waiting_for_opponent", "payload": None}

    run(scenario())


def test_a_lone_creator_cannot_move_before_anyone_joins():
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", ". . ."])
        alone = FakeConnection()
        room.seat_or_view(alone, "alice", 1200)

        await room.handle_command(alone, parse_command("MOVE a3 c3"))

        rejected = json.loads(alone.sent[-1])
        assert rejected == {"type": "rejected", "payload": {"reason": "waiting_for_opponent"}}
        assert engine.snapshot().cells[0][0] == "wR"  # untouched - never reached the engine

    run(scenario())


def test_room_started_flips_true_once_the_second_seat_is_filled():
    room, engine = make_room()
    assert room.started is False

    room.seat_or_view(FakeConnection(), "alice", 1200)
    assert room.started is False

    room.seat_or_view(FakeConnection(), "bob", 1200)
    assert room.started is True


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


def test_a_seated_player_cannot_move_the_other_colors_piece():
    # GameEngine itself has no notion of turns/ownership (both colors are
    # one person for LocalGameSession's offline hotseat play) - Room is
    # what has to enforce, per network connection, that a seated player
    # only moves their own color.
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", "bK . ."])
        white = FakeConnection()
        black = FakeConnection()
        room.seat_or_view(white, "alice", 1200)  # first color (white)
        room.seat_or_view(black, "bob", 1200)  # second color (black)

        await room.handle_command(black, parse_command("MOVE a3 c3"))  # a3 holds the white rook

        rejected = json.loads(black.sent[-1])
        assert rejected == {"type": "rejected", "payload": {"reason": "not_your_piece"}}
        assert engine.snapshot().cells[0][0] == "wR"  # untouched - never reached the engine

    run(scenario())


def test_select_replies_with_legal_destinations_for_the_requesters_own_piece():
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", "bK . ."])
        white = FakeConnection()
        room.seat_or_view(white, "alice", 1200)
        room.seat_or_view(FakeConnection(), "bob", 1200)

        await room.handle_command(white, parse_command("SELECT a3"))

        reply = json.loads(white.sent[-1])
        assert reply == {
            "type": "legal_destinations",
            "payload": {"start": [0, 0], "destinations": [[0, 1], [0, 2], [1, 0], [2, 0]]},
        }

    run(scenario())


def test_select_of_the_opponents_piece_replies_with_no_destinations():
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", "bK . ."])
        white = FakeConnection()
        room.seat_or_view(white, "alice", 1200)
        room.seat_or_view(FakeConnection(), "bob", 1200)

        await room.handle_command(white, parse_command("SELECT a1"))  # a1 holds the black king

        reply = json.loads(white.sent[-1])
        assert reply == {"type": "legal_destinations", "payload": {"start": [2, 0], "destinations": []}}

    run(scenario())


def test_select_of_an_empty_cell_replies_with_no_destinations():
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", "bK . ."])
        white = FakeConnection()
        room.seat_or_view(white, "alice", 1200)
        room.seat_or_view(FakeConnection(), "bob", 1200)

        await room.handle_command(white, parse_command("SELECT b3"))

        reply = json.loads(white.sent[-1])
        assert reply == {"type": "legal_destinations", "payload": {"start": [0, 1], "destinations": []}}

    run(scenario())


def test_select_from_a_non_seated_connection_is_rejected():
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", "bK . ."])
        stranger = FakeConnection()

        await room.handle_command(stranger, parse_command("SELECT a3"))

        error = json.loads(stranger.sent[-1])
        assert error["type"] == "error"

    run(scenario())


def test_select_is_answered_even_before_the_room_has_started():
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", ". . ."])
        alone = FakeConnection()
        room.seat_or_view(alone, "alice", 1200)

        await room.handle_command(alone, parse_command("SELECT a3"))

        reply = json.loads(alone.sent[-1])
        assert reply["type"] == "legal_destinations"
        assert reply["payload"]["destinations"] != []

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


def test_is_reclaimable_and_notify_reconnected_around_a_reconnect():
    async def scenario():
        room, engine = make_room()
        alice = FakeConnection()
        bob = FakeConnection()
        role_alice = room.seat_or_view(alice, "alice", 1200)
        room.seat_or_view(bob, "bob", 1200)
        await room.handle_disconnect(alice)

        assert room.is_reclaimable("alice") is True
        assert room.is_reclaimable("bob") is False

        new_connection = FakeConnection()
        role = room.seat_or_view(new_connection, "alice", 1200)
        assert room.is_reclaimable("alice") is False  # reclaimed, no longer pending

        bob.sent.clear()
        await room.notify_reconnected(role)

        notice = json.loads(bob.sent[-1])
        assert notice == {"type": "opponent_reconnected", "payload": {"color": role_alice}}

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


def test_tick_broadcasts_a_resign_message_before_game_over_for_an_auto_resign():
    async def scenario():
        room, engine = make_room(["wK . .", ". . .", "bK . ."])
        alice = FakeConnection()
        bob = FakeConnection()
        role_alice = room.seat_or_view(alice, "alice", 1200)
        role_bob = room.seat_or_view(bob, "bob", 1200)
        await room.handle_disconnect(alice)
        room._disconnected[role_alice] = time.monotonic() - 1  # already expired

        await room.tick(time.monotonic())

        messages = [json.loads(m) for m in bob.sent]
        resign_index = next(i for i, m in enumerate(messages) if m["type"] == "resign")
        game_over_index = next(i for i, m in enumerate(messages) if m["type"] == "game_over")
        assert messages[resign_index]["payload"] == {"color": role_alice}
        assert messages[game_over_index]["payload"] == {"winner": role_bob}
        assert resign_index < game_over_index  # a client sees why before the outcome

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
        room.seat_or_view(bob, "bob", 1200)
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


def test_tick_broadcasts_an_arrival_message_once_a_move_lands():
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", "bK . ."])
        alice = FakeConnection()
        bob = FakeConnection()
        room.seat_or_view(alice, "alice", 1200)
        room.seat_or_view(bob, "bob", 1200)
        await room.handle_command(alice, parse_command("MOVE a3 b3"))  # 1 square
        bob.sent.clear()

        await room.tick(time.monotonic() + settings.MOVE_DURATION / 1000 + 0.2)

        arrivals = [json.loads(m) for m in bob.sent if json.loads(m)["type"] == "arrival"]
        assert arrivals == [{"type": "arrival", "payload": {"piece": "wR", "destination": [0, 1], "captured": None}}]

    run(scenario())


def test_tick_broadcasts_arrival_and_game_over_for_a_king_capturing_move():
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", "bK . ."])
        alice = FakeConnection()
        bob = FakeConnection()
        role_alice = room.seat_or_view(alice, "alice", 1200)
        room.seat_or_view(bob, "bob", 1200)
        await room.handle_command(alice, parse_command("MOVE a3 a1"))  # 2 squares, captures bK
        bob.sent.clear()

        await room.tick(time.monotonic() + 2 * settings.MOVE_DURATION / 1000 + 0.2)

        messages = [json.loads(m) for m in bob.sent]
        arrival = next(m for m in messages if m["type"] == "arrival")
        game_over = next(m for m in messages if m["type"] == "game_over")
        assert arrival["payload"] == {"piece": "wR", "destination": [2, 0], "captured": "bK"}
        assert game_over["payload"] == {"winner": role_alice}

    run(scenario())


def test_handle_command_flushes_an_event_that_became_due_between_ticks():
    # The narrow real race this guards against: engine time can only ever
    # advance through Room.tick(), but a client's command can reach the
    # room in the window between two periodic ticks, after the engine
    # clock (and so resolve()) has already moved past a pending move's
    # arrival - handle_command must still flush that, not wait for the
    # next tick. Simulated here by advancing the engine directly (as
    # tick() itself would) without going through Room.tick() at all, then
    # issuing an unrelated command.
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", "bK . ."])
        alice = FakeConnection()
        bob = FakeConnection()
        room.seat_or_view(alice, "alice", 1200)
        room.seat_or_view(bob, "bob", 1200)
        await room.handle_command(alice, parse_command("MOVE a3 b3"))
        bob.sent.clear()

        engine.wait(settings.MOVE_DURATION)  # settles the move, bypassing Room.tick()

        await room.handle_command(alice, parse_command("SELECT a3"))  # any other command

        arrivals = [json.loads(m) for m in bob.sent if json.loads(m)["type"] == "arrival"]
        assert len(arrivals) == 1

    run(scenario())


def test_on_game_over_is_a_noop_when_colors_isnt_the_two_player_case():
    # _on_game_over assumes exactly two colors (Elo is a two-player rating) -
    # a room configured with any other color count must not blow up or
    # touch accounts when the engine it wraps reports game_over.
    engine = build_engine(["wK . .", ". . .", ". . ."], settings)
    accounts = AccountStore()
    Room("room1", engine, colors=("w",), accounts=accounts)

    engine.events.publish("game_over", {"winner": "w"})  # must not raise

    assert accounts.get_rating("w") is None  # never looked up, let alone written


def test_on_game_over_is_a_noop_when_a_seat_was_never_filled():
    # A game_over reported before both colors are ever seated (e.g. the
    # engine's own win condition fires while a room is still waiting for a
    # second player) has nothing to rate - only one seat's info is known.
    events = EventBus()
    accounts = AccountStore()
    room, engine = make_room(["wK . .", ". . .", "bK . ."], events=events, accounts=accounts)
    accounts.authenticate("alice", "pw1")
    room.seat_or_view(FakeConnection(), "alice", 1200)

    engine.events.publish("game_over", {"winner": "w"})  # must not raise

    assert accounts.get_rating("alice") == 1200  # untouched


def test_notify_room_started_is_a_noop_when_no_one_is_left_to_notify():
    async def scenario():
        room, engine = make_room()
        creator = FakeConnection()
        room.seat_or_view(creator, "alice", 1200)
        await room.handle_disconnect(creator)  # no one left in the room at all

        await room.notify_room_started(exclude=FakeConnection())  # must not raise

    run(scenario())


def test_broadcast_is_a_noop_when_the_room_is_empty():
    async def scenario():
        room, engine = make_room()

        await room.broadcast()  # no seats, no viewers - must not raise

    run(scenario())


def test_select_with_a_malformed_square_replies_with_an_error():
    async def scenario():
        room, engine = make_room()
        alice = FakeConnection()
        room.seat_or_view(alice, "alice", 1200)
        room.seat_or_view(FakeConnection(), "bob", 1200)

        await room.handle_command(alice, parse_command("SELECT zz"))

        error = json.loads(alice.sent[-1])
        assert error["type"] == "error"

    run(scenario())


def test_move_with_a_malformed_square_replies_with_an_error():
    async def scenario():
        room, engine = make_room()
        alice = FakeConnection()
        room.seat_or_view(alice, "alice", 1200)
        room.seat_or_view(FakeConnection(), "bob", 1200)

        await room.handle_command(alice, parse_command("MOVE zz aa"))

        error = json.loads(alice.sent[-1])
        assert error["type"] == "error"

    run(scenario())


def test_seated_jump_is_accepted_and_broadcast():
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", "bK . ."])
        alice = FakeConnection()
        room.seat_or_view(alice, "alice", 1200)
        room.seat_or_view(FakeConnection(), "bob", 1200)

        await room.handle_command(alice, parse_command("JUMP a3"))  # alice's own rook

        accepted = json.loads(alice.sent[-1])
        assert accepted["type"] == "snapshot"

    run(scenario())


def test_seated_jump_is_rejected_when_the_cell_is_empty():
    async def scenario():
        room, engine = make_room(["wR . .", ". . .", "bK . ."])
        alice = FakeConnection()
        room.seat_or_view(alice, "alice", 1200)
        room.seat_or_view(FakeConnection(), "bob", 1200)

        await room.handle_command(alice, parse_command("JUMP b3"))  # empty cell

        rejected = json.loads(alice.sent[-1])
        assert rejected == {"type": "rejected", "payload": {"reason": "empty_cell"}}

    run(scenario())


def test_a_real_illegal_move_is_rejected_with_its_actual_reason_once_started():
    # Unlike test_illegal_move_is_rejected_not_broadcast (only one seat
    # filled, so it's rejected earlier as waiting_for_opponent), this seats
    # both colors first, so the rejection actually comes from GameEngine.
    async def scenario():
        room, engine = make_room(["wN . .", ". . .", "bK . ."])
        alice = FakeConnection()
        room.seat_or_view(alice, "alice", 1200)
        room.seat_or_view(FakeConnection(), "bob", 1200)

        await room.handle_command(alice, parse_command("MOVE a3 b3"))  # not a legal knight move

        rejected = json.loads(alice.sent[-1])
        assert rejected == {"type": "rejected", "payload": {"reason": "illegal_piece_move"}}
        assert engine.snapshot().cells[0][0] == "wN"  # untouched

    run(scenario())

    run(scenario())
