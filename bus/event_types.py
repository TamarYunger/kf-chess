"""Canonical names for every string-tagged message routed through this
project's EventBus instances (bus/event_bus.py) or GameSession.submit_command
- so a typo in a name fails fast (ImportError/AttributeError at import time,
or a NameError from the linter/IDE) instead of silently going unheard. Same
family of problem as server/room.py's `_call_engine` (see its own
docstring) - a failure mode with no exception and no test failure, just a
message that never arrives.

Three unrelated vocabularies share this module - not because they're the
same mechanism, but because they're the same *kind* of risk (a bare string
literal repeated at every publish/subscribe call site):

1. GameEngine's own domain events (game/engine.py, game/move_history.py) -
   published with real Python payloads (an ArrivalEvent, a plain dict),
   whether the engine lives in-process (LocalGameSession) or inside a
   server/room.py Room.
2. Server -> client wire message "type" values (server/protocol.py's
   encode_* functions) - re-published verbatim by NetworkGameSession.tick()
   onto the same client-side bus GameEngine's own events use. GAME_OVER and
   ARRIVAL above are reused unchanged for two of these on purpose - see
   client/view/sound.py's own docstring: the same event *names* reach it
   whether a game is local or online.
3. NetworkClient's own connection-lifecycle events (connected/disconnected/
   connection_error) - never sent by the server, invented client-side, but
   funneled onto the same bus the same way (see network_client.py).
4. GameScreen -> GameSession.submit_command's UI command "type" values -
   not a bus event at all, but the exact same failure mode (LocalGameSession
   and NetworkGameSession each compare `command["type"]` against a literal).

Deliberately plain string constants, not an enum - EventBus doesn't care
about the type, only equality/hashing as a dict key, and every payload
shape is already documented at its own publish/encode call site; this only
needs to kill typos, not add a new type.
"""

# -- GameEngine's own domain events (game/engine.py, game/move_history.py) --
GAME_STARTED = "game_started"
MOVE_ACCEPTED = "move_accepted"
RESIGN = "resign"
GAME_OVER = "game_over"
ARRIVAL = "arrival"
SCORE_CHANGED = "score_changed"
MOVE_LOG_UPDATED = "move_log_updated"

# -- Server -> client wire message types (server/protocol.py) --
SNAPSHOT = "snapshot"
ERROR = "error"
REJECTED = "rejected"
LOGIN = "login"
LOGIN_REJECTED = "login_rejected"
ROOM = "room"
NO_MATCH = "no_match"
OPPONENT_DISCONNECTED = "opponent_disconnected"
OPPONENT_RECONNECTED = "opponent_reconnected"
LEGAL_DESTINATIONS = "legal_destinations"
WAITING_FOR_OPPONENT = "waiting_for_opponent"
ROOM_STARTED = "room_started"

# -- NetworkClient's own client-local connection-lifecycle events --
CONNECTED = "connected"
DISCONNECTED = "disconnected"
CONNECTION_ERROR = "connection_error"

# -- GameScreen -> GameSession.submit_command UI command types --
CLICK = "click"
JUMP = "jump"
