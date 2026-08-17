from __future__ import annotations

from typing import TYPE_CHECKING

from bus.event_types import LOGIN_REJECTED
from client.view.button import Button
from client.view.graphics_renderer import (
    REJECTION_BAR_ALPHA, REJECTION_BAR_COLOR, REJECTION_FONT_SCALE, REJECTION_PADDING,
    REJECTION_TEXT_COLOR, REJECTION_THICKNESS, draw_bottom_banner,
)
from client.view.img import Img
from client.view.screen_manager import Screen
from client.view.text_input import TextInput

if TYPE_CHECKING:
    from bus.event_bus import EventBus
    from client.session.game_session import GameSession

SCREEN_WIDTH = 480
SCREEN_HEIGHT = 340
BG_COLOR = (40, 40, 40, 255)  # BGRA dark gray, matches GraphicsRenderer's side panels

TITLE_TEXT = "KungFu Chess"
TITLE_COLOR = (0, 215, 255, 255)  # BGRA amber
TITLE_FONT_SCALE = 0.9
TITLE_Y = 50

FIELD_X, FIELD_WIDTH, FIELD_HEIGHT = 90, 300, 40
USERNAME_FIELD_Y = 100
PASSWORD_FIELD_Y = 160

BUTTON_X, BUTTON_Y, BUTTON_WIDTH, BUTTON_HEIGHT = 90, 220, 300, 50
BUTTON_COLOR = (0, 130, 0, 255)  # BGRA green
BUTTON_LABEL = "Login"


class LoginScreen(Screen):
    """The GUI's entry point for network play: username + password
    TextInputs (the password field hidden - see TextInput's own `hidden`
    mode), one drawn (not native - see view/button.py) "Login" button.

    Submitting sends {"type": "login", "username": ..., "password": ...}
    through the session and otherwise does nothing itself - the session
    is what actually turns that into a REST call to the API Gateway and
    then an AUTH over the WebSocket (see NetworkGameSession.submit_command/
    tick) - this screen doesn't know or care that split happens.
    ScreenManager's own bus-driven transitions (see main_online.py's
    build_screens: transitions={"login": "GAME"}) are what move on to the
    board once the server confirms a seat,
    so this screen never needs to know what screen comes after it. Its
    only other job is showing a rejection (wrong password, room full, ...)
    if one arrives instead - styled after GraphicsRenderer's existing
    rejection bar, so it reads as the same kind of feedback a rejected
    move already gives on the board.
    """

    def __init__(self, session: GameSession, events: EventBus) -> None:
        self._session = session
        self._events = events
        self._username_field = TextInput(
            FIELD_X, USERNAME_FIELD_Y, FIELD_WIDTH, FIELD_HEIGHT,
            placeholder="Username", on_submit=self._focus_password,
        )
        self._password_field = TextInput(
            FIELD_X, PASSWORD_FIELD_Y, FIELD_WIDTH, FIELD_HEIGHT,
            placeholder="Password", hidden=True, on_submit=self._on_submit,
        )
        self._error_message: str | None = None
        self._button = Button(BUTTON_X, BUTTON_Y, BUTTON_WIDTH, BUTTON_HEIGHT, BUTTON_LABEL, BUTTON_COLOR)
        events.subscribe(LOGIN_REJECTED, self._on_login_rejected)

    def on_enter(self) -> None:
        self._username_field.clear()
        self._password_field.clear()
        self._password_field.blur()
        self._username_field.focus()
        self._error_message = None

    def render(self, canvas: Img) -> None:
        canvas.img = Img.create(SCREEN_WIDTH, SCREEN_HEIGHT, color=BG_COLOR).img
        text_w, _ = canvas.text_size(TITLE_TEXT, TITLE_FONT_SCALE, 2)
        canvas.put_text(TITLE_TEXT, (SCREEN_WIDTH - text_w) // 2, TITLE_Y, TITLE_FONT_SCALE, TITLE_COLOR, 2)

        self._username_field.render(canvas)
        self._password_field.render(canvas)
        self._button.draw(canvas)

        if self._error_message is not None:
            self._draw_error_banner(canvas, self._error_message)

    def handle_click(self, x: int, y: int) -> None:
        # Always drive both fields, not just the one the click landed in -
        # TextInput.handle_click focuses on a hit and blurs on a miss, so a
        # click inside username must still blur password if it was focused
        # (short-circuiting after the first hit used to skip that blur,
        # leaving both fields focused and every keystroke going to both).
        self._username_field.handle_click(x, y)
        self._password_field.handle_click(x, y)
        if self._button.contains(x, y):
            self._submit()

    def handle_key(self, key: int) -> None:
        # Stop once a field actually consumes the key - not "only while
        # unfocused" as before. Enter in the username field fires
        # on_submit -> _focus_password synchronously, inside this same
        # call, which focuses the password field before we'd reach it
        # below; forwarding the same Enter into it right after would
        # submit whatever (possibly stale) password was already sitting
        # there, before the user ever typed a new one.
        if self._username_field.handle_key(key):
            return
        self._password_field.handle_key(key)

    # -- internal ------------------------------------------------------

    def _focus_password(self, _username: str) -> None:
        # Enter in the username field moves on to the password field
        # instead of submitting with whatever (possibly empty) password
        # is currently there.
        self._username_field.blur()
        self._password_field.focus()

    def _on_submit(self, _password: str) -> None:
        self._submit()

    def _submit(self) -> None:
        username = self._username_field.value.strip()
        password = self._password_field.value
        if not username or not password:
            return
        self._error_message = None
        self._session.submit_command({"type": "login", "username": username, "password": password})

    def _on_login_rejected(self, payload: dict) -> None:
        self._error_message = payload.get("message", "Login rejected")

    def _draw_error_banner(self, canvas: Img, message: str) -> None:
        draw_bottom_banner(
            canvas, message, REJECTION_FONT_SCALE, REJECTION_THICKNESS, REJECTION_PADDING,
            REJECTION_TEXT_COLOR, REJECTION_BAR_COLOR, REJECTION_BAR_ALPHA,
        )
