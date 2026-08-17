from server.db import DEFAULT_RATING, AccountStore, build_postgres_dsn, build_redis_client


def test_first_login_creates_the_account_at_the_default_rating():
    store = AccountStore()  # in-memory
    ok, rating, error = store.authenticate("alice", "secret123")

    assert ok is True
    assert rating == DEFAULT_RATING
    assert error is None


def test_correct_password_on_an_existing_account_succeeds():
    store = AccountStore()
    store.authenticate("alice", "secret123")

    ok, rating, error = store.authenticate("alice", "secret123")

    assert ok is True
    assert rating == DEFAULT_RATING
    assert error is None


def test_wrong_password_on_an_existing_account_is_rejected():
    store = AccountStore()
    store.authenticate("alice", "secret123")

    ok, rating, error = store.authenticate("alice", "wrong-password")

    assert ok is False
    assert rating is None
    assert error is not None


def test_wrong_password_does_not_change_the_stored_rating():
    store = AccountStore()
    store.authenticate("alice", "secret123")
    store.update_rating("alice", 1350)

    store.authenticate("alice", "wrong-password")

    assert store.get_rating("alice") == 1350


def test_update_rating_persists_and_is_returned_by_future_logins():
    store = AccountStore()
    store.authenticate("alice", "secret123")

    store.update_rating("alice", 1264)

    ok, rating, error = store.authenticate("alice", "secret123")
    assert rating == 1264
    assert store.get_rating("alice") == 1264


def test_get_rating_for_an_unknown_username_returns_none():
    store = AccountStore()

    assert store.get_rating("nobody") is None


def test_two_different_usernames_are_independent_accounts():
    store = AccountStore()
    store.authenticate("alice", "alice-pw")
    store.authenticate("bob", "bob-pw")
    store.update_rating("alice", 1500)

    assert store.get_rating("alice") == 1500
    assert store.get_rating("bob") == DEFAULT_RATING


def test_passwords_are_not_stored_in_plaintext():
    store = AccountStore()
    store.authenticate("alice", "super-secret-password")

    row = store._conn.execute(
        "SELECT password_hash, salt FROM users WHERE username = ?", ("alice",),
    ).fetchone()
    password_hash, salt = row

    assert "super-secret-password" not in password_hash
    assert password_hash != "super-secret-password"
    assert len(salt) > 0


def test_same_password_for_two_users_produces_different_hashes():
    # Each account gets its own random salt, so identical passwords don't
    # produce identical stored hashes (defeats a precomputed lookup table).
    store = AccountStore()
    store.authenticate("alice", "same-password")
    store.authenticate("bob", "same-password")

    row_a = store._conn.execute("SELECT password_hash FROM users WHERE username = ?", ("alice",)).fetchone()
    row_b = store._conn.execute("SELECT password_hash FROM users WHERE username = ?", ("bob",)).fetchone()

    assert row_a[0] != row_b[0]


def test_persists_across_connections_to_the_same_file(tmp_path):
    db_path = str(tmp_path / "accounts.db")

    store = AccountStore(db_path)
    store.authenticate("alice", "secret123")
    store.update_rating("alice", 1417)
    store.close()

    reopened = AccountStore(db_path)
    ok, rating, error = reopened.authenticate("alice", "secret123")
    reopened.close()

    assert ok is True
    assert rating == 1417


def test_wrong_password_still_rejected_after_reopening_the_file(tmp_path):
    db_path = str(tmp_path / "accounts.db")

    store = AccountStore(db_path)
    store.authenticate("alice", "secret123")
    store.close()

    reopened = AccountStore(db_path)
    ok, rating, error = reopened.authenticate("alice", "wrong-password")
    reopened.close()

    assert ok is False


def test_build_redis_client_uses_the_configured_host_and_port(monkeypatch):
    # redis.Redis() is lazy - it never opens a socket just from being
    # constructed - so this checks the parameters were wired through
    # correctly without needing a real Redis server reachable at all.
    monkeypatch.setenv("REDIS_HOST", "some-redis-host")
    monkeypatch.setenv("REDIS_PORT", "16379")

    client = build_redis_client()

    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["host"] == "some-redis-host"
    assert kwargs["port"] == 16379


def test_build_postgres_dsn_reads_every_expected_env_var(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "some-postgres-host")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_DB", "kfchess")
    monkeypatch.setenv("POSTGRES_USER", "kfchess_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")

    dsn = build_postgres_dsn()

    assert dsn == (
        "host=some-postgres-host port=6543 dbname=kfchess user=kfchess_user password=secret"
    )
