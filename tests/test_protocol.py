import pytest

from board.board import Board
from config import settings
from realtime.real_time_arbiter import RealTimeArbiter
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion
from rules.rule_engine import RuleEngine
from rules.rule_registry import build_default_registry
from game.engine import GameEngine
from server.protocol import (
    Command, ProtocolError, encode_error, encode_rejected, encode_snapshot, parse_command, resolve_cells,
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
