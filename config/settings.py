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
# "long_rest" animation states). These are the fallback values used by the
# text-mode CLI and by tests, which have no loaded sprite assets to sync to;
# main_gui.py overrides both at startup with the real short_rest/long_rest
# sprites' own playback duration (frame_count/fps), so in the graphical game
# the cooldown always exactly matches how long the rest animation plays.
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

# Points a color's score gains when it captures a piece of the given kind.
# King is 0 - capturing it already ends the game via the win condition, so
# it earns no additional score on top of that.
PIECE_VALUES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}

# Gameplay policy: may several moves be in flight at the same time?
# True is the actual KungFu Chess rule: there are no turns, so any number of
# pieces - either color, any mix - can be moving at once; the only per-piece
# limit is its own busy/resting state (see GameEngine.is_busy). A contested
# destination is resolved in favour of whoever started first. Set False to
# fall back to one-motion-at-a-time (useful for simpler manual testing).
ALLOW_CONCURRENT_MOVES = True
