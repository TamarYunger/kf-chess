"""KungFu Chess - entry point.

Repository: https://github.com/TamarYunger/kf-chess
"""
import sys

from config import settings
from rules.rule_registry import build_default_registry
from rules.rule_engine import RuleEngine
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion
from realtime.real_time_arbiter import RealTimeArbiter
from game.parser import parse_input
from board.loaders import load_text_board, BoardParseError
from game.board_mapper import BoardMapper
from game.engine import GameEngine
from game.controller import Controller
from view.renderer import BoardRenderer


def run(input_lines, config=settings):
    """Parse input and execute all commands. `config` is injectable so
    tests (or custom variants) can supply alternate settings without
    monkeypatching the settings module.
    """
    board_lines, commands = parse_input(input_lines)
    registry = build_default_registry(config)

    try:
        board = load_text_board(board_lines, registry, config)
    except BoardParseError as error:
        print("ERROR", error)
        return

    arbiter = RealTimeArbiter(
        board=board,
        promotion_rule=LastRankPromotion(config.PAWN_DIRECTION),
        config=config,
    )
    engine = GameEngine(
        board=board,
        rule_engine=RuleEngine(rule_registry=registry, config=config),
        arbiter=arbiter,
        win_condition=KingCaptureWinCondition(),
        config=config,
    )
    controller = Controller(
        engine=engine,
        board_mapper=BoardMapper(board, config.CELL_SIZE),
    )
    renderer = BoardRenderer()

    for command in commands:
        _dispatch(command, engine, controller, renderer)


def _dispatch(command, engine, controller, renderer):
    parts = command.split()
    if not parts:
        return

    action = parts[0]
    if action == "click":
        controller.click(int(parts[1]), int(parts[2]))
    elif action == "jump":
        controller.jump(int(parts[1]), int(parts[2]))
    elif action == "wait":
        engine.wait(int(parts[1]))
    elif action == "print":
        print(engine.render(renderer))


def main(input_stream=None):
    """Read a script and run it. `input_stream` is injectable so tests can
    supply a file-like object instead of monkeypatching sys.stdin; it defaults
    to real stdin.
    """
    stream = sys.stdin if input_stream is None else input_stream
    lines = [line.strip() for line in stream]
    run(lines)


if __name__ == "__main__":  # pragma: no cover
    main()
