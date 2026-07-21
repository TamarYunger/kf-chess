import pytest

from board.board import Board
from config import settings
from realtime.real_time_arbiter import RealTimeArbiter
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion
from rules.rule_engine import RuleEngine
from rules.rule_registry import build_default_registry
from game.engine import GameEngine
from server.protocol import (
    Command, ProtocolError, encode_error, encode_login, encode_login_rejected,
    encode_no_match, encode_opponent_disconnected, encode_opponent_reconnected, encode_rejected,
    encode_room, encode_room_started, encode_snapshot, encode_waiting_for_opponent, parse_command, resolve_cells,
)
from view.snapshot_codec import snapshot_from_json


def make_engine(rows, config=settings):
    board = Board(rows)
    registry = build_default_registry(config)
    arbiter = RealTimeArbiter(board=board, promotion_rule=LastRankPromotion(config.PAWN_DIRECTION), config=config)
    engine = GameEngine(
        board=board,
        rule_engine=RuleEngine(rule_registry=registry, config=config),
        arbiter=arbiter,
        win_condition=KingCaptureWinCondition(),
        config=config,
    )
    return engine, board


def test_parse_command_move():
    assert parse_command("MOVE e2 e4") == Command("MOVE", ("e2", "e4"))


def test_parse_command_jump():
    assert parse_command("JUMP e2") == Command("JUMP", ("e2",))


def test_parse_command_is_case_insensitive_on_the_verb():
    assert parse_command("move e2 e4").verb == "MOVE"


def test_parse_command_rejects_an_empty_line():
    with pytest.raises(ProtocolError):
        parse_command("")


def test_parse_command_rejects_an_unknown_verb():
    with pytest.raises(ProtocolError):
        parse_command("FLY e2 e4")


def test_parse_command_rejects_the_wrong_number_of_squares():
    with pytest.raises(ProtocolError):
        parse_command("MOVE e2")
    with pytest.raises(ProtocolError):
        parse_command("JUMP e2 e4")


def test_resolve_cells_turns_squares_into_row_col():
    command = parse_command("MOVE e2 e4")
    assert resolve_cells(command, board_height=8) == ((6, 4), (4, 4))


def test_resolve_cells_raises_protocol_error_on_a_malformed_square():
    command = parse_command("MOVE e2 zz")
    with pytest.raises(ProtocolError):
        resolve_cells(command, board_height=8)


def test_encode_snapshot_shape_is_decodable_by_the_client_codec():
    # The whole point of this shape: server/protocol.py and
    # view/snapshot_codec.py must agree, or a real client can never
    # actually render what the server sends.
    engine, board = make_engine([["wR", ".", "."], [".", ".", "."], [".", ".", "bK"]])
    engine.request_move((0, 0), (0, 2))

    message = encode_snapshot(engine)

    assert message["type"] == "snapshot"
    decoded = snapshot_from_json(message["payload"])
    assert decoded.cells == (("wR", ".", "."), (".", ".", "."), (".", ".", "bK"))
    assert decoded.moves[0].piece == "wR"
    assert decoded.moves[0].start == (0, 0)
    assert decoded.moves[0].end == (0, 2)


def test_encode_snapshot_round_trips_move_history_and_score():
    engine, board = make_engine([["wR", ".", "bN"]])
    engine.request_move((0, 0), (0, 2))
    engine.wait(2 * settings.MOVE_DURATION)

    decoded = snapshot_from_json(encode_snapshot(engine)["payload"])

    assert decoded.score == {"w": settings.PIECE_VALUES["N"], "b": 0}
    assert decoded.move_history["w"][0].piece == "wR"


def test_encode_error_shape():
    assert encode_error("bad command") == {"type": "error", "payload": {"message": "bad command"}}


def test_encode_rejected_serializes_the_reason_as_its_plain_value():
    from rules.reasons import Reason
    message = encode_rejected(Reason.BUSY_SOURCE)
    assert message == {"type": "rejected", "payload": {"reason": "busy_source"}}


def test_parse_command_login():
    assert parse_command("LOGIN alice hunter2") == Command("LOGIN", ("alice", "hunter2"))


def test_parse_command_login_rejects_a_missing_password():
    with pytest.raises(ProtocolError):
        parse_command("LOGIN alice")


def test_parse_command_login_rejects_a_missing_username_and_password():
    with pytest.raises(ProtocolError):
        parse_command("LOGIN")


def test_parse_command_login_rejects_more_than_two_arguments():
    with pytest.raises(ProtocolError):
        parse_command("LOGIN alice hunter2 extra")


def test_encode_login_shape():
    assert encode_login("alice", 1200) == {"type": "login", "payload": {"username": "alice", "rating": 1200}}


def test_encode_login_rejected_shape():
    assert encode_login_rejected("Invalid password") == {
        "type": "login_rejected", "payload": {"message": "Invalid password"},
    }


def test_parse_command_play_takes_no_arguments():
    assert parse_command("PLAY") == Command("PLAY", ())


def test_parse_command_play_rejects_any_argument():
    with pytest.raises(ProtocolError):
        parse_command("PLAY now")


def test_parse_command_room_create():
    assert parse_command("ROOM CREATE") == Command("ROOM_CREATE", ())


def test_parse_command_room_join():
    assert parse_command("ROOM JOIN a1b2c3") == Command("ROOM_JOIN", ("a1b2c3",))


def test_parse_command_room_rejects_an_unknown_subcommand():
    with pytest.raises(ProtocolError):
        parse_command("ROOM DESTROY")


def test_parse_command_room_create_rejects_an_argument():
    with pytest.raises(ProtocolError):
        parse_command("ROOM CREATE extra")


def test_parse_command_room_join_rejects_a_missing_room_id():
    with pytest.raises(ProtocolError):
        parse_command("ROOM JOIN")


def test_parse_command_room_alone_is_an_error():
    with pytest.raises(ProtocolError):
        parse_command("ROOM")


def test_encode_room_shape():
    assert encode_room("a1b2c3", "w") == {"type": "room", "payload": {"room_id": "a1b2c3", "role": "w"}}


def test_encode_no_match_shape():
    assert encode_no_match() == {"type": "no_match", "payload": None}


def test_encode_opponent_disconnected_shape():
    assert encode_opponent_disconnected("w", 20) == {
        "type": "opponent_disconnected", "payload": {"color": "w", "grace_period_seconds": 20},
    }


def test_encode_opponent_reconnected_shape():
    assert encode_opponent_reconnected("w") == {"type": "opponent_reconnected", "payload": {"color": "w"}}


def test_encode_waiting_for_opponent_shape():
    assert encode_waiting_for_opponent() == {"type": "waiting_for_opponent", "payload": None}


def test_encode_room_started_shape():
    assert encode_room_started() == {"type": "room_started", "payload": None}
