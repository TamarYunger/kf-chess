from __future__ import annotations

# Key codes as returned by view.img.Img.wait_key (cv2.waitKey & 0xFF).
KEY_ENTER = (13, 10)
KEY_BACKSPACE = (8, 127)

BOX_COLOR_FOCUSED = (0, 215, 255, 255)  # BGRA amber
BOX_COLOR_UNFOCUSED = (150, 150, 150, 255)  # BGRA gray
BOX_THICKNESS = 2
TEXT_COLOR = (230, 230, 230, 255)  # BGRA near-white
PLACEHOLDER_COLOR = (120, 120, 120, 255)  # BGRA dim gray
FONT_SCALE = 0.6
TEXT_PADDING = 10
MASK_CHAR = "*"


class TextInput:
    """A single-line text box: focus, typed characters, Backspace/Enter,
    and an optional hidden/password mode - the shared building block every
    future login/room screen's text fields will use.

    Geometry is fixed at construction (mirrors how GraphicsRenderer's own
    `_draw_*` helpers take a cell/position, not a per-call layout), so a
    screen just creates one TextInput per field and calls
    `render`/`handle_click`/`handle_key` on it every frame.
    """

    def __init__(self, x, y, width, height, hidden=False, placeholder="",
                 max_length=64, on_submit=None):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self._hidden = hidden
        self._placeholder = placeholder
        self._max_length = max_length
        self._on_submit = on_submit
        self._value = ""
        self._focused = False

    @property
    def value(self):
        return self._value

    @property
    def focused(self):
        return self._focused

    def set_value(self, value):
        self._value = value[:self._max_length]

    def clear(self):
        self._value = ""

    def focus(self):
        self._focused = True

    def blur(self):
        self._focused = False

    def contains(self, x, y):
        return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height

    def handle_click(self, x, y):
        """Focuses if `(x, y)` landed inside the box, else blurs it. Returns
        whether the click was inside, so a screen juggling several fields
        can tell whether this field claimed the click."""
        inside = self.contains(x, y)
        if inside:
            self.focus()
        else:
            self.blur()
        return inside

    def handle_key(self, key):
        """Returns True if this field consumed `key` (only happens while
        focused) - a screen can use that to decide whether to also treat
        the key as its own shortcut (e.g. ESC to go back)."""
        if not self._focused:
            return False
        if key in KEY_ENTER:
            if self._on_submit is not None:
                self._on_submit(self._value)
            return True
        if key in KEY_BACKSPACE:
            self._value = self._value[:-1]
            return True
        if 32 <= key <= 126 and len(self._value) < self._max_length:
            self._value += chr(key)
            return True
        return False

    def render(self, canvas):
        color = BOX_COLOR_FOCUSED if self._focused else BOX_COLOR_UNFOCUSED
        canvas.rectangle((self.x, self.y), (self.x + self.width, self.y + self.height), color, BOX_THICKNESS)

        if self._value:
            text = MASK_CHAR * len(self._value) if self._hidden else self._value
            text_color = TEXT_COLOR
        else:
            text = self._placeholder
            text_color = PLACEHOLDER_COLOR

        if text:
            baseline_y = self.y + self.height - TEXT_PADDING // 2
            canvas.put_text(text, self.x + TEXT_PADDING, baseline_y, FONT_SCALE, text_color, 1)
