"""Meshes drawn by the Cairo renderer, as one filled polygon per face.

The faces of a mesh become path snapshots, sorted far to near; under a
:class:`.ThreeDCamera` they are then sorted with the other 3D paths of the scene, as
the faces of a polygon surface were.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from manim import config
from manim.constants import CapStyleType, LineJointType
from manim.renderer.snapshot import IDENTITY, RMesh, RNode, RPath
from manim.utils.bezier import interpolate

if TYPE_CHECKING:
    from .camera import Camera

__all__ = ["face_colours", "face_outlines", "mesh_faces"]

#: Scene units per unit of stroke width on the Cairo renderer.
_STROKE_WIDTH_UNIT = 0.01

_NO_COLOR = np.zeros((1, 4))
_NO_COLOR.flags.writeable = False
#: Where the anchors and handles of a straight cubic curve lie.
_THIRDS = np.array([0, 1 / 3, 2 / 3, 1])


def mesh_faces(node: RNode, camera: Camera) -> list[RNode]:
    """Path snapshots for the faces of a mesh node, from far to near."""
    mesh: RMesh = node.payload  # type: ignore[assignment]
    faces = np.asarray(mesh.faces)
    if len(faces) == 0 or len(mesh.points) == 0:
        return []
    corners = np.asarray(mesh.points)[faces]
    centers = (corners.min(axis=1) + corners.max(axis=1)) / 2
    colours = face_colours(mesh, faces)
    if not mesh.shade_in_3d and (mesh.gloss or mesh.shadow):
        colours = _lit(colours, corners, centers, mesh.gloss, mesh.shadow, camera)
    outlines = face_outlines(corners)
    end = ((outlines.shape[1] - 1) // 6) * 3
    depth = centers @ camera._view_rotation()[2]
    versions = node.versions
    face_versions = {
        "points": max(versions.get("points", 0), versions.get("faces", 0)),
        "fill_rgbas": max(
            versions.get(name, 0) for name in ("rgbas", "uvs", "texture", "points")
        ),
        "stroke_rgbas": versions.get("stroke_rgbas", 0),
    }
    # Without outlines, neighbouring faces leave a seam where their antialiased edges
    # meet; opaque faces are outlined in their own colour, a pixel wide, to close it.
    seam = (
        config["frame_width"] / config["pixel_width"] / _STROKE_WIDTH_UNIT
        if mesh.stroke_width == 0
        else None
    )
    strokes = np.asarray(mesh.stroke_rgbas)
    per_face = len(strokes) == len(faces) > 1
    nodes = []
    for index in np.argsort(depth, kind="stable"):
        outline = outlines[index]
        fill = colours[index : index + 1]
        stroke = strokes[index : index + 1] if per_face else strokes[:1]
        width = mesh.stroke_width
        if seam is not None and fill[0, 3] >= 1:
            stroke, width = fill, seam
        path = RPath(
            points=outline,
            fill_rgbas=fill,
            stroke_rgbas=stroke,
            stroke_width=width,
            background_stroke_rgbas=_NO_COLOR,
            background_stroke_width=0,
            joint_type=LineJointType.AUTO,
            cap_style=CapStyleType.AUTO,
            background_image=None,
            shade_in_3d=mesh.shade_in_3d,
            gradient=(outline[0], outline[end]) if mesh.shade_in_3d else None,
            z_reference_point=centers[index],
            tolerance=1e-6,
        )
        nodes.append(
            RNode(
                # Distinct from mobject uids, which are not negative.
                uid=-((node.uid << 32) | int(index)) - 1,
                transform=IDENTITY,
                z_index=node.z_index,
                versions=face_versions,
                payload=path,
                fixed_in_frame=node.fixed_in_frame,
                fixed_orientation_center=node.fixed_orientation_center,
            )
        )
    return nodes


def face_outlines(corners: np.ndarray) -> np.ndarray:
    """The outlines of faces with corners of shape ``(m, k, 3)``: each side a
    straight cubic curve, as :meth:`.VMobject.set_points_as_corners` makes them.
    """
    following = np.roll(corners, -1, axis=1)
    return interpolate(
        corners[:, :, None, :], following[:, :, None, :], _THIRDS[:, None]
    ).reshape(len(corners), -1, 3)


def face_colours(mesh: RMesh, faces: np.ndarray) -> np.ndarray:
    """One colour per face: the texture at its middle, or the mean of its corners."""
    rgbas = np.asarray(mesh.rgbas, dtype=float)
    count = len(mesh.points)
    texture = np.asarray(mesh.texture)
    if len(mesh.uvs) == count and texture.size:
        height, width = texture.shape[:2]
        uv = np.asarray(mesh.uvs)[faces].mean(axis=1)
        x = np.clip((uv[:, 0] * width).astype(int), 0, width - 1)
        y = np.clip((uv[:, 1] * height).astype(int), 0, height - 1)
        colours = texture[y, x].astype(float) / 255
        colours[:, 3] *= rgbas[:, 3].mean() if len(rgbas) != count else 1
        return colours
    if len(rgbas) == count:
        return rgbas[faces].mean(axis=1)
    return np.repeat(rgbas[:1], len(faces), axis=0)


def _lit(
    colours: np.ndarray,
    corners: np.ndarray,
    centers: np.ndarray,
    gloss: float,
    shadow: float,
    camera: Camera,
) -> np.ndarray:
    """Colours lit as the mesh shader lights them, at each face's center."""
    if corners.shape[1] >= 4:
        normals = np.cross(corners[:, 2] - corners[:, 0], corners[:, 3] - corners[:, 1])
    else:
        normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    rotation = camera._view_rotation()
    normals = normals @ rotation.T
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(
        normals,
        lengths,
        out=np.tile([0.0, 0.0, 1.0], (len(normals), 1)),
        where=lengths > 0,
    )
    # Treated as two-sided: the normal faces the camera.
    normals[normals[:, 2] < 0] *= -1
    points = (centers - np.asarray(camera.frame_center)) @ rotation.T
    light = rotation @ camera._light_position()
    to_camera = _unit(np.array([0.0, 0.0, 6.0]) - points)
    to_light = light - points
    along = np.sum(to_light * normals, axis=1, keepdims=True)
    reflection = _unit(-to_light + 2 * normals * along)
    shine = gloss * np.exp(-3 * (1 - np.sum(reflection * to_camera, axis=1)) ** 2)
    facing = np.maximum(np.sum(_unit(to_light) * normals, axis=1), 0)
    darkening = (1 - shadow) + facing * shadow
    lit = colours.copy()
    lit[:, :3] = darkening[:, None] * (
        colours[:, :3] * (1 - shine[:, None]) + shine[:, None]
    )
    return lit


def _unit(vectors: np.ndarray) -> np.ndarray:
    lengths = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(lengths > 0, lengths, 1)
