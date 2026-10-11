from __future__ import annotations

import numpy as np
import pytest

from manim import RIGHT, Square
from manim.mobject import fields
from manim.mobject.fields import field_version
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
