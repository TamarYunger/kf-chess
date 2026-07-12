# KungFu Chess

Real-time variant of chess: moves and jumps resolve after a delay instead
of instantly, and a "jump" onto a square can intercept an incoming enemy
move.

## Project layout

```
config/    settings.py            - all constants (timing, colors, pawn config)
board/     board_interface.py     - abstract BoardRepresentation
           text_board.py          - concrete text-token implementation
rules/     movement_strategy.py   - MovementStrategy interface + MoveContext
           piece_rules.py         - King/Queen/Rook/Bishop/Knight/Pawn strategies
           rule_registry.py       - PieceRuleRegistry (Registry/Factory pattern)
                      rule_engine.py         - RuleEngine (read-only move legality + reason codes)
           game_conditions.py     - WinCondition / PromotionRule strategies
realtime/  models.py              - Move / Jump value objects
           real_time_arbiter.py   - RealTimeArbiter (active motions, arrival, capture)
model/     piece.py               - PieceColor/PieceKind enums, kind_letter, PieceSnapshot
board_io/  parser.py              - input parsing + board construction
           snapshot.py            - GameSnapshot (read-only, piece-based DTO for rendering)
           board_printer.py       - BoardPrinter (GameSnapshot -> text, piece-based)
game/      models.py              - MoveResult/JumpResult value objects
           
board_mapper.py        - BoardMapper (pixel <-> cell coordinate adapter)
           controller.py          - Controller (click/jump translation, selection state)
           engine.py              - GameEngine (application-service coordinator)           
tests/     test_*.py              - unit tests (pytest)
main.py    entry point + dependency wiring
```
### Command path

Each layer only talks to the one below it, and only GameEngine sits between
Controller and RealTimeArbiter/RuleEngine:

```
click/jump -> Controller (pixel mapping, selection)
           -> GameEngine.request_move / request_jump (game-over + motion-in-progress guards)
              -> RuleEngine.validate_move (read-only legality, stable reason codes)
              -> RealTimeArbiter.start_motion / start_jump

wait -> GameEngine.wait -> RealTimeArbiter.advance_time
        (arrival: interception check, capture, promotion, king-capture reporting;
        the only place Board is ever mutated)

print -> GameEngine.render -> GameEngine.snapshot() -> BoardPrinter
         (BoardPrinter only ever sees a read-only GameSnapshot, built from
         PieceSnapshot data - never a live Board, and never a pre-built grid)
```

`RuleEngine` and `RealTimeArbiter` are both injected into `GameEngine`'s
constructor (see `main.run`), so each can be unit tested - and swapped -
independently of the others (`tests/test_rule_engine.py`,
`tests/test_real_time_arbiter.py`, `tests/test_controller.py` use fakes or
drive each layer directly instead of going through a full click/wait cycle).
## How the 4 requirements are addressed

1. **Future binary representation** - all game logic talks only to the
   `BoardRepresentation` interface (`board/board_interface.py`). The only
   concrete implementation today, `TextBoardRepresentation`, stores tokens
   like `"wK"`, but a future `BitboardRepresentation` could implement the
   same interface using integers internally without any other file
   changing.

2. **No hardcoded rules** - each piece's movement is a `MovementStrategy`
   registered by letter in a `PieceRuleRegistry`
   (`rules/rule_registry.py`). Registering a new kind (e.g. a custom
   "Champion" piece) automatically makes it a legal board token too, since
    `board_io/parser.py` derives valid tokens from the registry instead of a
   fixed string. Win conditions and promotion are likewise pluggable
   strategies (`rules/game_conditions.py`).

**Clean code** - one responsibility per module/class: pixel mapping
   (`BoardMapper`), click/selection (`Controller`), read-only legality
   (`RuleEngine`), timing/arrival/capture (`RealTimeArbiter`), coordination
   (`GameEngine`), board storage, movement rules, parsing, and rendering are
   all separate; no duplicated logic (e.g. `path_is_clear` is shared by
   Rook/Bishop/Queen); no magic numbers (all constants live in
   `config/settings.py`); the board's internal list-of-lists storage is
      private and only reachable through its public interface. `BoardPrinter
   never sees a live `Board` at all - only the read-only `GameSnapshot`
   DTO `GameEngine.snapshot()` produces, built from `PieceSnapshot`
   entries (`model/piece.py`) rather than board tokens, so rendering code
   has no way to mutate game state, or even to know the board stores
   pieces as `"wK"`-style strings internally.

4. **Tests & DI** - `tests/` covers every module. `GameEngine`, `Controller`,
   `RealTimeArbiter` and `main.run` all take their collaborators (board,
   registry, rule engine, win condition, promotion rule, config) as
   constructor/function arguments, so tests substitute fakes instead of
   monkeypatching - see `tests/test_controller.py` (fake `GameEngine`),
   `tests/test_rule_engine.py` and `tests/test_real_time_arbiter.py`
   (isolated from Controller/click handling), and `tests/test_engine.py`
   (full click-to-arrival regression coverage with real collaborators).

## Pawn double-step

A pawn may take a two-square opening move only from its home rank - one row
in front of its own back rank, matching standard chess (pawns start on the
2nd rank, not the 1st). Rather than store that rank as a fixed constant,
`PawnMovement` derives it from the board height: `1` for a color that moves
downward (one row in front of its back rank at the top) and `height - 2`
for one that moves upward (one row in front of its back rank at the
bottom). The same rule therefore holds on any board size - an 8x8 board
(white's home rank is row 6) or a 4-row board (row 2) alike. Only the
per-color advance direction stays configurable, in `config.PAWN_DIRECTION`.

## Running tests

```
pip install pytest
pytest
```

## Repository

`<insert-git-repository-url-here>` (see header comment in `main.py`)
