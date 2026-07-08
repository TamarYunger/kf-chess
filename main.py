"""KungFu Chess - entry point.

Repository: <insert-git-repository-url-here>
"""
import sys

from config import settings
from rules.rule_registry import build_default_registry
from rules.game_conditions import KingCaptureWinCondition, LastRankPromotion
from game.parser import parse_input, build_board, BoardParseError
from game.engine import GameEngine
from game.renderer import BoardRenderer


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

    engine = GameEngine(
        board=board,
        rule_registry=registry,
        win_condition=KingCaptureWinCondition(),
        promotion_rule=LastRankPromotion(),
        config=config,
    )
    renderer = BoardRenderer()

    for command in commands:
        _dispatch(command, engine, renderer)


def _dispatch(command, engine, renderer):
    parts = command.split()
    if not parts:
        return

    action = parts[0]
    if action == "click":
        engine.handle_click(int(parts[1]), int(parts[2]))
    elif action == "jump":
        engine.handle_jump(int(parts[1]), int(parts[2]))
    elif action == "wait":
        engine.wait(int(parts[1]))
    elif action == "print":
        print(engine.render(renderer))


def main():
    lines = [line.strip() for line in sys.stdin]
    run(lines)


if __name__ == "__main__":
    main()
