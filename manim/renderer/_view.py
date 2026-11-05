"""How a camera state places, orders and shades render snapshots: shared by the
renderers, which draw from a :class:`.CameraState` and never read cameras.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from manim.mobject.three_d.three_d_utils import (
    _end_corner,
    _end_corner_index,
    _start_corner,
    _unit_normal,
)
from manim.renderer.snapshot import RMesh
from manim.utils.color import get_shaded_rgb
from manim.utils.space_ops import get_unit_normal

if TYPE_CHECKING:
    from manim.renderer.protocol import CameraState
    from manim.renderer.snapshot import RNode, RPath
    from manim.typing import FloatRGBA_Array, Point3D, Point3D_Array

__all__: list[str] = []


def is_3d(state: CameraState) -> bool:
    """Whether the state projects with perspective (a :class:`.ThreeDCamera`)."""
    return state.focal_distance is not None


def view_transform_center(state: CameraState) -> Point3D:
    """The scene point at the middle of the image after :func:`place`.

    A perspective projection already subtracts the frame center.
    """
    return np.zeros(3) if is_3d(state) else state.center


def project_points(state: CameraState, points: Point3D_Array) -> Point3D_Array:
    """Rotate points about the frame center and scale x and y by the perspective
    factor ``focal_distance / (focal_distance - z)`` and the zoom.
    """
    focal_distance = state.focal_distance
    assert focal_distance is not None
    points = points - state.center
    points = np.dot(points, state.rotation.T)
    zs = points[:, 2]
    factor = focal_distance / (focal_distance - zs)
    factor[(focal_distance - zs) < 0] = 10**6
    scale = factor * state.zoom
    for i in 0, 1:
        points[:, i] *= scale
    return points


def place(
    state: CameraState,
    points: Point3D_Array,
    fixed_in_frame: bool,
    orientation_center: Point3D | None,
) -> Point3D_Array:
    """Where points are drawn, in the coordinates of :func:`view_transform_center`."""
    if not np.all(np.isfinite(points)):
        return np.zeros((1, 3))
    if not is_3d(state):
        if fixed_in_frame:
            # Drawn as if the frame were at its default position and size.
            scale = state.frame_width / state.default_frame_width
            return state.center + scale * points
        return points
    # The view transform is centered at the origin, so points fixed in frame are
    # drawn where they are.
    if fixed_in_frame:
        return points
    if orientation_center is not None:
        center = orientation_center.reshape((1, 3))
        return points + (project_points(state, center)[0] - orientation_center)
    return project_points(state, points)


def display_points(
    state: CameraState, node: RNode, points: Point3D_Array
) -> Point3D_Array:
    """:func:`place` for the points of a render snapshot."""
    return place(state, points, node.fixed_in_frame, node.fixed_orientation_center)


def sort_for_display(state: CameraState, nodes: list[RNode]) -> list[RNode]:
    """Order snapshots far to near for a perspective view (stably; nodes without a
    depth reference keep their order and come last). Flat views keep the order.
    """
    if not is_3d(state):
        return nodes
    depth_axis = state.rotation[2]

    def z_key(node: RNode) -> float:
        payload = node.payload
        reference_point = getattr(payload, "z_reference_point", None)
        if isinstance(payload, RMesh) and len(payload.points):
            # A whole mesh (on OpenGL; Cairo sorts its faces) goes by its middle.
            points = np.asarray(payload.points)
            reference_point = (points.min(axis=0) + points.max(axis=0)) / 2
        if reference_point is None:
            return np.inf  # type: ignore[no-any-return]
        return float(np.dot(reference_point, depth_axis))

    return sorted(nodes, key=z_key)


def shaded_rgbas(
    state: CameraState, path: RPath, rgbas: FloatRGBA_Array
) -> FloatRGBA_Array:
    """The colors of a path at its two gradient ends, shaded towards the light if
    the path is ``shade_in_3d`` and the state shades; else ``rgbas``.
    """
    points = path.points
    if not (state.shade_3d and path.shade_in_3d and len(points) > 0):
        return rgbas
    light = state.light
    shaded = rgbas.repeat(2, axis=0) if len(rgbas) < 2 else np.array(rgbas[:2])
    shaded[0, :3] = get_shaded_rgb(
        shaded[0, :3], _start_corner(points), _unit_normal(points, 0), light
    )
    end = _end_corner_index(points)
    shaded[1, :3] = get_shaded_rgb(
        shaded[1, :3], _end_corner(points), _unit_normal(points, end), light
    )
    return shaded


def shade_faces(
    state: CameraState, outlines: np.ndarray, colours: np.ndarray
) -> np.ndarray:
    """The colours of ``shade_in_3d`` faces at their two gradient ends, shape
    ``(m, 2, 4)``, for face outlines as :func:`.face_outlines` makes them and one
    colour per face. The same as :func:`shaded_rgbas` of each face as a path.
    """
    shaded = np.repeat(colours[:, None], 2, axis=1)
    if not state.shade_3d or len(outlines) == 0:
        return shaded
    count = outlines.shape[1]
    light = state.light
    end = _end_corner_index(outlines[0])
    for side, (index, before, after) in enumerate(
        ((0, count - 4, 3), (end, end - 3, end + 3 if end < count - 3 else 3))
    ):
        point = outlines[:, index]
        normals = _unit_normals(outlines[:, after] - point, outlines[:, before] - point)
        to_sun = light - point
        lengths = np.linalg.norm(to_sun, axis=1, keepdims=True)
        to_sun = np.divide(
            to_sun, lengths, out=np.zeros_like(to_sun), where=lengths > 0
        )
        amount = 0.5 * np.sum(normals * to_sun, axis=1) ** 3
        amount = np.where(amount < 0, 0.5 * amount, amount)
        shaded[:, side, :3] += amount[:, None]
    return shaded


def _unit_normals(v1: np.ndarray, v2: np.ndarray) -> np.ndarray:
    """:func:`.get_unit_normal` of each row pair, for outlines of at least two
    sides (whose shading uses it).
    """
    tol = 1e-6
    div1 = np.abs(v1).max(axis=1, keepdims=True)
    div2 = np.abs(v2).max(axis=1, keepdims=True)
    u1 = v1 / np.where(div1 == 0, 1, div1)
    u2 = v2 / np.where(div2 == 0, 1, div2)
    cp = np.stack(
        (
            u1[:, 1] * u2[:, 2] - u1[:, 2] * u2[:, 1],
            u1[:, 2] * u2[:, 0] - u1[:, 0] * u2[:, 2],
            u1[:, 0] * u2[:, 1] - u1[:, 1] * u2[:, 0],
        ),
        axis=1,
    )
    norm = np.sqrt(np.sum(cp * cp, axis=1))
    result = cp / np.where(norm > tol, norm, 1)[:, None]
    # Degenerate rows (aligned or null vectors) take the scalar path's fallbacks.
    for row in np.flatnonzero(norm <= tol):
        result[row] = get_unit_normal(v1[row], v2[row])
    return result
