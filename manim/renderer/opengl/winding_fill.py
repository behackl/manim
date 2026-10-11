"""Fill paths from the winding number of their own curves.

Each curve's signed coverage is accumulated into a multisampled buffer and the result
coloured once, in two steps:

1. Two triangles per quadratic piece are rasterized into a float buffer: a fan
   triangle back to the first point of the piece's subpath, and one hugging the curve.
   Their contributions are added with the sign of which way they face once projected,
   so every pixel ends up holding the winding number of the path around it. Holes and
   self-intersections follow from that number; nothing is triangulated.
2. The buffer is resolved once: pixels with a nonzero winding are coloured, each
   path's fill opacity applied exactly once (it is accumulated separately, weighted
   by coverage, and divided back out).

A group's paths share both steps; the caller only groups paths that do not overlap or
are opaque and of one colour, where sharing gives the same pixels.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import moderngl
import numpy as np

from .shader import Shader

if TYPE_CHECKING:
    from collections.abc import Sequence

    from manim.renderer.snapshot import RNode, RPath

    from .drawing import DrawTarget, _Geometry
    from .renderer import OpenGLRenderer

__all__ = ["WindingFill"]

# Corner order per piece: the fan triangle first, then the one hugging the curve.
_CORNER_UV = np.array(
    [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.5, 0.0], [1.0, 1.0]],
    dtype=np.float32,
)
_CORNER_FILL_ALL = np.array([1.0, 1.0, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
_VERTEX_DTYPE = [
    ("point", np.float32, (3,)),
    ("corner_uv", np.float32, (2,)),
    ("fill_all", np.float32),
    ("color", np.float32, (4,)),
]
# Coverage is averaged over samples, which is what antialiases the edges.
_REQUESTED_SAMPLES = 4


def pack(
    geometry: Sequence[_Geometry],
    colours: list[tuple[np.ndarray, tuple[np.ndarray, np.ndarray] | None]],
) -> np.ndarray:
    """The two triangles per quadratic piece of several paths, built in one pass."""
    from .drawing import _colours, _concatenate

    quads, counts, offsets = _concatenate(geometry)
    subpath_start = np.concatenate(
        [g.subpath_start + offset for g, offset in zip(geometry, offsets, strict=True)]
    )
    base = quads[subpath_start, 0]
    starts, handles, ends = quads[:, 0], quads[:, 1], quads[:, 2]
    vertices = np.empty((len(quads), 6), dtype=_VERTEX_DTYPE)
    corners = np.stack((base, starts, ends, starts, handles, ends), axis=1)
    vertices["point"] = corners
    vertices["corner_uv"] = _CORNER_UV
    vertices["fill_all"] = _CORNER_FILL_ALL
    vertices["color"] = _colours(colours, corners.reshape(-1, 3), 6 * counts).reshape(
        len(quads), 6, 4
    )
    return vertices.reshape(-1)


class WindingFill:
    """Owns the buffers and programs used to fill by winding number.

    The GPU resources follow the renderer's context and are released with it.
    """

    def __init__(self, renderer: OpenGLRenderer) -> None:
        self._renderer = renderer
        self._size: tuple[int, int] | None = None
        self._accumulation: moderngl.Framebuffer | None = None
        self._accumulation_texture: moderngl.Texture | None = None
        self._opacity_texture: moderngl.Texture | None = None
        self._corners: moderngl.Buffer | None = None
        self._resolve_array: moderngl.VertexArray | None = None
        self.samples = 0

    def _ensure_buffers(self, size: tuple[int, int]) -> None:
        if self._size == size:
            return
        self.release()
        context = self._renderer.context
        self.samples = min(_REQUESTED_SAMPLES, context.max_samples)
        # Half floats: coverage sums stay small. The texture is sampled directly,
        # so the samples never have to be resolved into a second buffer.
        self._accumulation_texture = context.texture(
            size, components=4, samples=self.samples, dtype="f2"
        )
        self._opacity_texture = context.texture(
            size, components=1, samples=self.samples, dtype="f2"
        )
        self._accumulation = context.framebuffer(
            color_attachments=[self._accumulation_texture, self._opacity_texture]
        )
        self._corners = context.buffer(
            np.array([-1, -1, 3, -1, -1, 3], dtype=np.float32).tobytes()
        )
        self._resolve_array = context.vertex_array(
            Shader(context, name="winding_fill_resolve").shader_program,
            [(self._corners, "2f", "corner")],
        )
        self._size = size
        self._renderer._resources.callback(self.release)

    def release(self) -> None:
        """Release the GPU objects; safe to call more than once."""
        for resource in (
            self._resolve_array,
            self._corners,
            self._accumulation,
            self._accumulation_texture,
            self._opacity_texture,
        ):
            if resource is not None and not isinstance(
                resource.mglo, moderngl.InvalidObject
            ):
                resource.release()
        self._resolve_array = None
        self._corners = None
        self._accumulation = None
        self._accumulation_texture = None
        self._opacity_texture = None
        self._size = None

    def draw(
        self,
        nodes: Sequence[RNode],
        geometry: Sequence[_Geometry],
        target: DrawTarget,
        scissor: tuple[int, int, int, int] | None = None,
    ) -> None:
        """Accumulate one group's coverage and colour it into the frame.

        ``scissor`` limits clearing and resolving to a pixel rectangle
        ``(x, y, width, height)`` that contains the group.
        """
        camera = target.camera
        filled, colours = [], []
        for node, geo in zip(nodes, geometry, strict=True):
            path: RPath = node.payload  # type: ignore[assignment]
            if len(geo.quads) == 0 or path.fill_rgbas[:, 3].max() == 0:
                continue
            filled.append(geo)
            colours.append((camera._shaded_rgbas(path, path.fill_rgbas), path.gradient))
        if not filled:
            return
        vertices = pack(filled, colours)
        renderer = self._renderer
        context = renderer.context
        self._ensure_buffers(target.size)
        assert self._accumulation is not None
        assert self._accumulation_texture is not None
        assert self._opacity_texture is not None
        assert self._resolve_array is not None

        shader = Shader(context, name="winding_fill")
        for name, value in target.uniforms.items():
            shader.set_uniform(name, value)

        buffer = context.buffer(vertices.tobytes())
        try:
            array = context.vertex_array(
                shader.shader_program,
                [(buffer, "3f 2f 1f 4f", *(field[0] for field in _VERTEX_DTYPE))],
            )
            try:
                # Coverage must add up rather than replace.
                context.disable(moderngl.DEPTH_TEST)
                context.enable(moderngl.BLEND)
                self._accumulation.use()
                self._accumulation.scissor = scissor
                self._accumulation.clear(0.0, 0.0, 0.0, 0.0)
                context.blend_equation = moderngl.FUNC_ADD
                context.blend_func = (moderngl.ONE, moderngl.ONE)
                array.render(moderngl.TRIANGLES)

                frame = target.framebuffer
                frame.use()
                frame.scissor = scissor
                context.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
                self._accumulation_texture.use(0)
                self._opacity_texture.use(1)
                program = self._resolve_array.program
                program["accumulated"].value = 0
                program["accumulated_opacity"].value = 1
                program["samples"].value = self.samples
                self._resolve_array.render(moderngl.TRIANGLES)
            finally:
                array.release()
                frame.scissor = None
                self._accumulation.scissor = None
        finally:
            buffer.release()
