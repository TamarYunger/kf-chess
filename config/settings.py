"""Central configuration for KungFu Chess.

All game constants live here so game logic never hardcodes magic numbers.
Changing timing, supported colors, or pawn direction only requires
editing this file - no other module should contain literal values like
these.
"""

# Rendering / timing (milliseconds)
CELL_SIZE = 100
MOVE_DURATION = 1000
JUMP_DURATION = 1000

# Player colors supported by the game
COLORS = ("w", "b")

# Row delta a pawn advances by on a single step, per color.
# The double-step home rank is not configured here: it is derived from the
# board height in PawnMovement (0 for a downward color, height-1 for an
# upward one), so the rule works for any board size.
PAWN_DIRECTION = {"w": -1, "b": 1}



# Token used to represent an empty cell on the board
EMPTY_CELL = "."

# Gameplay policy: may several moves be in flight at the same time?
# The real-time variant resolves a contested route in favour of whoever
# started first, so only one move is allowed at a time (default False).
# Set True to re-enable concurrent moves.
ALLOW_CONCURRENT_MOVES = False