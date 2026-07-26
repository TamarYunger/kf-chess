"""Real sound playback for game events - what game/presentation_stub.py
has always described itself as a stand-in for ("Placeholder for a future
sound/animation layer"). Subscribed alongside that stub where the stub is
also used, not instead of it - the stub's log line is still a useful audit
trail; this one plays a short local .wav file for the same events instead.

Deliberately wired at each entry point's composition-root level
(main_gui.py, main_online.py), not inside LocalGameSession/
NetworkGameSession themselves: attaching it inside the session class would
mean every test building one - several of which do run a move to a real
landing, or end the game, to test exactly that - would also trigger a
real, audible winsound.PlaySound. Wiring it one layer up keeps the session
classes themselves unaware of sound (like they're unaware of rendering)
and confines "real OS side effect" to the two entry points that actually
want it.

Works the same for both entry points because "arrival"/"game_over" reach
this module's subscribers either way, just shaped differently at the
source: offline, GameEngine publishes a real ArrivalEvent object directly
on its own bus (attribute access, `event.captured`); online, server/room.py
forwards the same two event *names* as new discrete broadcast messages
(server/protocol.py's encode_arrival/encode_game_over) once JSON-decoded,
NetworkGameSession's own tick() already republishes every message it gets
by "type" onto this same shared bus - so the payload arrives here as a
plain dict instead (`payload["captured"]`), with nothing in
NetworkGameSession needing to change at all. `_captured_of` below is the
one place that shape difference is bridged.
"""
from __future__ import annotations

from pathlib import Path

SOUNDS_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "sounds"

MOVE_SOUND = "move.wav"
CAPTURE_SOUND = "capture.wav"
GAME_OVER_SOUND = "game_over.wav"


def attach_sound(events, sounds_dir=SOUNDS_DIR, play=None):
    """"arrival" only ever fires for a move landing, never a jump (see
    RealTimeArbiter.resolve/_resolve_jumps) - captured (see `_captured_of`)
    is None for a plain move, the captured token otherwise, the same
    distinction game/move_history.py's own "arrival" subscriber already
    relies on for the offline, object-shaped payload.

    `play` is injectable (defaulting to the real `_play`, a real OS audio
    call) the same way main_gui.py's/main_online.py's own `run_app` is -
    so a test can substitute a fake and verify which sound got requested
    for which event, without ever actually calling winsound.
    """
    play = play if play is not None else _play
    sounds_dir = Path(sounds_dir)
    events.subscribe(
        "arrival", lambda payload: play(sounds_dir / (CAPTURE_SOUND if _captured_of(payload) is not None else MOVE_SOUND))
    )
    events.subscribe("game_over", lambda payload: play(sounds_dir / GAME_OVER_SOUND))


def _captured_of(payload):
    """Offline, `payload` is GameEngine's own ArrivalEvent (attribute
    access); online, it's the same event JSON-decoded off the wire by the
    time it reaches this bus - a plain dict (see this module's own
    docstring)."""
    return payload["captured"] if isinstance(payload, dict) else payload.captured


def _play(path):  # pragma: no cover - real OS audio playback, see view/img.py's own window methods
    import winsound  # Windows-only stdlib module - imported here, not at module load,
    # so this module stays importable (and testable) on any platform; only
    # actually calling _play (Windows-only, since this game is Windows-only
    # today per view/img.py's own cv2 window usage) needs it to exist.
    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
