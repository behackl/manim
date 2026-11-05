"""Projection uses current camera angles, and reading it leaves cache keys unchanged."""

import numpy as np
import pytest

from manim import ThreeDCamera
from manim.utils.hashing import get_json


def test_projection_and_identity_do_not_depend_on_drawing():
    camera = ThreeDCamera()
    camera.set_theta(0)
    point = np.array([1.0, 0.0, 0.0])
    identity = get_json(camera)
    before = camera.project_point(point)
    with pytest.raises(ValueError, match="read-only"):
        camera.rotation_matrix[0, 0] = 5
    np.testing.assert_allclose(before, [0, -1, 0], atol=1e-12)
    camera._prepare_for_render()
    np.testing.assert_array_equal(before, camera.project_point(point))
    assert get_json(camera) == identity
    camera.theta_tracker.set_value(0.4)
    assert get_json(camera) != identity
    assert not np.array_equal(before, camera.project_point(point))


def test_points_are_projected_with_the_perspective_factor():
    camera = ThreeDCamera(focal_distance=10.0)
    camera.set_phi(0)
    camera.set_theta(-np.pi / 2)
    near = camera.project_point(np.array([1.0, 0.0, 5.0]))
    # x and y scale by focal_distance / (focal_distance - z).
    np.testing.assert_allclose(near[:2], [2.0, 0.0], atol=1e-12)
    with pytest.raises(TypeError, match="exponential_projection"):
        ThreeDCamera(exponential_projection=True)
