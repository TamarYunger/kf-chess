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

# How long a piece is blocked from starting a new move/jump after it lands,
# per the kind of motion that landed it (mirrors the "short_rest"/
# "long_rest" animation states, but is a separate, independently tunable
# gameplay knob - not derived from the rest sprites' own frame_count/fps,
# since sprite length is an art decision and cooldown length is a balance
# decision).
SHORT_REST_DURATION = 1000  # after landing from a jump
LONG_REST_DURATION = 3000  # after landing from a move

# Folder (relative to the project root) holding the graphics UI's assets:
# board.png and pieces/<KIND><COLOR>/states/<state>/{config.json,sprites/*.png}
ASSETS_DIR = "assets"

# Player colors supported by the game
COLORS = ("w", "b")

# Row delta a pawn advances by on a single step, per color.
# The double-step home rank is not configured here: it is derived from the
# board height in PawnMovement (1 for a downward color, height-2 for an
# upward one - one row in front of the back rank, as in standard chess),
# so the rule works for any board size.
PAWN_DIRECTION = {"w": -1, "b": 1}

# Token used to represent an empty cell on the board
EMPTY_CELL = "."

# Gameplay policy: may several moves be in flight at the same time?
# The real-time variant resolves a contested route in favour of whoever
# started first, so only one move is allowed at a time (default False).
# Set True to re-enable concurrent moves.
ALLOW_CONCURRENT_MOVES = False
