from game.parser import parse_input


def test_parse_input_splits_sections():
    lines = ["Board:", "wK . bK", "Commands:", "print", "wait 5"]
    board_lines, commands = parse_input(lines)
    assert board_lines == ["wK . bK"]
    assert commands == ["print", "wait 5"]


def test_parse_input_ignores_lines_before_any_section():
    lines = ["junk", "Board:", "wK", "Commands:", "print"]
    board_lines, commands = parse_input(lines)
    assert board_lines == ["wK"]
    assert commands == ["print"]
