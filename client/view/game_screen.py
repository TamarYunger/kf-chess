from __future__ import annotations

import time
from types import ModuleType
from typing import TYPE_CHECKING

from bus.event_types import (
    CLICK, JUMP, OPPONENT_DISCONNECTED, OPPONENT_RECONNECTED, RESIGN, ROOM, ROOM_STARTED, VIEWER,
    WAITING_FOR_OPPONENT,
)
from client.view.graphics_renderer import COLOR_NAMES, GraphicsRenderer, SIDE_PANEL_WIDTH, draw_centered_banner
from client.view.img import Img
from client.view.screen_manager import Screen

if TYPE_CHECKING:
    from bus.event_bus import EventBus
    from client.session.game_session import GameSession
    from game.snapshot import GameSnapshot

CONNECTING_TEXT = "Connecting to server..."
CONNECTING_TEXT_COLOR = (230, 230, 230, 255)  # BGRA near-white
CONNECTING_BG_COLOR = (30, 30, 30, 255)  # BGRA near-black
CONNECTING_FONT_SCALE = 0.8

# Board size assumed only for the placeholder shown before any snapshot has
# arrived - purely cosmetic (window size while "Connecting..." is on
# screen); the real board dimensions come from the first snapshot and
# GraphicsRenderer sizes its own canvas from those, same as before.
DEFAULT_BOARD_SIZE = 8

DISCONNECT_LINE_1 = "Opponent disconnected"
DISCONNECT_FONT_SCALE_1 = 0.9
DISCONNECT_FONT_SCALE_2 = 0.7
DISCONNECT_THICKNESS = 2

WAITING_LINE_1 = "Waiting for opponent..."
WAITING_FONT_SCALE_1 = 0.9
WAITING_THICKNESS = 2

ROOM_HEADER_COLOR = (0, 215, 255, 255)  # BGRA amber, matches HomeScreen/LoginScreen's title color
ROOM_HEADER_FONT_SCALE = 0.5
ROOM_HEADER_X = 8
ROOM_HEADER_Y = 18

RESIGN_CAPTION_COLOR = (200, 200, 200, 255)  # BGRA light gray, secondary to the amber room header
RESIGN_CAPTION_FONT_SCALE = 0.5
RESIGN_CAPTION_X = 8
RESIGN_CAPTION_Y = 36  # one line below ROOM_HEADER_Y, same left margin


class GameScreen(Screen):
    """The board screen: renders whatever GameSnapshot its GameSession
    currently has, and turns clicks/double-clicks into commands submitted
    through that same session - it never knows or cares whether the
    session is local (LocalGameSession) or networked (NetworkGameSession).

    GraphicsRenderer's own contract - snapshot in, canvas out - is
    untouched; this screen just copies its output into the canvas
    ScreenManager handed this screen (see Screen.render), then layers
    either a "waiting for a second player" overlay (a fresh ROOM CREATE's
    creator, alone until "room_started" arrives - see
    "waiting_for_opponent" below) or a disconnect-countdown overlay on top
    when relevant (see "opponent_disconnected"/"opponent_reconnected"
    below) - both styled after GraphicsRenderer's own game-over banner,
    the same pattern view/screens/home_screen.py's "Searching..." overlay
    reuses. A "resign" caption (see server/protocol.py's own docstring:
    broadcast right before "game_over" on an auto-resign, never for a
    capture) is drawn as a small caption under the room header instead of
    folded into GraphicsRenderer's own centered banner - that banner is
    snapshot-only and already dims+centers "GAME OVER"/"X WINS" without
    knowing why the game ended; duplicating its layout here to add a third
    line would mean re-deriving its exact vertical offsets from outside
    the class that owns them.

    `events` is the same bus NetworkGameSession publishes server messages
    on (harmless to subscribe to for a LocalGameSession, which never
    publishes these - there's simply never an opponent to disconnect, or
    a room at all - both a room-id header and the viewer/seated
    distinction below are simply inert for offline play).
    """

    def __init__(
        self, config: ModuleType, session: GameSession, events: EventBus, board_x_offset: int = SIDE_PANEL_WIDTH,
    ) -> None:
        self._config = config
        self._session = session
        self._board_x_offset = board_x_offset
        self._renderer = GraphicsRenderer(config)
        self._last_snapshot: GameSnapshot | None = None
        self._disconnect_deadline: float | None = None  # wall-clock time.time(), or None if no countdown active
        self._room_id: str | None = None
        self._role: str | None = None  # a color (seated) or "viewer"; None outside a room (e.g. local play)
        self._waiting_for_opponent = False  # a fresh ROOM CREATE's creator, alone until someone joins
        self._resigned_color: str | None = None  # the color whose disconnect grace period expired, or None
        events.subscribe(OPPONENT_DISCONNECTED, self._on_opponent_disconnected)
        events.subscribe(OPPONENT_RECONNECTED, self._on_opponent_reconnected)
        events.subscribe(ROOM, self._on_room)
        events.subscribe(WAITING_FOR_OPPONENT, self._on_waiting_for_opponent)
        events.subscribe(ROOM_STARTED, self._on_room_started)
        events.subscribe(RESIGN, self._on_resign)

    def render(self, canvas: Img) -> None:
        # A pure read - view/app_loop.py's run_app is what calls
        # session.tick() once per frame, regardless of which screen is
        # current (see GameSession.tick's own docstring for why this
        # screen must not do that itself). Cached for handle_click/
        # handle_double_click, which run from the mouse callback, not
        # this per-frame call.
        self._last_snapshot = self._session.latest_snapshot()
        if self._last_snapshot is None:
            self._render_connecting(canvas)
            return
        rendered = self._renderer.render(self._last_snapshot)
        canvas.img = rendered.img
        if self._room_id is not None:
            self._draw_room_header(canvas)
        if self._resigned_color is not None and self._last_snapshot.game_over:
            self._draw_resign_caption(canvas)
        if self._waiting_for_opponent:
            self._draw_waiting_overlay(canvas)
        elif self._disconnect_deadline is not None and not self._last_snapshot.game_over:
            self._draw_disconnect_overlay(canvas)

    def handle_click(self, x: int, y: int) -> None:
        if self._role == VIEWER or self._waiting_for_opponent:
            return  # nothing to move yet - see server/room.py's own rejection too
        cell = self._pixel_to_cell(x, y)
        if cell is not None:
            self._session.submit_command({"type": CLICK, "cell": cell})

    def handle_double_click(self, x: int, y: int) -> None:
        if self._role == VIEWER or self._waiting_for_opponent:
            return
        cell = self._pixel_to_cell(x, y)
        if cell is not None:
            self._session.submit_command({"type": JUMP, "cell": cell})

    def _pixel_to_cell(self, x: int, y: int) -> tuple[int, int] | None:
        if self._last_snapshot is None:
            return None
        cell_size = self._config.CELL_SIZE
        row, col = y // cell_size, (x - self._board_x_offset) // cell_size
        if 0 <= row < self._last_snapshot.height and 0 <= col < self._last_snapshot.width:
            return row, col
        return None

    def _render_connecting(self, canvas: Img) -> None:
        cell_size = self._config.CELL_SIZE
        width = DEFAULT_BOARD_SIZE * cell_size + 2 * SIDE_PANEL_WIDTH
        height = DEFAULT_BOARD_SIZE * cell_size
        canvas.img = Img.create(width, height, color=CONNECTING_BG_COLOR).img
        text_w, text_h = canvas.text_size(CONNECTING_TEXT, CONNECTING_FONT_SCALE, 2)
        canvas.put_text(
            CONNECTING_TEXT, (width - text_w) // 2, (height + text_h) // 2,
            CONNECTING_FONT_SCALE, CONNECTING_TEXT_COLOR, 2,
        )

    # -- room-id header ---------------------------------------------------

    def _on_room(self, payload: dict) -> None:
        self._room_id = payload["room_id"]
        self._role = payload["role"]

    def _draw_room_header(self, canvas: Img) -> None:
        text = f"Room: {self._room_id}"
        if self._role == VIEWER:
            text += " (viewing)"
        canvas.put_text(text, ROOM_HEADER_X, ROOM_HEADER_Y, ROOM_HEADER_FONT_SCALE, ROOM_HEADER_COLOR, 1)

    # -- auto-resign caption ----------------------------------------------

    def _on_resign(self, payload: dict) -> None:
        self._resigned_color = payload["color"]

    def _draw_resign_caption(self, canvas: Img) -> None:
        name = COLOR_NAMES.get(self._resigned_color, self._resigned_color.upper())
        canvas.put_text(
            f"{name} RESIGNED", RESIGN_CAPTION_X, RESIGN_CAPTION_Y,
            RESIGN_CAPTION_FONT_SCALE, RESIGN_CAPTION_COLOR, 1,
        )

    # -- waiting for a second player to join a fresh room ----------------

    def _on_waiting_for_opponent(self, payload: object) -> None:
        self._waiting_for_opponent = True

    def _on_room_started(self, payload: object) -> None:
        self._waiting_for_opponent = False

    def _draw_waiting_overlay(self, canvas: Img) -> None:
        draw_centered_banner(canvas, [(WAITING_LINE_1, WAITING_FONT_SCALE_1, WAITING_THICKNESS)])

    # -- opponent disconnect countdown ----------------------------------

    def _on_opponent_disconnected(self, payload: dict) -> None:
        self._disconnect_deadline = time.time() + payload["grace_period_seconds"]

    def _on_opponent_reconnected(self, payload: object) -> None:
        self._disconnect_deadline = None

    def _draw_disconnect_overlay(self, canvas: Img) -> None:
        remaining_seconds = max(0, int(self._disconnect_deadline - time.time()))
        draw_centered_banner(canvas, [
            (DISCONNECT_LINE_1, DISCONNECT_FONT_SCALE_1, DISCONNECT_THICKNESS),
            (f"Auto-resign in {remaining_seconds}s", DISCONNECT_FONT_SCALE_2, DISCONNECT_THICKNESS),
        ])
