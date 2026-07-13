def parse_input(lines):
    """Split raw input lines into the 'Board:' and 'Commands:' sections.

    This handles only the command-script protocol (which lines describe the
    board vs. the commands). Turning the board lines into a Board is the job
    of a board loader (see board/loaders.py), so this stays independent of how
    any particular board format is validated or stored.
    """
    board_lines, commands = [], []
    section = None
    for line in lines:
        if line == "Board:":
            section = "board"
            continue
        if line == "Commands:":
            section = "commands"
            continue
        if section == "board":
            board_lines.append(line)
        elif section == "commands":
            commands.append(line)
    return board_lines, commands
