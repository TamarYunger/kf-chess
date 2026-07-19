# KungFu Chess

Real-time variant of chess: moves and jumps resolve after a delay instead
of instantly, and a "jump" onto a square can intercept an incoming enemy
move.

## Project layout

```
config/    settings.py            - all constants (timing, colors, pawn config)
board/     board.py               - Board, the single internal representation
           loaders.py             - input-format adapters: text -> Board (add binary/FEN here)
rules/     movement_strategy.py   - MovementStrategy interface + MoveContext
           piece_rules.py         - King/Queen/Rook/Bishop/Knight/Pawn strategies
           rule_registry.py       - PieceRuleRegistry (Registry/Factory pattern)
           rule_engine.py         - RuleEngine (read-only move validation) + MoveValidation
           game_conditions.py     - WinCondition / PromotionRule strategies
realtime/  models.py              - Move / Jump in-flight motion objects
           real_time_arbiter.py   - RealTimeArbiter (clock, arrivals, interception) + ArrivalEvent
game/      models.py              - MoveResult + Reason (engine command-boundary result)
           parser.py              - splits the command script into board/commands sections
           board_mapper.py        - BoardMapper (pixel -> cell)
           controller.py          - Controller (selection state + click/jump dispatch)
           engine.py              - GameEngine (application-service coordinator)
           snapshot.py            - GameSnapshot (read-only view model, owned by the engine)
view/      renderer.py            - snapshot -> text rendering
tests/     test_*.py              - unit tests (pytest)
main.py    entry point + dependency wiring
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
- **Controller / BoardMapper** (`game/controller.py`, `game/board_mapper.py`) -
  translate pixels to cells and own selection state.
- **View** (`view/`) - renders a read-only `GameSnapshot` (`game/snapshot.py`), never the live board.

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

4. **Tests & DI** - `tests/` covers every module. `GameEngine` and `main.run`
   take all collaborators (board, registry, win condition, promotion rule,
   config) as constructor/function arguments, so tests substitute fakes
   (see `tests/test_engine.py`) instead of monkeypatching.

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
pip install pytest
pytest
```

## Repository

https://github.com/TamarYunger/kf-chess (see header comment in `main.py`)
