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
           game_conditions.py     - WinCondition / PromotionRule strategies
game/      models.py              - Move / Jump value objects
           parser.py              - input parsing + board construction
           engine.py              - GameEngine (turn orchestration)
           renderer.py            - board -> text rendering
tests/     test_*.py              - unit tests (pytest)
main.py    entry point + dependency wiring
```

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
   `game/parser.py` derives valid tokens from the registry instead of a
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

## Known open item

The original code set pawn double-step eligibility with
`start_row = 1 if color == "w" else 6`, which was flagged as uncertain in
a comment (pawns are placed on row 6 for white in the sample board, so a
double step from row 1 doesn't actually apply to them). This has been
preserved as-is in `config.PAWN_START_ROW = {"w": 1, "b": 6}` rather than
silently changed - flip the values there if white's double-step should
work from row 6 instead.

## Running tests

```
pip install pytest
pytest
```

## Repository

`<insert-git-repository-url-here>` (see header comment in `main.py`)
