import pytest

from data.sanity_check import looks_like_split


@pytest.mark.parametrize("ret", [-0.9, -0.5, -0.667, -0.75, 9.0, 1.0])
def test_split_shaped_moves_are_detected(ret):
    assert looks_like_split(ret)


@pytest.mark.parametrize("ret", [0.0, 0.05, -0.05, -0.26, -0.35, 0.3])
def test_ordinary_and_large_real_moves_are_not_split_shaped(ret):
    assert not looks_like_split(ret)
