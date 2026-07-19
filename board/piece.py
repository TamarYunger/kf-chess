"""Accessors for the board's piece-token convention (e.g. "wK" = white king).

Board tokens are plain 2-character strings (see board/board.py), so every
caller that needs a piece's color or kind ends up indexing into that string.
Centralizing the indexing here means the convention only has to change in
one place if it ever does (e.g. to support a "has moved" flag).
"""


def color_of(token):
    return token[0]


def kind_of(token):
    return token[1]


def make_piece(color, kind):
    return color + kind
