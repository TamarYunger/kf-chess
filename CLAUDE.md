# KungFu Chess — project notes for Claude Code

Real-time chess variant (no turns — every piece moves/jumps independently,
with a delay before it lands). Three ways to run it, three composition
roots, one shared core underneath. Full per-file/per-line reference doc:
see "Code reference artifact" below before re-deriving explanations from
scratch.

## Entry points

- `main.py` — text-mode batch CLI (script of click/jump/wait/print commands
  read from stdin). No GUI, no network.
- `main_gui.py` — offline GUI ("Play Offline"): `LocalGameSession` wired
  straight into `GameScreen`.
- `main_online.py` — online GUI: LOGIN → HOME → PLAY/ROOM → GAME, wired to
  `NetworkGameSession` talking to `server/ws_server.py` over WebSocket.

`main_gui.py`/`main_online.py` share `client/view/app_loop.py`'s
window/render loop and the same `GameScreen` — they differ only in which
`GameSession` (`client/session/`) and which screens they build. Neither is
a "mode flag" on the other; each is its own independent script.

## Layered architecture

- **Model** — `board/`, `rules/`, `realtime/`, `game/models.py`,
  `game/snapshot.py`. Pure state + domain rules, no orchestration, no I/O.
- **Application** — `game/engine.py` (`GameEngine`, self-described as
  "Application-service coordinator"), `game/controller.py`,
  `game/move_history.py`, `server/` (the multiplayer lobby/room layer),
  `client/session/` (the `GameSession` bridge between Application and
  Presentation).
- **Presentation** — `client/view/` (rendering, screens, input). Never
  imports `game`/`rules`/`realtime` directly — only talks to `GameSession`
  and `GameSnapshot`.
- Entry points (`main*.py`) are composition roots, not a layer — they only
  wire the other three together.
- `client/` = `session/` + `view/`, everything that runs on the player's
  machine. `server/` never imports from `client/`.

## Conventions worth knowing before touching this repo

- **100% line coverage is the current baseline** (`.coveragerc` excludes
  only genuinely untestable OS-boundary lines via `# pragma: no cover`:
  `if __name__ == "__main__":` blocks, `client/view/img.py`'s real cv2
  window calls, `client/view/app_loop.py`'s `run_app`,
  `client/view/sound.py`'s `_play`). Keep it there — write a real test
  before reaching for pragma.
- **Never wire real sound (`client/view/sound.py`'s `attach_sound`) inside
  `LocalGameSession`/`NetworkGameSession` themselves** — several tests
  drive a real move to landing or a real game-over on purpose, and that
  would trigger a real, audible `winsound.PlaySound`. It's wired one layer
  up, in `main_gui.py`/`main_online.py`'s own `build_session`, where tests
  never reach it. `attach_sound`'s `play` param is injectable for the same
  reason `run_app` is.
- **`server/room.py`'s `_pending_events` queue+flush** exists because
  `GameEngine`'s event bus (`bus/event_bus.py`) calls subscribers
  *synchronously* — a handler can't `await` a network send. `_on_arrival`/
  `_on_game_over_for_clients` only queue; `tick()`/`handle_command()` are
  the only two places that flush (this is the "Domain Events" pattern — if
  a new engine-touching method is ever added to `Room`, it must also flush,
  or messages go silently missing).
- **Wire protocol is asymmetric on purpose**: client→server commands are
  plain text ("MOVE e2 e4"), server→client messages are JSON. Matches the
  original spec's own example ("Sending commands (WQe2e5)") and lets you
  test by hand over a raw socket. Don't "fix" this into JSON-both-ways.
- **`board/notation.py`**, not `client/view/notation.py` — moved there
  specifically so `server/protocol.py` never depends on the view/client
  layer (server should never import from `client/`).
- Tests are flat in `tests/` regardless of which package they cover (no
  mirrored subfolder structure) — follow that when adding new test files.

## Code reference artifact

A full per-file, per-function walkthrough (every file's responsibility,
every non-trivial function explained, plus a full `main_online.py`
call-flow trace from `if __name__` through a complete networked move
round-trip) was published as a Claude Artifact for code-review prep:
https://claude.ai/code/artifact/80a36529-ddfd-4ad1-a0e3-592a56f4d31f

If asked to explain the codebase file-by-file again, or to refresh that
artifact after a significant change, republish to the **same URL** by
passing it as `url` to the Artifact tool (see the artifact-design skill) —
don't mint a new one unless the user asks for a fresh doc. It now covers
full startup + call-flow traces for **all three entry points**
(`main_online.py`'s move round-trip, LOGIN, PLAY/matchmaking, ROOM
CREATE/JOIN incl. a viewer, disconnect/reconnect + auto-resign;
`main_gui.py`'s offline startup + in-process click round-trip; `main.py`'s
text-mode startup + command dispatch), plus every file's responsibility
including `bus/event_types.py` and `server/room.py`'s `_call_engine`. It
doesn't cover the test suite itself — extend it there if asked for full
coverage of that too.
