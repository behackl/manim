"""Immutable render input extracted from mobjects.

A renderer draws a list of :class:`RNode` snapshots instead of reading mobjects. Each node
carries the mobject's ``uid``, a transform, its draw order key and one payload with the
values to draw, plus the versions of the fields they came from, so a renderer can tell
what changed since the last frame.

Payload arrays are the mobjects' field values, not copies; they are read-only when
``MANIM_STRICT_FIELDS`` is set (see :mod:`manim.mobject.fields`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, NamedTuple

import numpy as np

from manim.mobject.fields import check_in_place_modifications
from manim.mobject.mobject import Mobject
from manim.mobject.types.image_mobject import (
    AbstractImageMobject,
    ImageMobjectFromCamera,
)
from manim.mobject.types.point_cloud_mobject import PMobject
from manim.mobject.types.vectorized_mobject import VMobject
from manim.utils.family import extract_mobject_family_members
from manim.utils.iterables import list_difference_update

if TYPE_CHECKING:
    from PIL.Image import Image, Resampling

    from manim.constants import CapStyleType, LineJointType
    from manim.renderer.cairo.camera import Camera
    from manim.typing import FloatRGBA_Array, PixelArray, Point3D, Point3D_Array

__all__ = ["RCameraView", "RImage", "RNode", "RPath", "RPoints", "extract"]

#: Transform of every node while mobjects store their points in scene coordinates.
IDENTITY = np.eye(4)
IDENTITY.flags.writeable = False


class RPath(NamedTuple):
    """A vectorized path (:class:`~.VMobject`)."""

    points: Point3D_Array
    fill_rgbas: FloatRGBA_Array
    stroke_rgbas: FloatRGBA_Array
    stroke_width: float
    background_stroke_rgbas: FloatRGBA_Array
    background_stroke_width: float
    joint_type: LineJointType
    cap_style: CapStyleType
    background_image: Image | str | None
    shade_in_3d: bool
    #: Start and end of the color gradient; only set when a gradient is drawn.
    gradient: tuple[Point3D, Point3D] | None
    #: Point used to sort paths by depth; only set for ``shade_in_3d`` paths.
    z_reference_point: Point3D | None
    #: Distance below which two points count as equal (closing subpaths).
    tolerance: float

    ARRAYS = (
        "points",
        "fill_rgbas",
        "stroke_rgbas",
        "background_stroke_rgbas",
        "sheen_direction",
    )


class RPoints(NamedTuple):
    """A point cloud (:class:`~.PMobject`)."""

    points: Point3D_Array
    rgbas: FloatRGBA_Array
    stroke_width: float

    ARRAYS = ("points", "rgbas")


class RImage(NamedTuple):
    """A raster image (:class:`~.AbstractImageMobject`), placed by its corner points."""

    pixel_array: PixelArray
    points: Point3D_Array
    resampling_algorithm: Resampling

    ARRAYS = ("pixel_array", "points")


class RCameraView(NamedTuple):
    """The view of another camera (:class:`~.ImageMobjectFromCamera`)."""

    camera: Camera
    points: Point3D_Array
    resampling_algorithm: Resampling

    ARRAYS = ("points",)


Payload = RPath | RPoints | RImage | RCameraView


class RNode(NamedTuple):
    """What a renderer draws for one mobject."""

    uid: int
    transform: np.ndarray
    z_index: float
    #: Version of each field of the mobject at extraction (see :func:`.field_version`).
    versions: Mapping[str, int]
    payload: Payload
    #: The mobject the node was extracted from. Only for camera state that is not a
    #: field yet (fixed in frame, fixed orientation); renderers must not read mobject
    #: state through it.
    source: Mobject


def extract(
    mobjects: Iterable[Mobject],
    *,
    use_z_index: bool = True,
    excluded_mobjects: Iterable[Mobject] = (),
) -> list[RNode]:
    """Return render snapshots for the families of ``mobjects`` in drawing order.

    The order is family order, without duplicates, stably sorted by ``z_index`` if
    ``use_z_index``. Families of ``excluded_mobjects`` and mobjects without points are
    left out, as are plain :class:`~.Mobject` instances, which have nothing to draw.

    Raises
    ------
    TypeError
        If a mobject is of a type no renderer can draw.
    """
    members = extract_mobject_family_members(
        mobjects, use_z_index=use_z_index, only_those_with_points=True
    )
    excluded = list(excluded_mobjects)
    if excluded:
        members = list_difference_update(
            members, extract_mobject_family_members(excluded, use_z_index=use_z_index)
        )
    nodes = []
    for mobject in members:
        payload = _payload(mobject)
        if payload is None:
            continue
        nodes.append(
            RNode(
                uid=mobject.uid,
                transform=IDENTITY,
                z_index=mobject.z_index,
                versions=_versions(mobject, payload.ARRAYS),
                payload=payload,
                source=mobject,
            )
        )
    return nodes


def _versions(mobject: Mobject, arrays: tuple[str, ...]) -> dict[str, int]:
    check_in_place_modifications(mobject, arrays)
    return dict(mobject.__dict__.get("_field_versions", ()))


def _payload(mobject: Mobject) -> Payload | None:
    if isinstance(mobject, VMobject):
        return _path(mobject)
    if isinstance(mobject, PMobject):
        return RPoints(mobject.points, mobject.rgbas, mobject.stroke_width)
    if isinstance(mobject, AbstractImageMobject):
        return RImage(
            mobject.get_pixel_array(), mobject.points, mobject.resampling_algorithm
        )
    if isinstance(mobject, ImageMobjectFromCamera):
        return RCameraView(mobject.camera, mobject.points, mobject.resampling_algorithm)
    if isinstance(mobject, Mobject):
        return None
    raise TypeError(
        f"Displaying an object of class {type(mobject).__name__} is not supported"
    )


def _path(vmobject: VMobject) -> RPath:
    attributes: dict[str, Any] = vmobject.__dict__
    no_color = _NO_COLOR
    fill = attributes.get("fill_rgbas", no_color)
    stroke = attributes.get("stroke_rgbas", no_color)
    background_stroke = attributes.get("background_stroke_rgbas", no_color)
    shade_in_3d = vmobject.shade_in_3d
    has_gradient = (
        shade_in_3d or max(len(fill), len(stroke), len(background_stroke)) > 1
    )
    return RPath(
        points=vmobject.points,
        fill_rgbas=fill,
        stroke_rgbas=stroke,
        stroke_width=vmobject.get_stroke_width(),
        background_stroke_rgbas=background_stroke,
        background_stroke_width=vmobject.get_stroke_width(background=True),
        joint_type=vmobject.joint_type,
        cap_style=vmobject.cap_style,
        background_image=vmobject.background_image,
        shade_in_3d=shade_in_3d,
        gradient=(
            tuple(vmobject.get_gradient_start_and_end_points())  # type: ignore[arg-type]
            if has_gradient
            else None
        ),
        z_reference_point=(
            vmobject.get_z_index_reference_point() if shade_in_3d else None
        ),
        tolerance=vmobject.tolerance_for_point_equality,
    )


_NO_COLOR = np.zeros((1, 4))
_NO_COLOR.flags.writeable = False
