# Graphics UI + Animations - Summary of Changes

## New files

| File | Purpose |
|---|---|
| `assets/board.png` | Board background (copied from the KamaTechOrg/CTD26 asset pack). |
| `assets/pieces/<KIND><COLOR>/states/{idle,move,jump,short_rest,long_rest}/...` | Sprite frames + `config.json` per piece/state, copied from that repo's `pieces2` skin. |
| `view/img.py` | The reference repo's `Img` OpenCV wrapper (load/resize/alpha-blend/show), copied as-is - the only UI "library" used, on top of `opencv-python`. |
| `view/piece_assets.py` | Maps a board token (`"wP"`) to its asset folder (`"PW"`); loads `config.json` (fps/loop/next_state) and discovers frame counts from disk. |
| `view/animation.py` | Pure animation state machine: which state/frame a piece should show and where, derived entirely from timestamps (no stored per-piece state). |
| `view/graphics_renderer.py` | Renders a `GameSnapshot` onto a cv2/numpy canvas - board, pieces, selection highlight, rest-cooldown overlay, game-over banner. |
| `main_gui.py` | New interactive entry point: opens a window, wires the same game objects as `main.py`, runs a wall-clock loop, maps mouse input. |
| `requirements.txt` | `opencv-python`. |
| `tests/test_animation.py`, `tests/test_piece_assets.py`, `tests/test_graphics_renderer.py` | New unit tests for the above. |

## Changes to existing files

- **`config/settings.py`**: added `ASSETS_DIR`, `SHORT_REST_DURATION` / `LONG_REST_DURATION` (fallback values for text-mode/tests), and flipped `ALLOW_CONCURRENT_MOVES` to `True` (see "Design/rule changes" below).
- **`realtime/models.py`**: added `Arrival` (piece, cell, timestamp, kind) - the one fact about a landing that can't be derived from anything else.
- **`realtime/real_time_arbiter.py`**: records an `Arrival` when a move/jump settles; added read-only `active_moves`, `active_jumps`, `recent_arrivals`, and `is_resting(cell)`.
- **`view/snapshot.py`**: `GameSnapshot` gained `moves`, `jumps`, `recent_arrivals`, `clock`, `winner` (all defaulted - existing callers unaffected).
- **`game/engine.py`**: `snapshot()` now fills those fields from the arbiter; `is_busy()` now also checks `is_resting()`; tracks and exposes `winner` (the color whose piece survived) whenever `game_over` becomes true.
- **`tests/test_snapshot.py`, `tests/test_real_time_arbiter.py`, `tests/test_engine.py`**: extended with coverage for all of the above.

`main.py` (the text-mode CLI) and its tests were never touched - everything here is additive.

## Did this change the game's design/rules?

Yes, two real rule changes (not just rendering):

1. **New cooldown rule.** Before this work, a piece could act again the instant it landed. Now `is_resting()` blocks a piece from starting a new move/jump for a real, enforced period after landing (not just a visual animation) - `LONG_REST_DURATION` after a move, `SHORT_REST_DURATION` after a jump. In the graphical game these are synced to the actual rest-sprite playback length (~833ms / ~625ms with the current skin); in text-mode/tests they use the static fallback (3000ms / 1000ms).
2. **Concurrent moves restored.** `ALLOW_CONCURRENT_MOVES` was `False`, which blocked *any* second move anywhere on the board while one was in flight - regardless of color. That's not how KungFu Chess is meant to work (no turns; every piece acts independently), and its own code comment ("set True to *re-enable* concurrent moves") suggests it was the original intended default. Flipped to `True`: now any number of pieces, either color, can be moving at once - the only limit is a piece's own busy/resting state.

Everything else (assets, animation state machine, renderer, `main_gui.py`, the rest-cooldown color overlay, the game-over banner) is new UI, not a change to prior behavior.

## Session 2: game-over banner

- **`game/engine.py`**: new `winner` property - set alongside `game_over` in `_apply_events`, derived as "the color that isn't the captured piece's color" (works for the two-color setup this project supports; not a hardcoded `"w"`/`"b"` check, it reads `config.COLORS`).
- **`view/snapshot.py`**: `GameSnapshot` gained `winner` (defaulted `None`).
- **`view/graphics_renderer.py`**: `_draw_game_over_banner` - dims the whole board and draws "GAME OVER" / "<COLOR> WINS" centered, drawn once `snapshot.game_over` is true (still just rendering an existing snapshot field - no engine/rules change beyond exposing `winner`).
- New tests in `tests/test_engine.py` (winner tracking for both colors), `tests/test_snapshot.py` (field default/passthrough), and `tests/test_graphics_renderer.py` (new file - asserts the banner actually dims the board and draws visible text pixels, without opening a window).

## Session 3: jump arc + a code-review fix

- **`view/animation.py`**: new `jump_height_offset(t, cell_size)` - a sine arc (0 at takeoff and landing, peaking at `JUMP_HEIGHT_FRACTION` of a cell halfway through). Wired into `compute_piece_views`'s jump branch so `y` actually moves during a jump, instead of only the in-place wobble sprite playing. Clamped so a piece jumping from the board's top row (no canvas headroom above it) is never drawn above the canvas - it simply doesn't lift, a real but minor edge case.
- **`view/graphics_renderer.py`**: `_draw_game_over_banner` now calls `canvas.put_text(...)` (the given `Img` method) instead of `cv2.putText` directly - `canvas` is already an `Img`, so there was no reason to bypass its own wrapper for this one call. No behavior change (same underlying `cv2.putText`/`cv2.LINE_AA` call either way).
- New tests in `tests/test_animation.py`: takeoff has no lift yet, mid-air is lifted and lands back flat, and a top-row jump never gets a negative `y`.

## Worth improving next

- **Top-row jumps don't visually lift.** No canvas space exists above the board to show it without either clipping or adding a margin (which would also require adjusting click-to-cell mapping). Flagged to the user, not fixed without confirming it's wanted.
- **Text-mode/GUI rest-duration mismatch.** `main.py` and the tests use the static fallback (1000/3000ms); only `main_gui.py` syncs to the real sprite duration (625/833ms). Harmless today (text mode has no visuals to sync to), but worth a comment or a shared constant if the two ever need to agree.
- **No visual distinction between the two rest kinds.** The cooldown overlay is the same amber color whether a piece just moved or just jumped, even though they have different durations. A second color (or the overlay's own hue) could make that distinction readable at a glance.
- **`build_game` duplicates `main.run`'s wiring** (~15 lines) rather than sharing it, done deliberately to keep zero risk to the tested CLI path. If a third entry point ever appears, that wiring is worth extracting into `game/wiring.py`.
- **No illegal-move feedback.** Clicking an invalid destination silently clears the selection; a brief flash or message would make that failure legible instead of looking like nothing happened.
- **The GUI loop doesn't stop or block input once the game is over** - the banner shows, but you can still click around (the engine already rejects those with `Reason.GAME_OVER`, so nothing breaks, it's just not obviously "done" beyond the banner). Could freeze the loop or show a "press any key to close" prompt.
