"""loadtest/run.py's own tests - run_player takes login/connect as
injected callables specifically so its message-handling logic can be
exercised here against fakes, without a real server reachable (see that
module's own docstring).
"""
import asyncio
import json

from loadtest.run import Metrics, random_cell, report, run_player, summarize


def run(coro):
    return asyncio.run(coro)


class FakeWebSocket:
    """Pops queued messages in order; once exhausted, recv() hangs
    (mirrors a real connection with nothing left to say) so callers'
    own asyncio.wait_for(..., timeout=...) is what actually ends the
    wait - exactly the mechanism run_player relies on for both its
    per-command timeout and its overall duration deadline."""

    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []
        self.closed = False

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        if self._messages:
            return self._messages.pop(0)
        await asyncio.sleep(1000)

    async def close(self):
        self.closed = True


def make_login(token="tok123", fail=False):
    async def login(username, password):
        if fail:
            raise RuntimeError("login failed")
        return {"token": token}
    return login


def make_connect(ws=None, fail=False):
    async def connect():
        if fail:
            raise OSError("connection refused")
        return ws
    return connect


def test_random_cell_is_always_a_valid_algebraic_square():
    for _ in range(50):
        cell = random_cell()
        assert len(cell) == 2
        assert cell[0] in "abcdefgh"
        assert cell[1] in "12345678"


def test_login_failure_is_counted_and_never_attempts_to_connect():
    async def scenario():
        metrics = Metrics()
        connect_called = False

        async def connect():
            nonlocal connect_called
            connect_called = True

        await run_player(1, make_login(fail=True), connect, duration=0.1, metrics=metrics)

        assert metrics.login_errors == 1
        assert connect_called is False

    run(scenario())


def test_connect_failure_is_counted_after_a_successful_login():
    async def scenario():
        metrics = Metrics()

        await run_player(1, make_login(), make_connect(fail=True), duration=0.1, metrics=metrics)

        assert metrics.connect_errors == 1
        assert len(metrics.login_latencies) == 1  # login itself did succeed

    run(scenario())


def test_getting_matched_records_a_match_latency_and_closes_on_exit():
    async def scenario():
        ws = FakeWebSocket([
            json.dumps({"type": "login", "payload": {}}),  # AUTH confirmation
            json.dumps({"type": "room", "payload": {"room_id": "abc123", "role": "w"}}),
        ])
        metrics = Metrics()

        await run_player(1, make_login(), make_connect(ws), duration=0.1, metrics=metrics)

        assert metrics.games_matched == 1
        assert len(metrics.match_latencies) == 1
        assert ws.sent == ["AUTH tok123", "PLAY"]
        assert ws.closed is True

    run(scenario())


def test_no_match_ends_the_session_without_counting_a_match():
    async def scenario():
        ws = FakeWebSocket([
            json.dumps({"type": "login", "payload": {}}),
            json.dumps({"type": "no_match", "payload": None}),
        ])
        metrics = Metrics()

        await run_player(1, make_login(), make_connect(ws), duration=0.1, metrics=metrics)

        assert metrics.games_matched == 0
        assert ws.closed is True

    run(scenario())


def test_a_snapshot_after_matching_sends_a_select_and_records_its_latency():
    async def scenario():
        ws = FakeWebSocket([
            json.dumps({"type": "login", "payload": {}}),
            json.dumps({"type": "room", "payload": {"room_id": "abc123", "role": "w"}}),
            json.dumps({"type": "snapshot", "payload": {}}),
            json.dumps({"type": "legal_destinations", "payload": {}}),  # the SELECT's own reply
        ])
        metrics = Metrics()

        await run_player(1, make_login(), make_connect(ws), duration=0.2, metrics=metrics, command_probability=1.0)

        assert any(sent.startswith("SELECT ") for sent in ws.sent)
        assert len(metrics.command_latencies) == 1
        assert metrics.command_timeouts == 0

    run(scenario())


def test_a_command_with_no_reply_times_out_and_is_counted():
    async def scenario():
        ws = FakeWebSocket([
            json.dumps({"type": "login", "payload": {}}),
            json.dumps({"type": "room", "payload": {"room_id": "abc123", "role": "w"}}),
            json.dumps({"type": "snapshot", "payload": {}}),
            # no reply queued for the SELECT this snapshot triggers
        ])
        metrics = Metrics()

        await run_player(
            1, make_login(), make_connect(ws), duration=0.1, metrics=metrics,
            command_probability=1.0, command_timeout=0.02,
        )

        assert metrics.command_timeouts == 1
        assert metrics.command_latencies == []

    run(scenario())


def test_a_snapshot_is_ignored_when_command_probability_is_zero():
    async def scenario():
        ws = FakeWebSocket([
            json.dumps({"type": "login", "payload": {}}),
            json.dumps({"type": "room", "payload": {"room_id": "abc123", "role": "w"}}),
            json.dumps({"type": "snapshot", "payload": {}}),
        ])
        metrics = Metrics()

        await run_player(1, make_login(), make_connect(ws), duration=0.1, metrics=metrics, command_probability=0.0)

        assert not any(sent.startswith("SELECT ") for sent in ws.sent)
        assert metrics.command_latencies == []

    run(scenario())


def test_zero_duration_ends_the_session_before_receiving_anything():
    async def scenario():
        ws = FakeWebSocket([
            json.dumps({"type": "login", "payload": {}}),
        ])
        metrics = Metrics()

        await run_player(1, make_login(), make_connect(ws), duration=0.0, metrics=metrics)

        assert metrics.games_matched == 0
        assert ws.closed is True

    run(scenario())


def test_summarize_reports_no_samples_for_an_empty_list():
    assert summarize("thing", []) == "thing: no samples"


def test_summarize_reports_mean_percentiles_and_max_in_milliseconds():
    line = summarize("thing", [0.010, 0.020, 0.030, 0.040])

    assert "n=4" in line
    assert "mean=25.0ms" in line
    assert "max=40.0ms" in line


def test_report_combines_every_metric_and_the_run_parameters():
    metrics = Metrics(
        login_latencies=[0.05], match_latencies=[0.1], command_latencies=[0.02],
        login_errors=1, connect_errors=2, command_timeouts=3, games_matched=4,
    )

    text = report(metrics, players=10, duration=30.0)

    assert "10 players, 30s each" in text
    assert "games matched: 4" in text
    assert "login errors: 1" in text
    assert "connect errors: 2" in text
    assert "command timeouts: 3" in text
    assert "login latency" in text
    assert "matchmaking latency" in text
    assert "command round-trip latency" in text
