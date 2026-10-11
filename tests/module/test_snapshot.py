from __future__ import annotations

import numpy as np

from manim import (
    BLUE,
    RED,
    RIGHT,
    Circle,
    ImageMobject,
    Mobject,
    PMobject,
    Square,
    VGroup,
)
from manim.mobject import fields
from manim.renderer.snapshot import RImage, RPath, RPoints, extract


def test_extract_skips_excluded_families_and_mobjects_without_drawing():
    square, circle = Square(), Circle()
    cloud = PMobject().add_points([[0, 0, 0]])
    image = ImageMobject(np.zeros((2, 2, 4), dtype=np.uint8))
    excluded = VGroup(Square(), Square())
    plain = Mobject()
    plain.points = [[0, 0, 0]]

    nodes = extract(
        [VGroup(square, circle), cloud, image, excluded, plain],
        excluded_mobjects=[excluded],
    )

    assert [node.uid for node in nodes] == [
        m.uid for m in (square, circle, cloud, image)
    ]
    assert [type(node.payload) for node in nodes] == [RPath, RPath, RPoints, RImage]
    assert len({node.uid for node in nodes}) == 4


def test_snapshot_shares_values_and_versions_track_changes(monkeypatch):
    monkeypatch.setattr(fields, "STRICT", False)
    square = Square()
    first = extract([square])[0]
    assert first.payload.points is square.points
    assert first.payload.gradient is None

    assert extract([square])[0].versions == first.versions

    square.set_fill(RED, opacity=1)
    second = extract([square])[0]
    changed = {k for k in first.versions if first.versions[k] != second.versions[k]}
    assert changed == {"fill_rgbas"}

    square.points[0] += RIGHT  # deprecated, but detected
    third = extract([square])[0]
    assert third.versions["points"] != second.versions["points"]

    square.set_stroke([RED, BLUE])
    np.testing.assert_allclose(
        extract([square])[0].payload.gradient,
        square.get_gradient_start_and_end_points(),
    )
