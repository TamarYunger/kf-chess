import queue

from client.session.queue_utils import drain_queue


def test_drain_queue_pops_everything_currently_queued_in_order():
    q = queue.Queue()
    q.put({"type": "a"})
    q.put({"type": "b"})

    assert drain_queue(q) == [{"type": "a"}, {"type": "b"}]
    assert q.empty()


def test_drain_queue_on_an_empty_queue_returns_an_empty_list():
    assert drain_queue(queue.Queue()) == []
