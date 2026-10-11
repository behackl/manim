from __future__ import annotations

import numpy as np
import pytest

from manim import RED, RIGHT, Circle, Square, VMobject
from manim.mobject import fields
from manim.mobject.fields import Field, field_version
from manim.mobject.types.point_cloud_mobject import PMobject
from manim.utils.hashing import get_json


def test_version_changes_on_assignment_only():
    square = Square()
    version = field_version(square, "points")

    square.get_center()
    square.set_fill(opacity=0.5)
    assert field_version(square, "points") == version

    square.shift(RIGHT)
    assert field_version(square, "points") != version


def test_strict_mode_stores_an_owned_float_copy(monkeypatch):
    monkeypatch.setattr(fields, "STRICT", True)
    square = Square()
    corners = np.array([[0.0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]])

    square.points = corners
    corners[0] = [5, 5, 5]
    np.testing.assert_array_equal(square.points[0], [0, 0, 0])

    square.points = [[0, 0, 0]]
    assert square.points.dtype == np.float64


def test_in_place_modification_raises_in_strict_mode(monkeypatch):
    monkeypatch.setattr(fields, "STRICT", True)
    with pytest.raises(ValueError, match="read-only"):
        Square().points[0] = [1, 2, 3]


def test_in_place_modification_is_detected_and_warned_once(monkeypatch, manim_caplog):
    monkeypatch.setattr(fields, "STRICT", False)
    monkeypatch.setattr(fields, "_warned", set())

    class Shape(Square):
        pass

    first, second = Shape(), Shape()
    version = field_version(first, "points")
    field_version(second, "points")

    first.points[0] = [1, 2, 3]
    second.points[0] = [1, 2, 3]

    changed = field_version(first, "points")
    assert changed != version
    assert field_version(first, "points") == changed
    field_version(second, "points")
    warnings = [
        r for r in manim_caplog.records if "in place is deprecated" in r.message
    ]
    assert [r.message.split(" in place")[0] for r in warnings] == [
        "Modifying Shape.points"
    ]


def test_versions_do_not_change_play_cache_keys():
    square, reassigned = Square(), Square()
    reassigned.points = reassigned.points
    field_version(reassigned, "points")

    assert field_version(reassigned, "points") != field_version(square, "points")
    assert get_json(reassigned) == get_json(square)


def test_plain_field_has_version_zero_until_assigned():
    class Holder:
        width = Field()

    holder = Holder()
    assert field_version(holder, "width") == 0

    holder.width = 2.0
    assert holder.width == 2.0
    assert field_version(holder, "width") != 0


def test_point_cloud_colors_use_opengl_storage_when_rebased(using_opengl_renderer):
    cloud = PMobject()
    cloud.add_points([[0, 0, 0], [1, 0, 0]])

    cloud.set_color(RED)

    assert "rgbas" not in cloud.__dict__
    assert cloud.rgbas is cloud.data["rgbas"]


def test_animation_steps_that_change_nothing_keep_versions():
    start, end = Square(), Circle().set_color(RED)
    start.align_data(end)
    moving = start.copy()

    moving.interpolate(start, end, 1)
    versions = {name: field_version(moving, name) for name in ("points", "fill_rgbas")}
    moving.interpolate(start, end, 1)
    assert {name: field_version(moving, name) for name in versions} == versions

    moving.stroke_width = 2.5
    version = field_version(moving, "stroke_width")
    moving.stroke_width = float("2.5")  # equal, but another object
    assert field_version(moving, "stroke_width") == version

    partial = VMobject()
    partial.pointwise_become_partial(end, 0, 1)
    points_version = field_version(partial, "points")
    partial.pointwise_become_partial(end, 0, 1)
    assert field_version(partial, "points") == points_version
