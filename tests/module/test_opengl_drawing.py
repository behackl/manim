import math

import numpy as np
from scipy.spatial import cKDTree

from manim import Ellipse
from manim.renderer.opengl.drawing import cubics_to_quadratics


def _samples(controls: np.ndarray, count: int) -> np.ndarray:
    t = np.linspace(0, 1, count)[:, None]
    degree = len(controls) - 1
    weights = [
        math.comb(degree, i) * (1 - t) ** (degree - i) * t**i
        for i in range(degree + 1)
    ]
    return sum(w * c for w, c in zip(weights, controls, strict=True))


def test_quadratic_pieces_stay_within_tolerance():
    cubics = Ellipse(6, 1).points
    for tolerance in (0.01, 0.001):
        quads = cubics_to_quadratics(cubics, tolerance)
        curve = np.concatenate([_samples(c, 400) for c in cubics.reshape(-1, 4, 3)])
        pieces = np.concatenate([_samples(q, 4000) for q in quads])
        distance, _ = cKDTree(pieces).query(curve)
        assert distance.max() <= tolerance
        np.testing.assert_allclose(quads[0, 0], cubics[0])
        np.testing.assert_allclose(quads[-1, 2], cubics[-1])
    assert len(cubics_to_quadratics(cubics, 0.001)) > len(
        cubics_to_quadratics(cubics, 0.01)
    )
