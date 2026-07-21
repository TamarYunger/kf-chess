from __future__ import annotations

from view.graphics_renderer import (
    REJECTION_BAR_ALPHA, REJECTION_BAR_COLOR, REJECTION_FONT_SCALE, REJECTION_PADDING,
    REJECTION_TEXT_COLOR, REJECTION_THICKNESS,
)
from view.img import Img
from view.screen_manager import Screen
from view.text_input import TextInput

SCREEN_WIDTH = 480
SCREEN_HEIGHT = 320
BG_COLOR = (40, 40, 40, 255)  # BGRA dark gray, matches GraphicsRenderer's side panels

TITLE_TEXT = "KungFu Chess"
TITLE_COLOR = (0, 215, 255, 255)  # BGRA amber
TITLE_FONT_SCALE = 0.9
TITLE_Y = 60

FIELD_X, FIELD_Y, FIELD_WIDTH, FIELD_HEIGHT = 90, 120, 300, 40

BUTTON_X, BUTTON_Y, BUTTON_WIDTH, BUTTON_HEIGHT = 90, 190, 300, 50
BUTTON_COLOR = (0, 130, 0, 255)  # BGRA green
BUTTON_TEXT_COLOR = (255, 255, 255, 255)  # BGRA white
BUTTON_FONT_SCALE = 0.7
BUTTON_LABEL = "Login"
BUTTON_FILLED = -1  # cv2.FILLED, drawn ourselves rather than a native widget


class LoginScreen(Screen):
    """The GUI's entry point for network play: one username TextInput, one
    drawn (not native - see BUTTON_FILLED) "Login" button.

    Submitting sends "LOGIN <username>" through the session and otherwise
    does nothing itself - ScreenManager's own bus-driven transitions (see
    main_gui.py's build_screens: transitions={"login": "GAME"}) are what
    move on to the board once the server confirms a seat, so this screen
    never needs to know what screen comes after it. Its only other job is
    showing a rejection (e.g. "Room is full") if one arrives instead -
    styled after GraphicsRenderer's existing rejection bar, so it reads as
    the same kind of feedback a rejected move already gives on the board.
    """

    def __init__(self, session, events):
        self._session = session
        self._events = events
        self._username_field = TextInput(
            FIELD_X, FIELD_Y, FIELD_WIDTH, FIELD_HEIGHT, placeholder="Username", on_submit=self._on_submit,
        )
        self._error_message = None
        events.subscribe("login_rejected", self._on_login_rejected)

    def on_enter(self):
        self._username_field.clear()
        self._username_field.focus()
        self._error_message = None

    def render(self, canvas):
        canvas.img = Img.create(SCREEN_WIDTH, SCREEN_HEIGHT, color=BG_COLOR).img
        text_w, _ = canvas.text_size(TITLE_TEXT, TITLE_FONT_SCALE, 2)
        canvas.put_text(TITLE_TEXT, (SCREEN_WIDTH - text_w) // 2, TITLE_Y, TITLE_FONT_SCALE, TITLE_COLOR, 2)

        self._username_field.render(canvas)
        self._draw_login_button(canvas)

        if self._error_message is not None:
            self._draw_error_banner(canvas, self._error_message)

    def handle_click(self, x, y):
        if self._username_field.handle_click(x, y):
            return  # the field claimed this click (and is now focused)
        if self._button_contains(x, y):
            self._submit()

    def handle_key(self, key):
        self._username_field.handle_key(key)  # Enter -> _on_submit, no-op while unfocused

    # -- internal ------------------------------------------------------

    def _on_submit(self, username):
        self._submit()

    def _submit(self):
        username = self._username_field.value.strip()
        if not username:
            return
        self._error_message = None
        self._session.submit_command(f"LOGIN {username}")

    def _button_contains(self, x, y):
        return BUTTON_X <= x <= BUTTON_X + BUTTON_WIDTH and BUTTON_Y <= y <= BUTTON_Y + BUTTON_HEIGHT

    def _draw_login_button(self, canvas):
        canvas.rectangle(
            (BUTTON_X, BUTTON_Y), (BUTTON_X + BUTTON_WIDTH, BUTTON_Y + BUTTON_HEIGHT), BUTTON_COLOR, BUTTON_FILLED,
        )
        text_w, text_h = canvas.text_size(BUTTON_LABEL, BUTTON_FONT_SCALE, 2)
        text_x = BUTTON_X + (BUTTON_WIDTH - text_w) // 2
        text_y = BUTTON_Y + (BUTTON_HEIGHT + text_h) // 2
        canvas.put_text(BUTTON_LABEL, text_x, text_y, BUTTON_FONT_SCALE, BUTTON_TEXT_COLOR, 2)

    def _on_login_rejected(self, payload):
        self._error_message = payload.get("message", "Login rejected")

    def _draw_error_banner(self, canvas, message):
        h, w = canvas.img.shape[:2]
        text_w, text_h = canvas.text_size(message, REJECTION_FONT_SCALE, REJECTION_THICKNESS)
        bar_h = text_h + 2 * REJECTION_PADDING
        top = h - bar_h
        canvas.blend_rect(top, 0, h, w, REJECTION_BAR_COLOR, REJECTION_BAR_ALPHA)
        x = (w - text_w) // 2
        y = h - REJECTION_PADDING - 2
        canvas.put_text(message, x, y, REJECTION_FONT_SCALE, REJECTION_TEXT_COLOR, REJECTION_THICKNESS)
