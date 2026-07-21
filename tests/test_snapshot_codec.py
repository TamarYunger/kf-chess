from config import settings
from view.graphics_renderer import GraphicsRenderer
from view.snapshot_codec import snapshot_from_json


def minimal_json(**overrides):
    data = {
        "cells": [["wR", ".", "."], [".", ".", "."], [".", ".", "bK"]],
        "width": 3,
        "height": 3,
        "game_over": False,
    }
    data.update(overrides)
    return data


def test_decodes_the_required_fields():
    snapshot = snapshot_from_json(minimal_json())

    assert snapshot.cells == (("wR", ".", "."), (".", ".", "."), (".", ".", "bK"))
    assert snapshot.width == 3
    assert snapshot.height == 3
    assert snapshot.game_over is False


def test_optional_fields_default_like_gamesnapshot_itself():
    snapshot = snapshot_from_json(minimal_json())

    assert snapshot.selected is None
    assert snapshot.rejection_reason is None
    assert snapshot.legal_destinations == frozenset()
    assert snapshot.moves == ()
    assert snapshot.jumps == ()
    assert snapshot.recent_arrivals == ()
    assert snapshot.clock == 0
    assert snapshot.winner is None
    assert snapshot.move_history == {}
    assert snapshot.score == {}


def test_decodes_selected_and_legal_destinations_as_cell_tuples():
    data = minimal_json(selected=[0, 0], legal_destinations=[[0, 1], [0, 2]])

    snapshot = snapshot_from_json(data)

    assert snapshot.selected == (0, 0)
    assert snapshot.legal_destinations == frozenset({(0, 1), (0, 2)})


def test_decodes_moves_jumps_and_recent_arrivals():
    data = minimal_json(
        moves=[{"piece": "wR", "start": [0, 0], "end": [0, 2], "arrival": 2000, "path": [[0, 1], [0, 2]]}],
        jumps=[{"piece": "bK", "cell": [2, 2], "end_time": 1000}],
        recent_arrivals=[{"piece": "wR", "cell": [0, 2], "at": 500, "kind": "move"}],
        clock=750,
    )

    snapshot = snapshot_from_json(data)

    move = snapshot.moves[0]
    assert (move.piece, move.start, move.end, move.arrival, move.path) == ("wR", (0, 0), (0, 2), 2000, ((0, 1), (0, 2)))
    jump = snapshot.jumps[0]
    assert (jump.piece, jump.cell, jump.end_time) == ("bK", (2, 2), 1000)
    arrival = snapshot.recent_arrivals[0]
    assert (arrival.piece, arrival.cell, arrival.at, arrival.kind) == ("wR", (0, 2), 500, "move")
    assert snapshot.clock == 750


def test_decodes_move_history_and_score():
    data = minimal_json(
        move_history={"w": [{"piece": "wR", "start": [0, 0], "end": [0, 2], "promoted_to": None}], "b": []},
        score={"w": 3, "b": 0},
        winner="w",
        game_over=True,
    )

    snapshot = snapshot_from_json(data)

    record = snapshot.move_history["w"][0]
    assert (record.piece, record.start, record.end, record.promoted_to) == ("wR", (0, 0), (0, 2), None)
    assert snapshot.move_history["b"] == ()
    assert snapshot.score == {"w": 3, "b": 0}
    assert snapshot.winner == "w"
    assert snapshot.game_over is True


def test_decoded_snapshot_renders_without_error():
    # The whole point of matching GameSnapshot's shape: GraphicsRenderer
    # (untouched by this refactor) must accept a decoded snapshot exactly
    # like it accepts a locally-built one.
    data = minimal_json(
        moves=[{"piece": "wR", "start": [0, 0], "end": [0, 2], "arrival": 2000, "path": [[0, 1], [0, 2]]}],
        score={"w": 3, "b": 0},
    )
    snapshot = snapshot_from_json(data)
    renderer = GraphicsRenderer(settings)

    canvas = renderer.render(snapshot)

    assert canvas.img is not None
