"""Pure matchmaking logic - no asyncio, no websockets, no GameEngine, so
it's unit-testable without any of that infrastructure (see
tests/test_matchmaking.py). server/ws_server.py owns the actual waiting
pool (a dict) and turns it into the plain sequence this expects.
"""
from __future__ import annotations

DEFAULT_RATING_RANGE = 100


def find_opponent(rating, waiting, rating_range=DEFAULT_RATING_RANGE):
    """`waiting`: a sequence of (id, rating) pairs already searching for a
    match. Returns the id of the first one within `rating_range` of
    `rating` (earliest-queued first, since callers pass `waiting` in queue
    order), or None if nobody currently waiting qualifies - the caller
    should then add this player to the pool and keep waiting.
    """
    for player_id, other_rating in waiting:
        if abs(other_rating - rating) <= rating_range:
            return player_id
    return None
