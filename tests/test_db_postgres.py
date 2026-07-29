"""Same behavioral contract as tests/test_db.py's AccountStore tests, but
against PostgresAccountStore - the store server/ws_server.py's main() picks
when DB_BACKEND=postgres. Needs a real, reachable Postgres (POSTGRES_*
env vars below, matching docker-compose.yml's postgres service by
default); see .github/workflows/tests.yml for how CI starts one on the
Windows runner's pre-installed PostgreSQL service.
"""
import os
import threading

import psycopg2.extensions
import pytest

from server.db import DEFAULT_RATING, PostgresAccountStore


def _dsn():
    return (
        f"host={os.environ.get('POSTGRES_HOST', 'localhost')} "
        f"port={os.environ.get('POSTGRES_PORT', '5432')} "
        f"dbname={os.environ.get('POSTGRES_DB', 'kfchess')} "
        f"user={os.environ.get('POSTGRES_USER', 'kfchess')} "
        f"password={os.environ.get('POSTGRES_PASSWORD', 'kfchess')}"
    )


@pytest.fixture
def store():
    account_store = PostgresAccountStore(_dsn())
    with account_store._conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE users")
    account_store._conn.commit()
    yield account_store
    account_store.close()


def test_first_login_creates_the_account_at_the_default_rating(store):
    ok, rating, error = store.authenticate("alice", "secret123")

    assert ok is True
    assert rating == DEFAULT_RATING
    assert error is None


def test_correct_password_on_an_existing_account_succeeds(store):
    store.authenticate("alice", "secret123")

    ok, rating, error = store.authenticate("alice", "secret123")

    assert ok is True
    assert rating == DEFAULT_RATING
    assert error is None


def test_wrong_password_on_an_existing_account_is_rejected(store):
    store.authenticate("alice", "secret123")

    ok, rating, error = store.authenticate("alice", "wrong-password")

    assert ok is False
    assert rating is None
    assert error is not None


def test_update_rating_persists_and_is_returned_by_future_logins(store):
    store.authenticate("alice", "secret123")

    store.update_rating("alice", 1264)

    ok, rating, error = store.authenticate("alice", "secret123")
    assert rating == 1264
    assert store.get_rating("alice") == 1264


def test_get_rating_for_an_unknown_username_returns_none(store):
    assert store.get_rating("nobody") is None


def test_authenticate_does_not_leave_an_open_transaction_for_a_brand_new_user(store):
    # A long-lived process (server/api_gateway.py's main() holds one
    # PostgresAccountStore/connection for its whole lifetime) must not
    # leave this connection "idle in transaction" between requests - that
    # blocks unrelated things sharing the same tables (e.g. this very
    # fixture's own TRUNCATE, next time it runs) until something else
    # eventually reuses the connection. Covers the new-user path's own
    # race-check SELECT (after the INSERT), not just the existing-user
    # path below.
    store.authenticate("alice", "secret123")  # first-ever login for this username

    assert store._conn.get_transaction_status() == psycopg2.extensions.TRANSACTION_STATUS_IDLE


def test_authenticate_does_not_leave_an_open_transaction_for_an_existing_user(store):
    store.authenticate("alice", "secret123")  # creates the account

    store.authenticate("alice", "secret123")  # existing-user path

    assert store._conn.get_transaction_status() == psycopg2.extensions.TRANSACTION_STATUS_IDLE


def test_authenticate_does_not_leave_an_open_transaction_after_a_wrong_password(store):
    store.authenticate("alice", "secret123")

    store.authenticate("alice", "wrong-password")

    assert store._conn.get_transaction_status() == psycopg2.extensions.TRANSACTION_STATUS_IDLE


def test_get_rating_does_not_leave_an_open_transaction(store):
    store.authenticate("alice", "secret123")

    store.get_rating("alice")

    assert store._conn.get_transaction_status() == psycopg2.extensions.TRANSACTION_STATUS_IDLE


def test_two_different_usernames_are_independent_accounts(store):
    store.authenticate("alice", "alice-pw")
    store.authenticate("bob", "bob-pw")
    store.update_rating("alice", 1500)

    assert store.get_rating("alice") == 1500
    assert store.get_rating("bob") == DEFAULT_RATING


def test_passwords_are_not_stored_in_plaintext(store):
    store.authenticate("alice", "super-secret-password")

    with store._conn.cursor() as cur:
        cur.execute("SELECT password_hash, salt FROM users WHERE username = %s", ("alice",))
        password_hash, salt = cur.fetchone()

    assert "super-secret-password" not in password_hash
    assert password_hash != "super-secret-password"
    assert len(salt) > 0


def test_concurrent_first_login_race_is_resolved_to_a_single_winner(store):
    """Two Game Server Shards racing to create the same brand-new username
    at the same moment - this is the scenario SQLite's AccountStore never
    has to handle (one process, no race possible), and exactly the reason
    authenticate() uses ON CONFLICT DO NOTHING instead of a plain INSERT
    (see PostgresAccountStore.authenticate). Each racer needs its own
    connection - a single psycopg2 connection isn't safe to drive from two
    threads at once, so `store` (the fixture's connection) only sets up
    the empty table; it isn't one of the two racing connections.
    """
    racer_a = PostgresAccountStore(_dsn())
    racer_b = PostgresAccountStore(_dsn())
    results = {}

    def attempt(racer, password, key):
        results[key] = racer.authenticate("racer", password)

    thread_a = threading.Thread(target=attempt, args=(racer_a, "password-a", "a"))
    thread_b = threading.Thread(target=attempt, args=(racer_b, "password-b", "b"))
    thread_a.start()
    thread_b.start()
    thread_a.join()
    thread_b.join()
    racer_a.close()
    racer_b.close()

    # Whichever racer's INSERT actually committed first "wins" the
    # username - its own password matches, ok=True. The loser isn't a
    # crash or a corrupted row; it's correctly told "Invalid password",
    # the same as anyone else trying that username with the wrong
    # password now would be. Exactly one winner, never both, never
    # neither.
    ok_a, _, error_a = results["a"]
    ok_b, _, error_b = results["b"]
    assert ok_a != ok_b
    assert error_a == "Invalid password" or error_b == "Invalid password"


def test_concurrent_first_login_race_with_the_same_password_both_succeed(store):
    """Same race as above, but both racers happen to use the identical
    password for the brand-new username (e.g. the same person's login
    retried and landing on two shards at once) - here the race's loser
    isn't wrong, their password matches whatever actually got stored, so
    both must come back ok=True (the case authenticate()'s final `return
    True, rating, None` - not the "someone else won" rejection - exists
    for)."""
    racer_a = PostgresAccountStore(_dsn())
    racer_b = PostgresAccountStore(_dsn())
    results = {}

    def attempt(racer, key):
        results[key] = racer.authenticate("racer", "same-password")

    thread_a = threading.Thread(target=attempt, args=(racer_a, "a"))
    thread_b = threading.Thread(target=attempt, args=(racer_b, "b"))
    thread_a.start()
    thread_b.start()
    thread_a.join()
    thread_b.join()
    racer_a.close()
    racer_b.close()

    assert results["a"][0] is True
    assert results["b"][0] is True
