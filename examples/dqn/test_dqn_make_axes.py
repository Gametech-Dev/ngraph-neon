import neon as ng
from neon.examples.dqn import dqn


def test_make_axes_noop():
    axes = dqn.make_axes([ng.make_axis(1), ng.make_axis(2)])

    assert axes == ng.make_axes(axes)


def test_make_axes_array():
    assert dqn.make_axes([1, 3]).lengths == (1, 3)
