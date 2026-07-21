from server.matchmaking import find_opponent


def test_returns_none_when_nobody_is_waiting():
    assert find_opponent(1200, []) is None


def test_finds_an_opponent_with_the_exact_same_rating():
    assert find_opponent(1200, [("bob", 1200)]) == "bob"


def test_finds_an_opponent_within_the_default_range():
    assert find_opponent(1200, [("bob", 1290)]) == "bob"
    assert find_opponent(1200, [("bob", 1100)]) == "bob"


def test_does_not_match_an_opponent_outside_the_default_range():
    assert find_opponent(1200, [("bob", 1301)]) is None
    assert find_opponent(1200, [("bob", 1099)]) is None


def test_boundary_ratings_exactly_at_the_range_do_match():
    assert find_opponent(1200, [("bob", 1300)]) == "bob"
    assert find_opponent(1200, [("bob", 1100)]) == "bob"


def test_custom_rating_range_is_respected():
    assert find_opponent(1200, [("bob", 1250)], rating_range=20) is None
    assert find_opponent(1200, [("bob", 1250)], rating_range=100) == "bob"


def test_returns_the_first_qualifying_opponent_in_queue_order():
    waiting = [("bob", 900), ("carol", 1210), ("dave", 1190)]
    assert find_opponent(1200, waiting) == "carol"


def test_skips_non_qualifying_entries_to_find_a_later_qualifying_one():
    waiting = [("bob", 2000), ("carol", 1250)]
    assert find_opponent(1200, waiting) == "carol"


def test_does_not_mutate_the_waiting_sequence():
    waiting = [("bob", 1200)]
    find_opponent(1200, waiting)
    assert waiting == [("bob", 1200)]
