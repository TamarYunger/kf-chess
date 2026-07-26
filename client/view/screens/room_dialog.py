from __future__ import annotations

from client.view.button import FILLED, Button
from client.view.text_input import TextInput

# Assumes it's drawn within a 480x340 HOME canvas (view/screens/home_screen.py's
# SCREEN_WIDTH/SCREEN_HEIGHT) - not imported directly to avoid a circular
# import (home_screen.py is what imports RoomDialog, not the other way
# around).
DIALOG_X, DIALOG_Y = 70, 60
DIALOG_WIDTH, DIALOG_HEIGHT = 340, 210
DIALOG_BG_COLOR = (65, 65, 65, 255)  # BGRA - lighter than HOME's background, reads as "on top"
DIALOG_BORDER_COLOR = (0, 215, 255, 255)  # BGRA amber, matches the title color elsewhere
DIALOG_BORDER_THICKNESS = 2

TITLE_TEXT = "Room"
TITLE_FONT_SCALE = 0.7
TITLE_Y = DIALOG_Y + 30

FIELD_X = DIALOG_X + 20
FIELD_Y = DIALOG_Y + 50
FIELD_WIDTH = DIALOG_WIDTH - 40
FIELD_HEIGHT = 36

BUTTON_WIDTH = 90
BUTTON_HEIGHT = 40
BUTTON_GAP = 15
BUTTON_Y = DIALOG_Y + 110
BUTTON_FONT_SCALE = 0.55

CREATE_BUTTON_X = DIALOG_X + 20
JOIN_BUTTON_X = CREATE_BUTTON_X + BUTTON_WIDTH + BUTTON_GAP
CANCEL_BUTTON_X = JOIN_BUTTON_X + BUTTON_WIDTH + BUTTON_GAP

CREATE_COLOR = (0, 130, 0, 255)  # BGRA green
JOIN_COLOR = (150, 90, 0, 255)  # BGRA blue
CANCEL_COLOR = (90, 90, 90, 255)  # BGRA neutral gray


class RoomDialog:
    """A modal overlay HomeScreen draws on top of itself when open - not a
    separate ScreenManager screen (it isn't a full-window destination,
    just a dialog within HOME - see HomeScreen.render/handle_click routing
    everything to this first while `is_open`), the same kind of
    self-contained widget view/text_input.py's TextInput already is.

    One TextInput (room id) + three drawn buttons:
      - Create: sends "ROOM CREATE" - the server assigns a fresh room id
        and seats this connection as the first color.
      - Join: sends "ROOM JOIN <id>" using whatever's in the text field.
      - Cancel: closes the dialog - no server call at all, no state change.
    Either Create or a successful Join eventually produces a "room" event
    (server-confirmed) that ScreenManager's own transitions= wiring moves
    on to GAME with (see main_online.py) - this dialog doesn't need to know
    that happens, it only closes itself once it has sent a command.
    """

    def __init__(self, session):
        self._session = session
        self.is_open = False
        self._room_id_field = TextInput(
            FIELD_X, FIELD_Y, FIELD_WIDTH, FIELD_HEIGHT, placeholder="Room ID", on_submit=self._on_field_submit,
        )
        self._create_button = Button(
            CREATE_BUTTON_X, BUTTON_Y, BUTTON_WIDTH, BUTTON_HEIGHT, "Create", CREATE_COLOR,
            font_scale=BUTTON_FONT_SCALE,
        )
        self._join_button = Button(
            JOIN_BUTTON_X, BUTTON_Y, BUTTON_WIDTH, BUTTON_HEIGHT, "Join", JOIN_COLOR, font_scale=BUTTON_FONT_SCALE,
        )
        self._cancel_button = Button(
            CANCEL_BUTTON_X, BUTTON_Y, BUTTON_WIDTH, BUTTON_HEIGHT, "Cancel", CANCEL_COLOR,
            font_scale=BUTTON_FONT_SCALE,
        )

    def open(self):
        self.is_open = True
        self._room_id_field.clear()
        self._room_id_field.focus()

    def close(self):
        self.is_open = False
        self._room_id_field.blur()

    def render(self, canvas):
        if not self.is_open:
            return
        canvas.rectangle((DIALOG_X, DIALOG_Y), (DIALOG_X + DIALOG_WIDTH, DIALOG_Y + DIALOG_HEIGHT), DIALOG_BG_COLOR, FILLED)
        canvas.rectangle(
            (DIALOG_X, DIALOG_Y), (DIALOG_X + DIALOG_WIDTH, DIALOG_Y + DIALOG_HEIGHT),
            DIALOG_BORDER_COLOR, DIALOG_BORDER_THICKNESS,
        )
        text_w, _ = canvas.text_size(TITLE_TEXT, TITLE_FONT_SCALE, 2)
        canvas.put_text(
            TITLE_TEXT, DIALOG_X + (DIALOG_WIDTH - text_w) // 2, TITLE_Y, TITLE_FONT_SCALE, DIALOG_BORDER_COLOR, 2,
        )
        self._room_id_field.render(canvas)
        self._create_button.draw(canvas)
        self._join_button.draw(canvas)
        self._cancel_button.draw(canvas)

    def handle_click(self, x, y):
        if not self.is_open:
            return
        if self._room_id_field.handle_click(x, y):
            return
        if self._create_button.contains(x, y):
            self._create()
        elif self._join_button.contains(x, y):
            self._join()
        elif self._cancel_button.contains(x, y):
            self.close()

    def handle_key(self, key):
        if self.is_open:
            self._room_id_field.handle_key(key)  # Enter -> _on_field_submit -> _join

    # -- internal --------------------------------------------------------

    def _on_field_submit(self, _value):
        self._join()

    def _create(self):
        self._session.submit_command("ROOM CREATE")
        self.close()

    def _join(self):
        room_id = self._room_id_field.value.strip()
        if not room_id:
            return
        self._session.submit_command(f"ROOM JOIN {room_id}")
        self.close()
