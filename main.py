"""KungFu Chess - entry point.

Repository: <insert-git-repository-url-here>
"""
import sys

from config import settings
from rules.rule_registry import build_default_registry
from rules.rule_engine import RuleEngine
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion
from board_io.parser import parse_input, build_board, BoardParseError
from game.board_mapper import BoardMapper
from realtime.real_time_arbiter import RealTimeArbiter
from game.engine import GameEngine
from game.controller import Controller
from board_io.board_printer import BoardPrinter


def run(input_lines, config=settings):
    """Parse input and execute all commands. `config` is injectable so
    tests (or custom variants) can supply alternate settings without
    monkeypatching the settings module.
    """
    board_lines, commands = parse_input(input_lines)
    registry = build_default_registry(config)

    try:
        board = build_board(board_lines, registry, config)
    except BoardParseError as error:
        print("ERROR", error)
        return

    real_time_arbiter = RealTimeArbiter(
        board=board,
        win_condition=KingCaptureWinCondition(),
        promotion_rule=LastRankPromotion(),
        config=config,
    )
    engine = GameEngine(
        board=board,
        rule_engine=RuleEngine(registry, config),
        real_time_arbiter=real_time_arbiter,
        config=config,
    )
    controller = Controller(engine, BoardMapper(board, config.CELL_SIZE))
    renderer = BoardPrinter(config.EMPTY_CELL)

    for command in commands:
        _dispatch(command, controller, engine, renderer)


def _dispatch(command, controller, engine, renderer):
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


def main():
    lines = [line.strip() for line in sys.stdin]
    run(lines)


if __name__ == "__main__":
    main()
