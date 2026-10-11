"""Utility functions for three-dimensional mobjects."""

from __future__ import annotations

__all__ = [
    "get_3d_vmob_gradient_start_and_end_points",
    "get_3d_vmob_start_corner_index",
    "get_3d_vmob_end_corner_index",
    "get_3d_vmob_start_corner",
    "get_3d_vmob_end_corner",
    "get_3d_vmob_unit_normal",
    "get_3d_vmob_start_corner_unit_normal",
    "get_3d_vmob_end_corner_unit_normal",
]


from typing import TYPE_CHECKING, Literal

import numpy as np

from manim.constants import ORIGIN, UP
from manim.utils.space_ops import get_unit_normal

if TYPE_CHECKING:
    from manim.typing import Point3D, Point3D_Array, Vector3D

    from ..types.vectorized_mobject import VMobject


def get_3d_vmob_gradient_start_and_end_points(
    vmob: VMobject,
) -> tuple[Point3D, Point3D]:
    return (
        get_3d_vmob_start_corner(vmob),
        get_3d_vmob_end_corner(vmob),
    )


def get_3d_vmob_start_corner_index(vmob: VMobject) -> Literal[0]:
    return 0


def get_3d_vmob_end_corner_index(vmob: VMobject) -> int:
    return _end_corner_index(vmob.points)


def get_3d_vmob_start_corner(vmob: VMobject) -> Point3D:
    return _start_corner(vmob.points)


def get_3d_vmob_end_corner(vmob: VMobject) -> Point3D:
    return _end_corner(vmob.points)


def get_3d_vmob_unit_normal(vmob: VMobject, point_index: int) -> Vector3D:
    return _unit_normal(vmob.points, point_index)


def get_3d_vmob_start_corner_unit_normal(vmob: VMobject) -> Vector3D:
    return _unit_normal(vmob.points, 0)


def get_3d_vmob_end_corner_unit_normal(vmob: VMobject) -> Vector3D:
    return _unit_normal(vmob.points, _end_corner_index(vmob.points))


# The same on the points of a path, for renderers drawing from snapshots.


def _end_corner_index(points: Point3D_Array) -> int:
    return ((len(points) - 1) // 6) * 3


def _start_corner(points: Point3D_Array) -> Point3D:
    if len(points) == 0:
        return np.array(ORIGIN)
    return points[0]


def _end_corner(points: Point3D_Array) -> Point3D:
    if len(points) == 0:
        return np.array(ORIGIN)
    return points[_end_corner_index(points)]


def _unit_normal(points: Point3D_Array, point_index: int) -> Vector3D:
    n_points = len(points)
    # At most one curve: no plane to take a normal of.
    if n_points <= 4:
        return np.array(UP)
    i = point_index
    im3 = i - 3 if i > 2 else (n_points - 4)
    ip3 = i + 3 if i < (n_points - 3) else 3
    unit_normal = get_unit_normal(
        points[ip3] - points[i],
        points[im3] - points[i],
    )
    if np.linalg.norm(unit_normal) == 0:
        return np.array(UP)
    return unit_normal
