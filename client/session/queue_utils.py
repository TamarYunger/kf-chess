"""Shared by every session-side class that hands messages from a background
thread to the render loop via a thread-safe queue.Queue: NetworkClient
(WebSocket) and LoginClient (the REST /login call) both drain their own
`incoming` queue once per frame, non-blocking - kept in one place instead
of each carrying its own identical drain() method.
"""
from __future__ import annotations

import queue


def drain_queue(q: queue.Queue) -> list[dict]:
    """Pops every message currently queued, without blocking."""
    messages = []
    while True:
        try:
            messages.append(q.get_nowait())
        except queue.Empty:
            break
    return messages
