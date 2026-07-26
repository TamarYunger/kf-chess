"""A connection can disconnect between being read and actually being sent
to - that race is not the caller's problem to raise about, so both
server.room.Room and server.ws_server.GameServer send through this instead
of a bare `connection.send(...)`; whichever one owns that connection's
lifecycle (Room.handle_disconnect, GameServer.handle_connection's own loop
ending) is what removes it from its own tracked set.
"""
from __future__ import annotations

import websockets.exceptions


async def safe_send(connection, message):
    try:
        await connection.send(message)
    except websockets.exceptions.ConnectionClosed:
        pass
