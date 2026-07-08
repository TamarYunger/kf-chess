"""Central configuration for KungFu Chess.

All game constants live here so game logic never hardcodes magic numbers.
Changing timing, supported colors, or pawn starting rows only requires
editing this file - no other module should contain literal values like
these.
"""

# Rendering / timing (milliseconds)
CELL_SIZE = 100
MOVE_DURATION = 1000
JUMP_DURATION = 1000

# Player colors supported by the game
COLORS = ("w", "b")

# Row delta a pawn advances by on a single step, per color
PAWN_DIRECTION = {"w": -1, "b": 1}

# Starting row (0-indexed) from which each color's pawns may take a double step
PAWN_START_ROW = {"w": 1, "b": 6}

# Token used to represent an empty cell on the board
EMPTY_CELL = "."
