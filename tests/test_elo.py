import pytest

from server.elo import expected_score, update_ratings


def test_expected_score_is_half_for_equal_ratings():
    assert expected_score(1200, 1200) == pytest.approx(0.5)


def test_expected_score_favors_the_higher_rated_player():
    assert expected_score(1400, 1200) > 0.5
    assert expected_score(1200, 1400) < 0.5


def test_expected_scores_of_both_sides_sum_to_one():
    a = expected_score(1350, 1180)
    b = expected_score(1180, 1350)
    assert a + b == pytest.approx(1.0)


def test_a_draw_between_equal_ratings_leaves_both_unchanged():
    new_a, new_b = update_ratings(1200, 1200, 0.5)
    assert (new_a, new_b) == (1200, 1200)


def test_a_win_between_equal_ratings_moves_them_apart_symmetrically():
    new_a, new_b = update_ratings(1200, 1200, 1.0)
    assert new_a > 1200
    assert new_b < 1200
    assert (new_a - 1200) == (1200 - new_b)


def test_a_loss_between_equal_ratings_moves_them_apart_the_other_way():
    new_a, new_b = update_ratings(1200, 1200, 0.0)
    assert new_a < 1200
    assert new_b > 1200


def test_upset_win_gains_more_than_an_expected_win():
    # The lower-rated player winning is a bigger surprise than the
    # higher-rated player winning, so it should move ratings further.
    upset_a, upset_b = update_ratings(1000, 1400, 1.0)  # underdog a wins
    expected_a, expected_b = update_ratings(1400, 1000, 1.0)  # favorite a wins

    assert (upset_a - 1000) > (expected_a - 1400)


def test_favorite_winning_gains_fewer_points_than_the_k_factor():
    new_a, _ = update_ratings(1400, 1000, 1.0)
    assert 0 < (new_a - 1400) < 32


def test_underdog_winning_gains_close_to_the_full_k_factor():
    new_a, _ = update_ratings(1000, 1400, 1.0)
    assert (new_a - 1000) > 25  # close to the full K_FACTOR=32


def test_rating_changes_are_symmetric_within_rounding():
    new_a, new_b = update_ratings(1263, 1417, 1.0)
    delta_a = new_a - 1263
    delta_b = new_b - 1417
    assert abs(delta_a + delta_b) <= 1  # opposite in sign, equal up to rounding


def test_returned_ratings_are_integers():
    new_a, new_b = update_ratings(1200, 1250, 0.5)
    assert isinstance(new_a, int)
    assert isinstance(new_b, int)


@pytest.mark.parametrize("bad_score", [-0.1, 1.1, 2.0, -1.0])
def test_score_outside_zero_to_one_raises(bad_score):
    with pytest.raises(ValueError):
        update_ratings(1200, 1200, bad_score)


@pytest.mark.parametrize("ok_score", [0.0, 0.5, 1.0])
def test_score_at_or_inside_the_valid_range_does_not_raise(ok_score):
    update_ratings(1200, 1200, ok_score)
