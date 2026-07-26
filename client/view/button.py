"""A drawn (not native) rectangular button - centered label, filled
background - shared by every screen that draws one (HomeScreen's Play/Room,
LoginScreen's Login, RoomDialog's Create/Join/Cancel), instead of each
re-implementing its own draw-a-filled-rect-plus-centered-text and
is-this-point-inside-it pair.
"""
from __future__ import annotations

FILLED = -1  # cv2.FILLED, drawn ourselves rather than a native widget

DEFAULT_TEXT_COLOR = (255, 255, 255, 255)  # BGRA white
DEFAULT_FONT_SCALE = 0.7
DEFAULT_THICKNESS = 2


class Button:
    def __init__(self, x, y, width, height, label, color,
                 text_color=DEFAULT_TEXT_COLOR, font_scale=DEFAULT_FONT_SCALE, thickness=DEFAULT_THICKNESS):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.label = label
        self.color = color
        self.text_color = text_color
        self.font_scale = font_scale
        self.thickness = thickness

    def contains(self, x, y):
        return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height

    def draw(self, canvas):
        canvas.rectangle((self.x, self.y), (self.x + self.width, self.y + self.height), self.color, FILLED)
        text_w, text_h = canvas.text_size(self.label, self.font_scale, self.thickness)
        text_x = self.x + (self.width - text_w) // 2
        text_y = self.y + (self.height + text_h) // 2
        canvas.put_text(self.label, text_x, text_y, self.font_scale, self.text_color, self.thickness)
