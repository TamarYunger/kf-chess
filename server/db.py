"""SQLite-backed account storage: username, salted password hash, and Elo
rating (see server/elo.py). No websockets/asyncio import - so it's
testable on its own with a plain temp-file or in-memory database.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis

DEFAULT_RATING = 1200

# PBKDF2-HMAC-SHA256 iteration count. High enough that password hashing is
# not "just for show", low enough that a test suite doing dozens of logins
# stays fast (each login costs one of these).
PBKDF2_ITERATIONS = 100_000


def _hash_password(password: str, salt_hex: str) -> str:
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

    def __init__(self, path: str = ":memory:") -> None:
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

    def authenticate(self, username: str, password: str) -> tuple[bool, int | None, str | None]:
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

    def update_rating(self, username: str, rating: int) -> None:
        self._conn.execute("UPDATE users SET rating = ? WHERE username = ?", (rating, username))
        self._conn.commit()

    def get_rating(self, username: str) -> int | None:
        row = self._conn.execute("SELECT rating FROM users WHERE username = ?", (username,)).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self._conn.close()


def build_redis_client() -> "redis.Redis":
    """The real Redis connection main() (both server/ws_server.py's and
    server/api_gateway.py's) builds for production use - the one place
    that reads REDIS_HOST/REDIS_PORT, same reasoning as PostgresAccountStore
    vs main()'s DB_BACKEND choice: a connection helper isn't a "which
    backend" decision, it's just wiring, so it lives here rather than
    duplicated in every service's own main(). Deliberately no fallback
    defaults - a service that needs Redis and doesn't have these set
    should crash immediately, not silently guess a host.

    redis.Redis() itself is lazy (it only opens a socket on the first
    actual command), so this call succeeding doesn't mean a real Redis is
    reachable - only that the parameters were present.
    """
    import redis

    return redis.Redis(host=os.environ["REDIS_HOST"], port=int(os.environ["REDIS_PORT"]))


class PostgresAccountStore:
    """Same three-method contract as AccountStore (authenticate/
    update_rating/get_rating), backed by PostgreSQL instead of a local
    SQLite file - for when more than one process needs to share the same
    account data. Still no websockets/asyncio import; the caller decides
    which of the two stores to build (see server/ws_server.py's main()),
    this class only knows how to talk to Postgres.

    Unlike SQLite, more than one process can call authenticate() for the
    same brand-new username at the same time (two players' first-ever
    login racing each other), so account creation can't just be a plain
    INSERT - see authenticate()'s comment.
    """

    def __init__(self, dsn: str) -> None:
        import psycopg2

        self._conn = psycopg2.connect(dsn)
        with self._conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS users ("
                "username TEXT PRIMARY KEY, "
                "password_hash TEXT NOT NULL, "
                "salt TEXT NOT NULL, "
                "rating INTEGER NOT NULL"
                ")"
            )
        self._conn.commit()

    def authenticate(self, username: str, password: str) -> tuple[bool, int | None, str | None]:
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash, salt, rating FROM users WHERE username = %s", (username,),
                )
                row = cur.fetchone()
                if row is not None:
                    stored_hash, salt, rating = row
                    # Read-only so far, but psycopg2's default non-autocommit
                    # mode still leaves this connection "idle in transaction"
                    # until something closes it - and this connection is
                    # long-lived (one per process, see server/api_gateway.py's
                    # main()), so every login for an existing user would
                    # otherwise leave it open indefinitely between requests.
                    self._conn.commit()
                    if _hash_password(password, salt) != stored_hash:
                        return False, None, "Invalid password"
                    return True, rating, None

                # Nobody has this username yet, as far as we saw - but another
                # shard could be creating it from a concurrent first login at
                # the same moment. ON CONFLICT DO NOTHING makes the INSERT a
                # no-op if we lost that race, instead of raising/crashing.
                salt = secrets.token_hex(16)
                password_hash = _hash_password(password, salt)
                cur.execute(
                    "INSERT INTO users (username, password_hash, salt, rating) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT (username) DO NOTHING",
                    (username, password_hash, salt, DEFAULT_RATING),
                )
                self._conn.commit()

                cur.execute(
                    "SELECT password_hash, salt, rating FROM users WHERE username = %s", (username,),
                )
                stored_hash, stored_salt, rating = cur.fetchone()
                self._conn.commit()  # read-only from here - see the existing-user branch's own comment
                if stored_hash == password_hash:
                    return True, DEFAULT_RATING, None  # our own insert won the race

                # Someone else's login created this username first - check our
                # password against what they actually stored, not what we
                # attempted to insert.
                if _hash_password(password, stored_salt) != stored_hash:
                    return False, None, "Invalid password"
                return True, rating, None
        except Exception:
            # A failed query leaves psycopg2's non-autocommit connection
            # "idle in transaction" until something rolls it back - and this
            # connection is long-lived (one per process), so every later
            # call would otherwise fail with InFailedSqlTransaction forever,
            # not just this one. Roll back so the connection stays usable,
            # then let the caller see the original failure.
            self._conn.rollback()
            raise

    def update_rating(self, username: str, rating: int) -> None:
        try:
            with self._conn.cursor() as cur:
                cur.execute("UPDATE users SET rating = %s WHERE username = %s", (rating, username))
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def get_rating(self, username: str) -> int | None:
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT rating FROM users WHERE username = %s", (username,))
                row = cur.fetchone()
                self._conn.commit()  # read-only - see authenticate()'s own comment on why this still matters
                return row[0] if row else None
        except Exception:
            self._conn.rollback()
            raise

    def close(self) -> None:
        self._conn.close()
