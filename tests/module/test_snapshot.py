from __future__ import annotations

import numpy as np
import pytest

from manim import (
    BLUE,
    RED,
    RIGHT,
    UP,
    Circle,
    Dot,
    ImageMobject,
    Mobject,
    PMobject,
    Square,
    ThreeDAxes,
    VGroup,
)
from manim.mobject import fields
from manim.renderer.snapshot import Extractor, RImage, RPath, RPoints, extract


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


def test_extractor_reuses_snapshots_until_a_field_changes(monkeypatch):
    monkeypatch.setattr(fields, "STRICT", False)
    extractor = Extractor()
    square = Square()
    first = extractor.extract([square])[0]
    assert extractor.extract([square])[0] is first
    square.set_fill(RED, 1)
    filled = extractor.extract([square])[0]
    assert filled is not first
    assert filled.payload.fill_rgbas[0, 3] == 1
    before = extractor.extract([square])[0]
    square.points[0, 0] += 1  # in place, outside strict mode
    # A new version, so that renderers draw it again.
    assert extractor.extract([square])[0].versions != before.versions
    square.tolerance_for_point_equality = 0.5
    assert extractor.extract([square])[0].payload.tolerance == 0.5


def test_extractor_follows_the_group_a_mobject_is_drawn_with():
    extractor = Extractor()
    group = VGroup(Square(), Square().shift(RIGHT))
    group.set_shade_in_3d(True, z_index_as_group=True)
    first = extractor.extract([group])[1]
    group[0].shift(UP)  # moves the group's center, not the second square
    second = extractor.extract([group])[1]
    np.testing.assert_allclose(second.payload.z_reference_point, group.get_center())

    axes = ThreeDAxes()
    tip, piece = axes.x_axis.family_members_with_points()[1:3]
    before = next(n for n in extractor.extract([axes]) if n.uid == piece.uid)
    tip.shift(UP)  # another piece of the axis, which moves the axis's gradient
    after = next(n for n in extractor.extract([axes]) if n.uid == piece.uid)
    np.testing.assert_allclose(
        after.payload.gradient, piece.get_gradient_start_and_end_points()
    )
    assert after is not before


def test_extractor_takes_orientation_centers_anew():
    extractor = Extractor()
    dot, target = Dot(), Dot()
    dot.fix_orientation(target.get_center)
    before = extractor.extract([dot])[0]
    target.shift(RIGHT)
    np.testing.assert_allclose(
        extractor.extract([dot])[0].fixed_orientation_center,
        before.fixed_orientation_center + RIGHT,
    )


def test_extractor_rejects_snapshots_that_change_without_their_fields(monkeypatch):
    monkeypatch.setattr(fields, "STRICT", True)

    class Wobbly(Square):
        def get_stroke_width(self, background=False):
            return 1.0 + len(calls)

    calls = []
    extractor = Extractor()
    wobbly = Wobbly()
    extractor.extract([wobbly])
    calls.append(1)
    with pytest.raises(AssertionError, match="drawn_with"):
        extractor.extract([wobbly])
