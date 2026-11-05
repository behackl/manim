"""What a renderer is given to draw a frame, and the drawing methods used by Manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy as np

    from manim.renderer.snapshot import RNode
    from manim.typing import Point3D, RGBAPixelArray
    from manim.utils.color import ManimColor

__all__ = [
    "CameraState",
    "CameraView",
    "RenderConfig",
    "Renderer",
    "RendererCapabilities",
]


@dataclass(frozen=True, slots=True)
class RendererCapabilities:
    """Optional session features implemented by a renderer."""

    live_preview: bool = False


@dataclass(frozen=True, slots=True, eq=False)
class CameraState:
    """A camera at one time, as plain values: what renderers draw from.

    Made by :meth:`.Camera._state`; renderers never read camera objects.
    """

    center: Point3D
    """The center of the camera's frame in scene coordinates."""
    frame_width: float
    """The width of the frame in scene units."""
    frame_height: float
    """The height of the frame in scene units."""
    rotation: np.ndarray
    """The rotation from scene to view coordinates (3x3); the view looks along -z."""
    focal_distance: float | None
    """The distance of the eye from the frame center, for the perspective of a
    :class:`.ThreeDCamera`; ``None`` for a flat view, which sorts nothing by depth."""
    zoom: float
    """The factor that projected points are scaled by (1 for a flat view)."""
    light: Point3D
    """Where meshes are lit from."""
    shade_3d: bool
    """Whether ``shade_in_3d`` paths and faces are shaded towards :attr:`light`."""
    default_frame_width: float
    """The frame width the scene was configured with: mobjects fixed in frame are
    drawn as if the frame had this width and were centered at the origin."""


@dataclass(frozen=True, slots=True, eq=False)
class CameraView:
    """What one camera view (an :class:`.ImageMobjectFromCamera`) shows in a frame.

    The renderer draws :attr:`nodes` as :attr:`config` sets them up, and shows the
    picture on the frame's node with :attr:`uid` (an :class:`.RCameraView`), and
    on the copies of that node, which have the same :attr:`camera_id`.
    """

    uid: int
    camera_id: int
    config: RenderConfig
    nodes: Sequence[RNode]


@dataclass(frozen=True, slots=True, eq=False)
class RenderConfig:
    """What a renderer is given next to the render snapshots of one frame."""

    pixel_width: int
    pixel_height: int
    background_color: ManimColor
    background_opacity: float
    camera: CameraState
    background_image: str | None = None
    """An image file shown behind everything, scaled to the frame (Cairo only)."""
    camera_views: tuple[CameraView, ...] = ()
    """The camera views of the frame, drawn before it. They have no views."""


class Renderer(Protocol):
    """Draws frames: render snapshots and a :class:`RenderConfig` in, pixels out.

    A renderer never reads a scene, a mobject, a camera or the animation clock;
    :class:`.FrameBuilder` makes what it is given. It may keep what it built
    between frames, keyed by :attr:`.RNode.uid` and :attr:`.RNode.versions`.
    """

    def render(self, nodes: Sequence[RNode], config: RenderConfig, /) -> RGBAPixelArray:
        """Draw ``nodes`` in order, as ``config`` sets them up; return the pixels,
        RGBA with row zero at the top.
        """
        ...

    def close(self) -> None:
        """Release what the renderer holds; it does not draw afterwards."""
        ...
