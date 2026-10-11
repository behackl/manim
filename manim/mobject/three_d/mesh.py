"""Mobjects made of triangles: smooth surfaces with lighting and textures.

These are drawn by the OpenGL renderer as meshes, with depth testing and lighting. The
Cairo renderer cannot draw them yet; use :class:`.Surface` there.
"""

from __future__ import annotations

__all__ = ["MeshMobject", "ParametricSurface"]

import itertools as it
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image

from manim.mobject.fields import ArrayField, Field
from manim.mobject.mobject import Mobject
from manim.mobject.types.vectorized_mobject import VGroup, VMobject
from manim.utils.color import (
    BLUE_D,
    BLUE_E,
    LIGHT_GREY,
    ManimColor,
    ParsableManimColor,
    color_to_rgba,
    interpolate_color,
)
from manim.utils.images import get_full_raster_image_path
from manim.utils.iterables import stretch_array_to_length

if TYPE_CHECKING:
    from typing import Self

    from manim.mobject.graphing.coordinate_systems import CoordinateSystem
    from manim.typing import Point3D, Point3D_Array


class MeshMobject(Mobject):
    """A mobject made of triangles.

    Parameters
    ----------
    points
        The vertices, shape ``(n, 3)``.
    triangles
        Indices into ``points``, three per triangle, shape ``(m, 3)``.
    color, opacity
        One colour for the whole mesh. :meth:`set_vertex_colors` sets one per vertex.
    gloss, shadow
        Lighting: the strength of highlights and of the darkening of faces turned away
        from the light. Zero for both draws flat colours.
    depth_test
        Whether the mesh hides what is behind it, independently of drawing order.
    texture
        An image drawn onto the mesh, a path or an RGBA pixel array. Needs ``uvs``.
    uvs
        Texture coordinates of the vertices, shape ``(n, 2)``, from ``(0, 0)`` at the
        upper left of the image to ``(1, 1)`` at the lower right.
    shade_in_3d
        Shade each face as a :class:`.ThreeDCamera` shades 3D paths (see
        :meth:`.VMobject.set_shade_in_3d`), instead of with ``gloss`` and ``shadow``.
    stroke_color, stroke_width, stroke_opacity
        The outlines of the faces (see :attr:`faces`); no outlines by default.
    """

    triangles: ArrayField[np.ndarray] = ArrayField(np.int32)
    #: Colours: one row for the whole mesh, or one per vertex.
    rgbas: ArrayField[np.ndarray] = ArrayField(np.float64)
    uvs: ArrayField[np.ndarray] = ArrayField(np.float64)
    texture: ArrayField[np.ndarray] = ArrayField(np.uint8)
    #: Polygons, as vertex indices in order around each, that the mesh is made of
    #: (quads for parametric surfaces). Empty means the triangles.
    faces: ArrayField[np.ndarray] = ArrayField(np.int32)
    gloss: Field[float] = Field()
    shadow: Field[float] = Field()
    depth_test: Field[bool] = Field()
    shade_in_3d: Field[bool] = Field()
    stroke_rgbas: ArrayField[np.ndarray] = ArrayField(np.float64)
    stroke_width: Field[float] = Field()

    def __init__(
        self,
        points: Point3D_Array | None = None,
        triangles: np.ndarray | None = None,
        color: ParsableManimColor = BLUE_D,
        opacity: float = 1.0,
        gloss: float = 0.3,
        shadow: float = 0.4,
        depth_test: bool = True,
        texture: str | Path | np.ndarray | None = None,
        uvs: np.ndarray | None = None,
        shade_in_3d: bool = False,
        stroke_color: ParsableManimColor = LIGHT_GREY,
        stroke_width: float = 0,
        stroke_opacity: float = 1.0,
        **kwargs: Any,
    ) -> None:
        self.triangles = np.zeros((0, 3)) if triangles is None else triangles
        self.faces = np.zeros((0, 3))
        self.shade_in_3d = shade_in_3d
        self.stroke_rgbas = [color_to_rgba(stroke_color, stroke_opacity)]
        self.stroke_width = stroke_width
        self.rgbas = [color_to_rgba(color, opacity)]
        self.uvs = np.zeros((0, 2)) if uvs is None else uvs
        self.texture = _load_texture(texture)
        self.gloss = gloss
        self.shadow = shadow
        self.depth_test = depth_test
        super().__init__(color=color, **kwargs)
        if points is not None:
            self.points = points

    # Colours

    def set_color(
        self,
        color: ParsableManimColor = BLUE_D,
        alpha: float | None = None,
        family: bool = True,
    ) -> Self:
        opacity = self.rgbas[:, 3].max() if alpha is None else alpha
        self.rgbas = [color_to_rgba(color, opacity)]
        self.color = ManimColor(color)
        return self

    def set_opacity(self, opacity: float, family: bool = True) -> Self:
        rgbas = np.array(self.rgbas)
        rgbas[:, 3] = opacity
        self.rgbas = rgbas
        return self

    def fade(self, darkness: float = 0.5, family: bool = True) -> Self:
        rgbas = np.array(self.rgbas)
        rgbas[:, 3] *= 1 - darkness
        self.rgbas = rgbas
        return super().fade(darkness, family)

    def set_stroke(
        self,
        color: ParsableManimColor | None = None,
        width: float | None = None,
        opacity: float | None = None,
        family: bool = True,
    ) -> Self:
        """Set the outlines of the faces."""
        rgba = self.stroke_rgbas[0]
        self.stroke_rgbas = [
            color_to_rgba(
                ManimColor(rgba[:3]) if color is None else color,
                rgba[3] if opacity is None else opacity,
            )
        ]
        if width is not None:
            self.stroke_width = width
        return self

    def get_faces(self) -> np.ndarray:
        """The polygons of the mesh: :attr:`faces`, or else the triangles."""
        return self.faces if len(self.faces) else self.triangles

    def set_vertex_colors(self, rgbas: np.ndarray) -> Self:
        """Give every vertex its own colour, as an ``(n, 4)`` array of RGBA values."""
        self.rgbas = rgbas
        return self

    def set_color_by_xyz_func(
        self,
        func: Callable[[Point3D_Array], np.ndarray],
        colorscale: Sequence[ParsableManimColor],
        min_value: float = 0.0,
        max_value: float = 1.0,
    ) -> Self:
        """Colour the vertices by a function of their position.

        Parameters
        ----------
        func
            Maps the vertices, shape ``(n, 3)``, to one value each.
        colorscale
            Colours evenly spread from ``min_value`` to ``max_value``.
        """
        values = np.asarray(func(self.points), dtype=float)
        return self.set_vertex_colors(
            _colorscale(values, colorscale, min_value, max_value, self.rgbas[0, 3])
        )

    # Animation

    def align_points(self, mobject: Mobject) -> Self:
        if not isinstance(mobject, MeshMobject) or (
            self.points.shape != mobject.points.shape
            or not np.array_equal(self.triangles, mobject.triangles)
        ):
            raise ValueError(
                "Meshes can only be transformed into meshes with the same triangles "
                "(for parametric surfaces: the same resolution)."
            )
        return self

    def interpolate_color(
        self, mobject1: Mobject, mobject2: Mobject, alpha: float
    ) -> Self:
        assert isinstance(mobject1, MeshMobject)
        assert isinstance(mobject2, MeshMobject)
        start, end = mobject1.rgbas, mobject2.rgbas
        if len(start) != len(end):
            length = max(len(start), len(end))
            start = stretch_array_to_length(start, length)
            end = stretch_array_to_length(end, length)
        self.rgbas = (1 - alpha) * start + alpha * end
        self.gloss = (1 - alpha) * mobject1.gloss + alpha * mobject2.gloss
        self.shadow = (1 - alpha) * mobject1.shadow + alpha * mobject2.shadow
        self.stroke_rgbas = (
            1 - alpha
        ) * mobject1.stroke_rgbas + alpha * mobject2.stroke_rgbas
        self.stroke_width = (
            1 - alpha
        ) * mobject1.stroke_width + alpha * mobject2.stroke_width
        return self

    def pointwise_become_partial(self, mobject: Mobject, a: float, b: float) -> Self:
        """Show the triangles of ``mobject`` from proportion ``a`` to ``b``, in order."""
        assert isinstance(mobject, MeshMobject)
        count = len(mobject.triangles)
        low, high = int(a * count), int(np.ceil(b * count))
        self.points = mobject.points
        self.triangles = mobject.triangles[low:high]
        faces = mobject.faces
        if len(faces):
            # Faces made of triangles in order, the same number each.
            per_face = count // len(faces)
            self.faces = faces[low // per_face : -(-high // per_face)]
        return self

    # Shape

    def get_wireframe(
        self, color: ParsableManimColor = LIGHT_GREY, stroke_width: float = 1
    ) -> VGroup:
        """The edges of the triangles, as lines drawn by both renderers."""
        edges = np.sort(self.triangles[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2), axis=1)
        lines = VGroup()
        for start, end in np.unique(edges, axis=0):
            lines.add(VMobject().set_points_as_corners(self.points[[start, end]]))
        return lines.set_stroke(color, stroke_width)


class ParametricSurface(MeshMobject):
    """A surface given by a function of two parameters, drawn as a smooth mesh.

    Parameters
    ----------
    func
        Maps parameters ``(u, v)`` to a point in space.
    u_range, v_range
        The ranges of the parameters.
    resolution
        Number of steps in ``u`` and ``v``.
    flat
        Give every quad its own vertices, so that faces can have their own colour
        (needed for checkerboards) and are shaded flat.
    texture
        An image drawn onto the surface: ``u`` runs left to right across it, ``v``
        bottom to top.

    Examples
    --------
    .. code-block:: python

        sphere = ParametricSurface(
            lambda u, v: [np.cos(u) * np.sin(v), np.sin(u) * np.sin(v), np.cos(v)],
            u_range=[0, TAU],
            v_range=[0, PI],
        )
    """

    def __init__(
        self,
        func: Callable[[float, float], Point3D],
        u_range: Sequence[float] = (0, 1),
        v_range: Sequence[float] = (0, 1),
        resolution: int | Sequence[int] = 32,
        flat: bool = False,
        **kwargs: Any,
    ) -> None:
        self._func = func
        self.u_range = tuple(u_range)
        self.v_range = tuple(v_range)
        self.resolution = (
            (resolution, resolution)
            if isinstance(resolution, int)
            else tuple(resolution)
        )
        self.flat = flat
        super().__init__(**kwargs)

    def func(self, u: float, v: float) -> Point3D:
        """The point at parameters ``(u, v)``."""
        return self._func(u, v)

    def generate_points(self) -> Self:
        nu, nv = self.resolution
        us = np.linspace(*self.u_range, nu + 1)
        vs = np.linspace(*self.v_range, nv + 1)
        grid = np.array([[self.func(u, v) for v in vs] for u in us], dtype=float)
        uv = np.stack(np.meshgrid(us, vs, indexing="ij"), axis=-1)
        if self.flat:
            # Four vertices per quad: (u, v), (u + 1, v), (u, v + 1), (u + 1, v + 1).
            quads = [(i, j) for i in range(nu) for j in range(nv)]
            corners = [(0, 0), (1, 0), (0, 1), (1, 1)]
            points = np.array(
                [grid[i + di, j + dj] for i, j in quads for di, dj in corners]
            )
            params = np.array(
                [uv[i + di, j + dj] for i, j in quads for di, dj in corners]
            )
            base = 4 * np.arange(len(quads))[:, None]
            triangles = np.concatenate(
                (base + [0, 1, 2], base + [1, 3, 2]), axis=1
            ).reshape(-1, 3)
            faces = base + [0, 1, 3, 2]
        else:
            points = grid.reshape(-1, 3)
            params = uv.reshape(-1, 2)
            index = np.arange((nu + 1) * (nv + 1)).reshape(nu + 1, nv + 1)
            a, b = index[:-1, :-1].ravel(), index[1:, :-1].ravel()
            c, d = index[:-1, 1:].ravel(), index[1:, 1:].ravel()
            triangles = np.stack((a, b, c, b, d, c), axis=1).reshape(-1, 3)
            faces = np.stack((a, b, d, c), axis=1)
        self.points = points
        self.triangles = triangles
        self.faces = faces
        if len(self.texture):
            u0, u1 = self.u_range
            v0, v1 = self.v_range
            self.uvs = np.stack(
                ((params[:, 0] - u0) / (u1 - u0), 1 - (params[:, 1] - v0) / (v1 - v0)),
                axis=1,
            )
        return self

    def set_fill_by_checkerboard(
        self, *colors: ParsableManimColor, opacity: float | None = None
    ) -> Self:
        """Colour the quads alternately with ``colors`` (default: two blues).

        The surface is rebuilt with :attr:`flat` quads if it is not flat yet.
        """
        if not self.flat:
            self.flat = True
            self.generate_points()
        colors = colors or (BLUE_D, BLUE_E)
        alpha = self.rgbas[:, 3].max() if opacity is None else opacity
        nu, nv = self.resolution
        pattern = [
            color_to_rgba(colors[(i + j) % len(colors)], alpha)
            for i, j in it.product(range(nu), range(nv))
        ]
        return self.set_vertex_colors(np.repeat(pattern, 4, axis=0))

    def set_fill_by_value(
        self,
        axes: CoordinateSystem,
        colorscale: Sequence[ParsableManimColor],
        axis: int = 2,
    ) -> Self:
        """Colour the surface by one coordinate of its points, measured on ``axes``.

        Parameters
        ----------
        axes
            The axes the surface is plotted on.
        colorscale
            Colours evenly spread over the range of that coordinate on the axes.
        axis
            The coordinate: 0, 1 or 2 for x, y or z.
        """
        values = np.asarray(axes.point_to_coords(self.points))[:, axis]
        low, high = getattr(axes, ("x_range", "y_range", "z_range")[axis])[:2]
        return self.set_vertex_colors(
            _colorscale(values, colorscale, low, high, self.rgbas[0, 3])
        )

    def pointwise_become_partial(self, mobject: Mobject, a: float, b: float) -> Self:
        """Show the part of ``mobject`` from proportion ``a`` to ``b`` of ``v``.

        Points outside are moved onto the edge of the shown part, so the triangles stay
        the same and the partial surface can be animated like the whole one.
        """
        assert isinstance(mobject, ParametricSurface)
        if mobject.flat:
            return super().pointwise_become_partial(mobject, a, b)
        nu, nv = mobject.resolution
        grid = mobject.points.reshape(nu + 1, nv + 1, 3).copy()
        low, high = a * nv, b * nv
        for bound, side in ((low, "low"), (high, "high")):
            index = min(int(bound), nv - 1)
            residue = bound - index
            edge = (1 - residue) * grid[:, index] + residue * grid[:, index + 1]
            if side == "low":
                grid[:, : index + 1] = edge[:, None]
            else:
                grid[:, index + 1 :] = edge[:, None]
        self.points = grid.reshape(-1, 3)
        self.triangles = mobject.triangles
        self.faces = mobject.faces
        return self

    def get_wireframe(
        self, color: ParsableManimColor = LIGHT_GREY, stroke_width: float = 1
    ) -> VGroup:
        """The parameter lines of constant ``u`` and ``v``."""
        nu, nv = self.resolution
        us = np.linspace(*self.u_range, nu + 1)
        vs = np.linspace(*self.v_range, nv + 1)
        lines = VGroup()
        for u in us:
            lines.add(VMobject().set_points_as_corners([self.func(u, v) for v in vs]))
        for v in vs:
            lines.add(VMobject().set_points_as_corners([self.func(u, v) for u in us]))
        return lines.set_stroke(color, stroke_width)


def _load_texture(texture: str | Path | np.ndarray | None) -> np.ndarray:
    if texture is None:
        return np.zeros((0, 0, 4), dtype=np.uint8)
    if isinstance(texture, (str, Path)):
        path = get_full_raster_image_path(texture)
        return np.asarray(Image.open(path).convert("RGBA"))
    pixels = np.asarray(texture)
    if pixels.ndim == 3 and pixels.shape[2] == 3:
        alpha = np.full(pixels.shape[:2] + (1,), 255, dtype=pixels.dtype)
        pixels = np.concatenate((pixels, alpha), axis=2)
    return pixels


def _colorscale(
    values: np.ndarray,
    colorscale: Iterable[ParsableManimColor],
    low: float,
    high: float,
    alpha: float,
) -> np.ndarray:
    """RGBA values for ``values``, from colours evenly spread from ``low`` to ``high``."""
    colors = [ManimColor(c) for c in colorscale]
    t = np.clip((values - low) / (high - low), 0, 1) * (len(colors) - 1)
    index = np.minimum(t.astype(int), len(colors) - 2)
    rgbas = np.array(
        [
            interpolate_color(colors[i], colors[i + 1], f).to_rgba()
            for i, f in zip(index, t - index, strict=True)
        ]
    )
    rgbas[:, 3] = alpha
    return rgbas
