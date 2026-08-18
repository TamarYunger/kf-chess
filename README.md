# KungFu Chess

Real-time variant of chess: moves and jumps resolve after a delay instead
of instantly, and a "jump" onto a square can intercept an incoming enemy
move. Playable three ways - a text-mode script runner, an offline
graphical hotseat board, and a real client/server multiplayer game with
login, matchmaking, and private rooms.

## Entry points

```
main.py         text-mode CLI - reads a board + a script of click/jump/wait/print
                commands from stdin, no GUI at all.
main_gui.py     offline GUI ("Play Offline") - a graphical hotseat board,
                both colors played from one window, no server involved.
main_online.py  online GUI - LOGIN -> HOME -> PLAY (matchmaking) / ROOM
                (create or join by id) -> GAME, talking to a real server
                over WebSocket (see "Running the server" below).
```

`main_gui.py` and `main_online.py` share the same window/render loop
(`client/view/app_loop.py`) and the same board screen
(`client/view/game_screen.py`) - neither duplicates the other's rendering
code; they only differ in which `GameSession` (`client/session/`) and
which set of screens they wire up.

## Project layout

```
config/    settings.py            - all constants (timing, colors, pawn config, piece values)
board/     board.py               - Board, the single internal representation
           piece.py               - board-token helpers (color_of/kind_of)
           loaders.py             - input-format adapters: text -> Board (add binary/FEN here)
           notation.py            - algebraic square <-> (row, col), move notation for the log
bus/       event_bus.py           - plain string-keyed pub/sub, shared by GameEngine and the UI
rules/     movement_strategy.py   - MovementStrategy interface + MoveContext
           piece_rules.py         - King/Queen/Rook/Bishop/Knight/Pawn strategies
           rule_registry.py       - PieceRuleRegistry (Registry/Factory pattern)
           rule_engine.py         - RuleEngine (read-only move validation) + MoveValidation
           reasons.py             - Reason codes a rejected move/jump carries
           game_conditions.py     - WinCondition / PromotionRule strategies
realtime/  models.py              - Move / Jump / Arrival in-flight motion objects
           real_time_arbiter.py   - RealTimeArbiter (clock, arrivals, interception) + ArrivalEvent
game/      models.py              - MoveResult + Reason (engine command-boundary result)
           parser.py              - splits the command script into board/commands sections
           board_mapper.py        - BoardMapper (pixel -> cell)
           controller.py          - Controller (selection state + click/jump dispatch)
           move_history.py        - per-color accepted-move log, subscribed to the event bus
           presentation_stub.py   - placeholder sound/animation subscriber (text mode has none)
           engine.py              - GameEngine (application-service coordinator)
           snapshot.py            - GameSnapshot (read-only view model, owned by the engine)
server/    a small distributed system (see Server_Design.md for the full topology),
           not one process - a Room/GameEngine and the real socket that reaches
           it live in two different services, talking over NATS:
           ws_server.py           - WS Gateway: holds every live socket, forwards
                                     AUTH/PLAY/ROOM/MOVE/JUMP/SELECT to whichever
                                     Shard owns the room
           api_gateway.py         - REST front door: POST /login issues a
                                     short-lived token for AUTH to redeem
           shard.py               - Game Shard: hosts Room/GameEngine instances,
                                     the sole source of truth for game rules
           room.py                - Room: one game's seats, GameEngine, disconnect
                                     grace period
           matchmaker_service.py  - Matchmaker: PLAY's rating-range opponent
                                     search over a Redis-backed waiting queue
           allocator_service.py   - Allocator: picks which Shard replica a new
                                     room lands on (power-of-two-choices)
           matchmaking.py         - find_opponent: the pure rating-range search
                                     the Matchmaker calls
           nats_connection.py     - NatsConnectionProxy: looks like a live
                                     connection to Room, routes over NATS instead
           inbox.py               - shared NATS inbox parse/dispatch/except shape
           protocol.py            - wire format: text commands in, JSON
                                     snapshots/events out
           db.py                  - AccountStore/PostgresAccountStore
                                     (username/password/rating) + Redis/DSN wiring
           elo.py                 - rating update on game_over
           health.py              - GET /health and GET /metrics for each service
           safe_send.py           - swallows a send() to an already-closed connection
           logging_config.py      - server-side log file setup
client/    everything that only ever runs on the player's machine
  session/   game_session.py        - GameSession: the abstract session interface the UI talks to
             local_game_session.py - GameSession backed by an in-process GameEngine ("Play Offline")
             network_game_session.py - GameSession backed by a WebSocket connection to a server
             network_client.py     - the WebSocket connection itself, on its own background thread
             snapshot_codec.py     - decodes the server's JSON snapshot back into a GameSnapshot
             session_logging.py    - audit trail of the network session lifecycle
  view/      app_loop.py            - the shared window/render loop both GUIs run
             game_screen.py         - the board screen (rendering + click handling), session-agnostic
             screen_manager.py      - Screen registry + bus-driven transitions between screens
             screens/               - login_screen.py, home_screen.py, room_dialog.py (online-only)
             graphics_renderer.py   - GameSnapshot -> canvas (board, pieces, overlays, banners)
             animation.py           - piece animation state/frame, derived from timestamps
             piece_assets.py        - board token -> sprite folder/frame config
             text_input.py          - a drawn (not native) text field widget
             img.py                 - the OpenCV canvas wrapper (load/resize/alpha-blend/show)
             renderer.py            - snapshot -> plain text rendering (main.py's text mode)
tests/     test_*.py              - unit tests (pytest)
```

## Layers and responsibilities

The engine is a thin coordinator; each real responsibility lives in its own
layer, so each is testable in isolation and a new rule/feature extends one
layer without touching the others:

- **Model** (`board/`) - one internal `Board` (logical occupancy only); input
  formats are converted into it by adapters in `board/loaders.py`.
- **Movement rules** (`rules/piece_rules.py` + `rule_registry.py`) - legal
  destinations per piece kind (Strategy pattern).
- **RuleEngine** (`rules/rule_engine.py`) - read-only validation of a requested
  move, returning a stable `Reason` code.
- **RealTimeArbiter** (`realtime/`) - all motion over simulated time: active
  moves/jumps, arrival timing, capture and interception; reports `ArrivalEvent`s.
- **GameEngine** (`game/engine.py`) - application-service coordinator and public
  command boundary; owns the game-over guard and one-motion-at-a-time policy.
- **Server** (`server/`) - a small distributed system, not one process: the
  WS Gateway (`ws_server.py`) holds every real socket and forwards commands
  over NATS to whichever Game Shard (`shard.py`) hosts that room; the
  Matchmaker (`matchmaker_service.py`) and Allocator (`allocator_service.py`)
  decide who plays whom and which Shard replica a new room lands on; the
  REST API Gateway (`api_gateway.py`) handles login. All of them share Redis
  (presence/routing/session state) and Postgres (accounts) - see
  `Server_Design.md` for the full topology. Authentication, matchmaking,
  rooms with seats/viewers, disconnect grace periods, and Elo are all built
  on the exact same `GameEngine` the offline path uses - the server never
  has its own game logic, only one `Room` per match, owned by whichever
  Shard replica currently hosts it.
- **Session** (`client/session/`) - `GameSession` is the one interface every
  screen talks to instead of `GameEngine` or a network client directly, so
  the same UI works identically offline (`LocalGameSession`) or online
  (`NetworkGameSession`).
- **Controller / BoardMapper** (`game/controller.py`, `game/board_mapper.py`) -
  translate pixels to cells and own selection state.
- **View** (`client/view/`) - renders a read-only `GameSnapshot`
  (`game/snapshot.py`), never the live board; `client/view/screens/` adds
  the login/home/room-dialog flow the online path needs on top of the same
  board screen.
- **Client** (`client/`) - `session/` + `view/`, everything that runs on
  the player's machine. `server/` never imports from `client/`.

## Running

```
pip install -r requirements.txt
```

**Text mode** (a board + a script of commands from stdin):
```
python main.py < some_script.txt
```

**Offline GUI** (hotseat, no server):
```
python main_gui.py
```

**Online**: the server is a small distributed system (WS Gateway, REST API
Gateway, Game Shard, Matchmaker, Allocator, backed by Postgres/Redis/NATS -
see `Server_Design.md` for the full topology). Easiest way to run it all
locally:
```
docker compose up
```
then one `main_online.py` per player:
```
python main_online.py
```
`main_online.py` connects to `ws://localhost:8765` (the WS Gateway) and
`http://localhost:8080` (the REST API Gateway) by default (see
`main_online.py`'s `DEFAULT_SERVER_URL`/`DEFAULT_API_GATEWAY_URL`).

## How the 4 requirements are addressed

1. **Supporting other board formats** - game logic works with a single
   internal `Board` (`board/board.py`). Support for a new *input* format is
   added at the boundary, not by subclassing the board: a loader in
   `board/loaders.py` converts the external format into a `Board`
   (`load_text_board` does this for text today; a `load_binary_board` would
   sit beside it). Adding a format means writing one loader and pointing
   `main.py` at it - no rules/engine/arbiter/view file changes. The variation
   lives where it actually is (input format), instead of forcing a storage
   abstraction the game never needs.

2. **No hardcoded rules** - each piece's movement is a `MovementStrategy`
   registered by letter in a `PieceRuleRegistry`
   (`rules/rule_registry.py`). Registering a new kind (e.g. a custom
   "Champion" piece) automatically makes it a legal board token too, since
   `board/loaders.py` derives valid tokens from the registry instead of a
   fixed string. Win conditions and promotion are likewise pluggable
   strategies (`rules/game_conditions.py`).

3. **Clean code** - one responsibility per module/class (parsing, board
   storage, movement rules, turn orchestration, rendering are all
   separate); no duplicated logic (e.g. `path_is_clear` is shared by
   Rook/Bishop/Queen); no magic numbers (all constants live in
   `config/settings.py`); the board's internal list-of-lists storage is
   private and only reachable through its public interface.

4. **Tests & DI** - `tests/` covers every module (100% line coverage).
   `GameEngine`, `Room`, and every `GameSession` take all collaborators
   (board, registry, win condition, promotion rule, config, event bus) as
   constructor/function arguments, so tests substitute fakes (see
   `tests/test_engine.py`, `tests/test_room.py`) instead of monkeypatching.

## Pawn double-step

A pawn may take a two-square opening move only from its home rank - one row
in front of its own back rank, matching standard chess (pawns start on the
2nd rank, not the 1st). Rather than store that rank as a fixed constant,
`PawnMovement` derives it from the board height: `1` for a color that moves
downward and `height - 2` for one that moves upward. The same rule therefore
holds on any board size - an 8x8 board (white's home rank is row 6) or a
4-row board (row 2) alike. Only the per-color advance direction stays
configurable, in `config.PAWN_DIRECTION`.

## Running tests

```
pip install -r requirements.txt pytest
pytest
```

## Load testing

`loadtest/run.py` simulates concurrent players logging in, matching via
PLAY, and exchanging commands against a running deployment (`docker
compose up`, or any reachable one), reporting login/matchmaking/command
round-trip latency and error counts - see `Server_Design.md`'s own
Assumptions table, which this puts real numbers behind:

```
python -m loadtest.run --players 100 --duration 30
```

## Repository

https://github.com/TamarYunger/kf-chess (see header comment in `main.py`)
