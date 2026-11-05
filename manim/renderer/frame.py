"""What a renderer is given for one frame of a scene, made from the scene's mobjects
and camera.

The :class:`FrameBuilder` is the only place that reads mobjects and cameras for
drawing: renderers get the render snapshots and :class:`.RenderConfig` it makes, and
nothing else (see :class:`.Renderer`).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from manim.camera import Camera, MultiCamera
from manim.renderer.protocol import CameraView, RenderConfig
from manim.renderer.snapshot import Extractor

if TYPE_CHECKING:
    from manim.mobject.mobject import Mobject
    from manim.mobject.types.image_mobject import ImageMobjectFromCamera
    from manim.renderer.snapshot import RNode

__all__ = ["FrameBuilder"]


class FrameBuilder:
    """Makes the render snapshots and :class:`.RenderConfig` of frames.

    It keeps an :class:`.Extractor`, so that mobjects that did not change since the
    previous frame cost little; one builder serves all frames of a scene.

    Parameters
    ----------
    pixel_width, pixel_height
        The size of the frames in pixels.
    """

    def __init__(self, pixel_width: int, pixel_height: int) -> None:
        self.pixel_width = pixel_width
        self.pixel_height = pixel_height
        self._extractor = Extractor()

    def build(
        self, camera: Camera, mobjects: Iterable[Mobject]
    ) -> tuple[list[RNode], RenderConfig]:
        """The snapshots of ``mobjects`` (with their families) in drawing order, and
        the configuration of a frame that ``camera`` shows.
        """
        mobjects = list(mobjects)
        views: tuple[CameraView, ...] = ()
        if isinstance(camera, MultiCamera):
            views = tuple(
                self._view(camera, view, mobjects)
                for view in camera.image_mobjects_from_cameras
            )
        nodes = self.nodes(camera, mobjects)
        return nodes, self.config(
            camera, self.pixel_width, self.pixel_height, camera_views=views
        )

    def nodes(
        self,
        camera: Camera,
        mobjects: Iterable[Mobject],
        excluded_mobjects: Iterable[Mobject] = (),
    ) -> list[RNode]:
        """The snapshots ``camera`` shows: family order, stably sorted by z-index
        unless the camera says otherwise. Renderers that paint far to near sort by
        depth themselves.
        """
        return self._extractor.extract(
            mobjects,
            use_z_index=camera.use_z_index,
            excluded_mobjects=excluded_mobjects,
        )

    @staticmethod
    def config(
        camera: Camera,
        pixel_width: int,
        pixel_height: int,
        camera_views: tuple[CameraView, ...] = (),
    ) -> RenderConfig:
        return RenderConfig(
            pixel_width=pixel_width,
            pixel_height=pixel_height,
            background_color=camera.background_color,
            background_opacity=camera.background_opacity,
            camera=camera._state(),
            background_image=camera.background_image,
            camera_views=camera_views,
        )

    def _view(
        self,
        camera: Camera,
        view: ImageMobjectFromCamera,
        mobjects: Sequence[Mobject],
    ) -> CameraView:
        # The picture has the resolution the view has in the frame.
        pixel_width = max(1, int(self.pixel_width * view.width / camera.frame_width))
        pixel_height = max(
            1, int(self.pixel_height * view.height / camera.frame_height)
        )
        view_camera = view.camera
        return CameraView(
            uid=view.uid,
            camera_id=id(view_camera),
            config=self.config(view_camera, pixel_width, pixel_height),
            # A view does not show itself.
            nodes=self.nodes(view_camera, mobjects, excluded_mobjects=[view]),
        )
