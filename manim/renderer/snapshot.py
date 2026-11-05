"""Immutable render input extracted from mobjects.

A renderer draws a list of :class:`RNode` snapshots instead of reading mobjects. Each node
carries the mobject's ``uid``, a transform, its draw order key and one payload with the
values to draw, plus the versions of the fields they came from, so a renderer can tell
what changed since the last frame.

Payload arrays are the mobjects' field values, not copies; they are read-only when
``MANIM_STRICT_FIELDS`` is set (see :mod:`manim.mobject.fields`).
"""

from __future__ import annotations

import weakref
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, NamedTuple

import numpy as np

from manim.mobject import fields
from manim.mobject.fields import check_in_place_modifications, field_version
from manim.mobject.mobject import Mobject
from manim.mobject.three_d.mesh import MeshMobject
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
    from manim.typing import FloatRGBA_Array, PixelArray, Point3D, Point3D_Array

__all__ = [
    "Extractor",
    "RCameraView",
    "RImage",
    "RMesh",
    "RNode",
    "RPath",
    "RPoints",
    "extract",
    "snapshot",
]

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


class RPoints(NamedTuple):
    """A point cloud (:class:`~.PMobject`)."""

    points: Point3D_Array
    rgbas: FloatRGBA_Array
    stroke_width: float


class RImage(NamedTuple):
    """A raster image (:class:`~.AbstractImageMobject`), placed by its corner points."""

    pixel_array: PixelArray
    points: Point3D_Array
    resampling_algorithm: Resampling


class RCameraView(NamedTuple):
    """Where to show the view of another camera (:class:`~.ImageMobjectFromCamera`).

    The renderer supplies the pixels, looked up by the node's ``uid``.
    """

    points: Point3D_Array
    resampling_algorithm: Resampling
    #: ``id()`` of the camera whose view is shown; copies of a view share it.
    camera_id: int = 0


class RMesh(NamedTuple):
    """A triangle mesh (:class:`~.MeshMobject`)."""

    points: Point3D_Array
    #: Vertex indices, three per triangle.
    triangles: np.ndarray
    #: One colour for the whole mesh, or one per vertex.
    rgbas: FloatRGBA_Array
    #: Texture coordinates per vertex; empty without a texture.
    uvs: np.ndarray
    #: RGBA pixels; empty without a texture.
    texture: PixelArray
    gloss: float
    shadow: float
    depth_test: bool
    #: Polygons as vertex indices (see :attr:`.MeshMobject.faces`).
    faces: np.ndarray
    shade_in_3d: bool
    #: Colour and width of the outlines of the faces.
    stroke_rgbas: FloatRGBA_Array
    stroke_width: float


Payload = RPath | RPoints | RImage | RCameraView | RMesh

# The array fields each payload is drawn from, checked for in-place modifications.
_ARRAYS: dict[type, tuple[str, ...]] = {
    RPath: (
        "points",
        "fill_rgbas",
        "stroke_rgbas",
        "background_stroke_rgbas",
        "sheen_direction",
    ),
    RPoints: ("points", "rgbas"),
    RImage: ("pixel_array", "points"),
    RCameraView: ("points",),
    RMesh: ("points", "triangles", "faces", "rgbas", "uvs", "texture", "stroke_rgbas"),
}


class RNode(NamedTuple):
    """What a renderer draws for one mobject."""

    uid: int
    transform: np.ndarray
    z_index: float
    #: Version of each field of the mobject at extraction (see :func:`.field_version`).
    versions: Mapping[str, int]
    payload: Payload
    #: Drawn as if the camera were at its default position (see
    #: :meth:`.Mobject.fix_in_frame`).
    fixed_in_frame: bool
    #: The point the mobject keeps facing the camera from, or ``None`` (see
    #: :meth:`.Mobject.fix_orientation`).
    fixed_orientation_center: Point3D | None


def extract(
    mobjects: Iterable[Mobject],
    *,
    include_submobjects: bool = True,
    use_z_index: bool = True,
    excluded_mobjects: Iterable[Mobject] = (),
) -> list[RNode]:
    """Return render snapshots for the families of ``mobjects`` in drawing order.

    The order is family order, without duplicates, stably sorted by ``z_index`` if
    ``use_z_index``. Families of ``excluded_mobjects`` and mobjects without points are
    left out. With ``include_submobjects=False``, ``mobjects`` are taken as given.
    Plain :class:`~.Mobject` instances are always left out; they have nothing to draw.

    Every snapshot is taken anew; an :class:`Extractor` reuses those of unchanged
    mobjects.

    Raises
    ------
    TypeError
        If a mobject is of a type no renderer can draw.
    """
    nodes = []
    for mobject in _members(
        mobjects, include_submobjects, use_z_index, excluded_mobjects
    ):
        check_in_place_modifications(mobject, _arrays_of(mobject))
        node = snapshot(mobject)
        if node is not None:
            nodes.append(node)
    return nodes


class Extractor:
    """Takes render snapshots like :func:`extract`, reusing the snapshot of a
    mobject while its fields, and the points of the family it is
    :meth:`~.Mobject.drawn_with`, keep their versions.

    This relies on one rule: a snapshot is a function of those fields. Classes
    that draw from other state set ``_drawn_from_fields = False``, and mobjects
    with a fixed orientation call their center function; both are taken anew every
    time. In strict field mode (:mod:`manim.mobject.fields`), every
    reused snapshot is compared with a fresh one, so a class that breaks the rule
    fails loudly instead of showing stale pixels.

    Whoever draws frames owns an extractor; it holds the mobjects it saw weakly.
    """

    def __init__(self) -> None:
        self._snapshots: weakref.WeakKeyDictionary[
            Mobject, tuple[tuple[Any, ...], RNode | None]
        ] = weakref.WeakKeyDictionary()

    def extract(
        self,
        mobjects: Iterable[Mobject],
        *,
        include_submobjects: bool = True,
        use_z_index: bool = True,
        excluded_mobjects: Iterable[Mobject] = (),
    ) -> list[RNode]:
        """Snapshots as :func:`extract` returns them."""
        nodes = []
        snapshots = self._snapshots
        # Versions of the groups mobjects are drawn with, once per call.
        groups: dict[int, tuple[Any, ...]] = {}
        for mobject in _members(
            mobjects, include_submobjects, use_z_index, excluded_mobjects
        ):
            check_in_place_modifications(mobject, _arrays_of(mobject))
            # The orientation center comes from a function, called every time.
            if not mobject._drawn_from_fields or mobject.fixed_orientation is not None:
                node = snapshot(mobject)
            else:
                key = _version_key(mobject, groups)
                cached = snapshots.get(mobject)
                if cached is not None and cached[0] == key:
                    node = cached[1]
                    if fields.STRICT:
                        _check_unchanged(mobject, node)
                else:
                    node = snapshot(mobject)
                    snapshots[mobject] = (key, node)
            if node is not None:
                nodes.append(node)
        return nodes


def snapshot(mobject: Mobject) -> RNode | None:
    """The render snapshot of ``mobject`` alone, or ``None`` if it draws nothing."""
    payload = _payload(mobject)
    if payload is None:
        return None
    return RNode(
        uid=mobject.uid,
        transform=IDENTITY,
        z_index=mobject.z_index,
        versions=dict(mobject.__dict__.get("_field_versions", ())),
        payload=payload,
        fixed_in_frame=mobject.fixed_in_frame,
        fixed_orientation_center=(
            None
            if mobject.fixed_orientation is None
            else np.asarray(mobject.fixed_orientation(), dtype=float)
        ),
    )


def _members(
    mobjects: Iterable[Mobject],
    include_submobjects: bool,
    use_z_index: bool,
    excluded_mobjects: Iterable[Mobject],
) -> list[Mobject]:
    if not include_submobjects:
        return list(mobjects)
    members = extract_mobject_family_members(
        mobjects, use_z_index=use_z_index, only_those_with_points=True
    )
    excluded = list(excluded_mobjects)
    if excluded:
        members = list_difference_update(
            members,
            extract_mobject_family_members(excluded, use_z_index=use_z_index),
        )
    return members


def _version_key(
    mobject: Mobject, groups: dict[int, tuple[Any, ...]]
) -> tuple[Any, ...]:
    """Equal while no field of ``mobject``, and no points of its
    :meth:`~.Mobject.drawn_with` family, are assigned.

    Versions come from one counter that only goes up, so a mobject's versions
    change exactly when their largest one or their number does. ``groups`` holds
    the keys of the groups seen in this call: the members of a group share them.
    """
    versions = mobject.__dict__.get("_field_versions")
    key: tuple[Any, ...] = (
        (max(versions.values()), len(versions)) if versions else (0, 0)
    )
    group = mobject.drawn_with()
    if group is None:
        return key
    group_key = groups.get(id(group))
    if group_key is None:
        group_key = groups[id(group)] = tuple(
            (id(member), field_version(member, "points"))
            for member in group.get_family()
        )
    return (*key, group_key)


def _check_unchanged(mobject: Mobject, node: RNode | None) -> None:
    if not _same(node, snapshot(mobject)):
        raise AssertionError(
            f"The render snapshot of {mobject!r} changed although none of the "
            "fields it is drawn from did. Draw it from fields, return the mobject "
            "it also depends on from drawn_with(), or set "
            f"{type(mobject).__name__}._drawn_from_fields = False."
        )


def _same(a: Any, b: Any) -> bool:
    if a is b:
        return True
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        return bool(np.array_equal(a, b))
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    return bool(a == b)


def _arrays_of(mobject: Mobject) -> tuple[str, ...]:
    """The array fields that snapshots of ``mobject`` are drawn from."""
    if isinstance(mobject, VMobject):
        return _ARRAYS[RPath]
    if isinstance(mobject, PMobject):
        return _ARRAYS[RPoints]
    if isinstance(mobject, AbstractImageMobject):
        return _ARRAYS[RImage]
    if isinstance(mobject, ImageMobjectFromCamera):
        return _ARRAYS[RCameraView]
    if isinstance(mobject, MeshMobject):
        return _ARRAYS[RMesh]
    return ()


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
        return RCameraView(
            mobject.points, mobject.resampling_algorithm, id(mobject.camera)
        )
    if isinstance(mobject, MeshMobject):
        return RMesh(
            mobject.points,
            mobject.triangles,
            mobject.rgbas,
            mobject.uvs,
            mobject.texture,
            mobject.gloss,
            mobject.shadow,
            mobject.depth_test,
            mobject.get_faces(),
            mobject.shade_in_3d,
            mobject.stroke_rgbas,
            mobject.stroke_width,
        )
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
            tuple(vmobject.get_gradient_start_and_end_points())
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
