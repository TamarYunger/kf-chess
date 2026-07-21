"""Pure Elo rating update - no DB, no GameEngine, no I/O, so it's testable
in complete isolation from the rest of the server.
"""
from __future__ import annotations

K_FACTOR = 32


def expected_score(rating_a, rating_b):
    """The probability the standard Elo model assigns to `a` beating `b`,
    from 0 (certain loss) to 1 (certain win) - 0.5 when ratings are equal."""
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def update_ratings(rating_a, rating_b, score_a):
    """(rating_a, rating_b, score_a) -> (new_rating_a, new_rating_b).

    `score_a` is the actual outcome for `a`: 1.0 for a win, 0.0 for a loss,
    0.5 for a draw (`b`'s score is always `1 - score_a`). Both returned
    ratings are rounded to the nearest integer - ratings are always whole
    numbers in this project (see server/db.py's DEFAULT_RATING).
    """
    if not 0.0 <= score_a <= 1.0:
        raise ValueError(f"score_a must be between 0 and 1, got {score_a!r}")

    expected_a = expected_score(rating_a, rating_b)
    expected_b = 1 - expected_a
    score_b = 1 - score_a

    new_a = rating_a + K_FACTOR * (score_a - expected_a)
    new_b = rating_b + K_FACTOR * (score_b - expected_b)
    return round(new_a), round(new_b)
