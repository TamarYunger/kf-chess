"""SQLite-backed account storage: username, salted password hash, and Elo
rating (see server/elo.py). No websockets/asyncio import - so it's
testable on its own with a plain temp-file or in-memory database.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3

DEFAULT_RATING = 1200

# PBKDF2-HMAC-SHA256 iteration count. High enough that password hashing is
# not "just for show", low enough that a test suite doing dozens of logins
# stays fast (each login costs one of these).
PBKDF2_ITERATIONS = 100_000


def _hash_password(password, salt_hex):
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex()


class AccountStore:
    """One row per username: password_hash + salt (both stored as hex
    text - sqlite3's TEXT affinity, not a BLOB, to keep the schema legible
    from a plain `sqlite3` CLI session) and the account's current Elo
    rating.

    There is no separate signup flow: a username that doesn't exist yet is
    created on its first login attempt, with whatever password it used -
    matching LoginScreen's single "Login" button doing double duty.
    """

    def __init__(self, path=":memory:"):
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "username TEXT PRIMARY KEY, "
            "password_hash TEXT NOT NULL, "
            "salt TEXT NOT NULL, "
            "rating INTEGER NOT NULL"
            ")"
        )
        self._conn.commit()

    def authenticate(self, username, password):
        """Returns (ok, rating, error). `error` (a message meant for
        LoginScreen's rejection banner) and `rating` are mutually
        exclusive - the one not relevant to the outcome is None.

        Creates the account (at DEFAULT_RATING) if `username` is new;
        otherwise checks `password` against the stored salted hash.
        """
        row = self._conn.execute(
            "SELECT password_hash, salt, rating FROM users WHERE username = ?", (username,),
        ).fetchone()

        if row is None:
            salt = secrets.token_hex(16)
            self._conn.execute(
                "INSERT INTO users (username, password_hash, salt, rating) VALUES (?, ?, ?, ?)",
                (username, _hash_password(password, salt), salt, DEFAULT_RATING),
            )
            self._conn.commit()
            return True, DEFAULT_RATING, None

        stored_hash, salt, rating = row
        if _hash_password(password, salt) != stored_hash:
            return False, None, "Invalid password"
        return True, rating, None

    def update_rating(self, username, rating):
        self._conn.execute("UPDATE users SET rating = ? WHERE username = ?", (rating, username))
        self._conn.commit()

    def get_rating(self, username):
        row = self._conn.execute("SELECT rating FROM users WHERE username = ?", (username,)).fetchone()
        return row[0] if row else None

    def close(self):
        self._conn.close()
