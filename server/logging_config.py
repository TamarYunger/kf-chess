"""Standard-library logging setup for the server: every server/*.py module
logs through `logging.getLogger(__name__)` as usual (login attempts, room
create/join, moves, disconnects, results - see server/ws_server.py and
server/room.py) - this module just decides where those records end up
when actually running the server (server/logs/server.log - not used by
tests, which read records via pytest's own caplog instead).
"""
from __future__ import annotations

import logging
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "server.log"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_server_logging(level=logging.INFO):
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
    )
