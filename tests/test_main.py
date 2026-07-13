import io
import types

import main as main_module


def test_run_prints_board_on_print_command(capsys):
    lines = ["Board:", "wK . bK", "Commands:", "print"]
    main_module.run(lines)
    out = capsys.readouterr().out
    assert out.strip() == "wK . bK"


def test_run_reports_parse_error(capsys):
    lines = ["Board:", "wX . bK", "Commands:", "print"]
    main_module.run(lines)
    out = capsys.readouterr().out
    assert out.startswith("ERROR")


def test_run_accepts_injected_config(capsys):
    custom_config = types.SimpleNamespace(
        CELL_SIZE=50,
        MOVE_DURATION=10,
        JUMP_DURATION=10,
        COLORS=("w", "b"),
        PAWN_DIRECTION={"w": -1, "b": 1},
        EMPTY_CELL=".",
        ALLOW_CONCURRENT_MOVES=False,
    )
    lines = ["Board:", "wK . bK", "Commands:", "print"]
    main_module.run(lines, config=custom_config)
    out = capsys.readouterr().out
    assert out.strip() == "wK . bK"


def test_dispatch_ignores_blank_command():
    # Should not raise for an empty command line.
    main_module._dispatch("", engine=None, controller=None, renderer=None)


def test_run_executes_click_wait_and_print(capsys):
    lines = [
        "Board:",
        "wR . .",
        ". . .",
        ". . .",
        "Commands:",
        "click 0 0",
        "click 200 0",
        "wait 2000",
        "print",
    ]
    main_module.run(lines)
    out = capsys.readouterr().out
    assert out.strip() == ". . wR\n. . .\n. . ."


def test_run_handles_jump_command(capsys):
    lines = ["Board:", ". wK .", "Commands:", "jump 100 0", "wait 1000", "print"]
    main_module.run(lines)
    out = capsys.readouterr().out
    assert out.strip() == ". wK ."


def test_main_reads_from_injected_stream(capsys):
    stream = io.StringIO("Board:\nwK . bK\nCommands:\nprint\n")
    main_module.main(input_stream=stream)
    out = capsys.readouterr().out
    assert out.strip() == "wK . bK"
