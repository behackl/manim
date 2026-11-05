"""What a renderer is given to draw a frame, and the drawing methods used by Manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import numpy as np

    from manim.mobject.mobject import Mobject
    from manim.scene.scene import Scene
    from manim.typing import Point3D, RGBAPixelArray
    from manim.utils.color import ManimColor

__all__ = ["CameraState", "RenderConfig", "RendererCapabilities"]


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
class RenderConfig:
    """What a renderer is given next to the render snapshots of one frame."""

    pixel_width: int
    pixel_height: int
    background_color: ManimColor
    background_opacity: float
    camera: CameraState
    background_image: str | None = None
    """An image file shown behind everything, scaled to the frame (Cairo only)."""


class _AnimationRenderer(Protocol):
    """Draw frames and display them in a preview window at Manager's request.

    Manager prepares animations, checks the cache, advances animation time, and
    sends frames to the writer. The renderer prepares its drawing resources and
    uses wall-clock time to pace its live preview.
    """

    def _animation_cache_identity(self, scene: Scene) -> tuple[str, Any]: ...

    def _start_animation(self) -> None: ...

    def _prepare_animation(self, scene: Scene) -> None: ...

    def render(
        self, scene: Scene, frame_offset: float, moving_mobjects: list[Mobject], /
    ) -> None: ...

    def get_frame(self) -> RGBAPixelArray: ...

    def _present_frame(self, scene: Scene, frame_offset: float) -> None: ...

    def _present_frozen_frame(self, scene: Scene, duration: float) -> None: ...
