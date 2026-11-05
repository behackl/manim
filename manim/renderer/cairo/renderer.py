from __future__ import annotations

import contextlib
from collections.abc import Iterable, Iterator, Sequence
from typing import TYPE_CHECKING, Any

from PIL import Image

from manim.camera import Camera

from ..._config import config
from ..._run.frames import frame_count
from ...mobject.mobject import Mobject, _AnimationBuilder
from ...scene.scene_file_writer import SceneFileWriter
from ...utils.iterables import list_update
from .. import _view
from .._execution import _RendererExecutionView
from .._reuse import PrefixMemo, node_key, view_key
from ..frame import FrameBuilder
from ..protocol import RenderConfig, RendererCapabilities
from ..snapshot import RMesh
from .mesh_faces import mesh_faces
from .rendering import _CairoDrawingContext, reusable_boundary
from .target import _CairoRasterSettings, _CairoRenderTarget

if TYPE_CHECKING:
    from manim._config.render_session import RenderSessionSpec
    from manim.animation.animation import Animation
    from manim.scene.scene import Scene

    from ...typing import RGBAPixelArray
    from ..snapshot import RCameraView, RNode

__all__ = ["CairoRenderer"]


class CairoRenderer(_RendererExecutionView):
    """A renderer using Cairo.

    The renderer draws the camera's view, including inset views, into image
    buffers. It manages the PyCairo drawing contexts and caches images of
    stationary mobjects. Construction saves the pixel dimensions; the buffers
    are allocated on the first draw or request for pixels.
    """

    capabilities = RendererCapabilities(live_preview=False)

    def __init__(
        self,
        camera_class: type[Camera] | None = None,
        camera: Camera | None = None,
        skip_animations: bool = False,
        *,
        _raster_settings: _CairoRasterSettings | None = None,
    ) -> None:
        if camera is not None and camera_class is not None:
            raise ValueError("Pass either camera or camera_class, not both.")
        camera_cls = camera_class if camera_class is not None else Camera
        self.camera = camera if camera is not None else camera_cls()
        self._initialize_execution(skip_animations)
        self._raster_settings = _raster_settings or _CairoRasterSettings(
            pixel_width=int(config["pixel_width"]),
            pixel_height=int(config["pixel_height"]),
            base_pixel_width=int(config["pixel_width"]),
            base_pixel_height=int(config["pixel_height"]),
        )
        self._target: _CairoRenderTarget | None = None
        self._sub_targets: dict[int, _CairoRenderTarget] = {}
        self._frame_builder: FrameBuilder | None = None
        # The drawing of the leading nodes of a frame of the whole scene that did
        # not change, and their keys.
        self._memo = PrefixMemo()
        self._saved_pixels: RGBAPixelArray | None = None
        self._closed = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("The Cairo renderer is closed.")

    def _get_target(self) -> _CairoRenderTarget:
        self._ensure_open()
        if self._target is None:
            self._target = _CairoRenderTarget(self._raster_settings)
        return self._target

    @property
    def pixel_size(self) -> tuple[int, int]:
        """The width and height in pixels of frames drawn for a scene."""
        settings = self._raster_settings
        return settings.pixel_width, settings.pixel_height

    def init_scene(
        self,
        scene: Scene,
        session_spec: RenderSessionSpec,
    ) -> None:
        self._ensure_open()
        if hasattr(self, "_scene"):
            raise RuntimeError("This renderer is already bound to a Scene.")
        self._scene = scene

    @property
    def file_writer(self) -> SceneFileWriter:
        """Return the scene manager's file writer, creating it if needed."""
        return self._scene._get_manager().file_writer

    def play(
        self,
        scene: Scene,
        *args: Animation | Mobject | _AnimationBuilder,
        **kwargs: Any,
    ) -> None:
        """Delegate playback to the scene's manager; prefer Scene.play for new code."""
        scene._get_manager().play(*args, **kwargs)

    def _animation_cache_identity(self, scene: Scene) -> tuple[str, Any]:
        return "cairo", ()

    def _start_animation(self) -> None:
        self._ensure_open()

    def _present_frame(self, scene: Scene, frame_offset: float) -> None:
        pass

    def _present_frozen_frame(self, scene: Scene, duration: float) -> None:
        pass

    def render(self, nodes: Sequence[RNode], config: RenderConfig, /) -> RGBAPixelArray:
        """Draw ``nodes`` as ``config`` sets them up; return the pixels.

        Camera views are drawn first, each into its own image, and shown on their
        nodes. The drawing of the leading nodes that did not change since the
        previous frame is copied instead of drawn again (see
        :mod:`manim.renderer._reuse`).
        """
        self._ensure_open()
        target = self._target_for(config)
        pictures = self._draw_camera_views(config)

        def resolve_image(node: RNode) -> RGBAPixelArray | None:
            view: RCameraView = node.payload  # type: ignore[assignment]
            # Copies of a view show the picture of the same camera.
            return pictures.get(node.uid, pictures.get(("camera", view.camera_id)))

        target.reset(config)
        context = _CairoDrawingContext(
            camera=config.camera, target=target, image_resolver=resolve_image
        )
        context.start_frame()
        self._draw_reusing(context, self._faces(nodes, config), config)
        return target.read_pixels()

    def _target_for(self, config: RenderConfig) -> _CairoRenderTarget:
        settings = self._raster_settings.resized(
            pixel_width=config.pixel_width, pixel_height=config.pixel_height
        )
        target = self._target
        if target is not None and target.settings != settings:
            target.close()
            target = self._target = None
        if target is None:
            target = self._target = _CairoRenderTarget(settings)
        return target

    def _draw_camera_views(self, config: RenderConfig) -> dict[Any, RGBAPixelArray]:
        """Draw each camera view into an image; return them by view uid and by
        ``("camera", camera_id)``.
        """
        pictures: dict[Any, RGBAPixelArray] = {}
        drawn = set()
        try:
            for view in config.camera_views:
                view_config = view.config
                settings = self._raster_settings.resized(
                    pixel_width=view_config.pixel_width,
                    pixel_height=view_config.pixel_height,
                )
                target = self._sub_targets.get(view.uid)
                if target is None or target.settings != settings:
                    if target is not None:
                        target.close()
                    target = self._sub_targets[view.uid] = _CairoRenderTarget(settings)
                target.reset(view_config)
                context = _CairoDrawingContext(
                    camera=view_config.camera,
                    target=target,
                    image_resolver=lambda node: None,
                )
                context.start_frame()
                context.draw_nodes(self._faces(view.nodes, view_config))
                pictures[view.uid] = pictures[("camera", view.camera_id)] = (
                    target.pixels
                )
                drawn.add(view.uid)
        finally:
            # Retire targets of removed views and of views whose drawing failed.
            for key in self._sub_targets.keys() - drawn:
                self._sub_targets.pop(key).close()
        return pictures

    @staticmethod
    def _faces(nodes: Sequence[RNode], config: RenderConfig) -> list[RNode]:
        """``nodes`` with meshes as their faces, sorted far to near for a
        perspective camera: Cairo paints in order.
        """
        camera = config.camera
        drawn: list[RNode] = []
        for node in nodes:
            if isinstance(node.payload, RMesh):
                drawn.extend(mesh_faces(node, camera))
            else:
                drawn.append(node)
        return _view.sort_for_display(camera, drawn)

    def _draw_reusing(
        self,
        context: _CairoDrawingContext,
        nodes: list[RNode],
        config: RenderConfig,
    ) -> None:
        """Draw ``nodes`` over the target's background, copying the drawing of the
        leading nodes that did not change since they were saved.

        After a frame, the drawing of the nodes that did not change since the
        frame before is saved, to be copied in the next frames while they stay
        the same.
        """
        target = context.target
        keys = [node_key(node) for node in nodes]
        view = view_key(
            config.camera,
            (config.pixel_width, config.pixel_height),
            _background_key(config),
        )
        memo = self._memo
        start = memo.reusable(keys, view)
        if start:
            assert self._saved_pixels is not None
            target.set_pixels(self._saved_pixels)
        else:
            save = reusable_boundary(nodes, memo.worth_saving(keys, view))
            if save:
                context.draw_nodes(nodes[:save])
                self._saved_pixels = target.read_pixels()
                memo.saved(keys[:save], view)
                start = save
            else:
                memo.forget_saved()
                self._saved_pixels = None
        context.draw_nodes(nodes[start:])
        memo.drew(keys, view)

    def _frames(self) -> FrameBuilder:
        settings = self._raster_settings
        if self._frame_builder is None:
            self._frame_builder = FrameBuilder(
                settings.pixel_width, settings.pixel_height
            )
        return self._frame_builder

    def update_frame(
        self,
        scene: Scene,
        mobjects: Iterable[Mobject] | None = None,
        include_submobjects: bool = True,
        ignore_skipping: bool = True,
        **kwargs: Any,
    ) -> None:
        """Draw the scene's current state into the renderer's image buffer."""
        self._ensure_open()
        if self.skip_animations and not ignore_skipping:
            return
        if not mobjects:
            mobjects = list_update(scene.mobjects, scene.foreground_mobjects)
        self.render(*self._frames().build(self.camera, mobjects))

    def render_mobjects(
        self,
        mobjects: Iterable[Mobject],
        *,
        camera: Camera | None = None,
    ) -> None:
        """Draw the supplied mobjects into the renderer's image buffer."""
        self.render(
            *self._frames().build(self.camera if camera is None else camera, mobjects)
        )

    def render_scene(self, scene: Scene, time: float) -> None:
        # Manager advances animation time and sends the pixels to the writer.
        self.update_frame(scene)

    def get_frame(self) -> RGBAPixelArray:
        """Copy the current image to an RGBA array, with row zero at the top."""
        return self._get_target().read_pixels()

    @contextlib.contextmanager
    def _scene_images(self) -> Iterator[None]:
        """See OpenGLRenderer._scene_images; Cairo images are cheap to set up."""
        yield

    def _get_scene_image(self, scene: Scene) -> Image.Image:
        """Draw a snapshot with a temporary renderer at the existing resolution."""
        renderer = CairoRenderer(
            camera=self.camera, _raster_settings=self._raster_settings
        )
        try:
            renderer.render_mobjects(
                list_update(scene.mobjects, scene.foreground_mobjects)
            )
            return renderer.get_image()
        finally:
            renderer.close()

    def get_image(self) -> Image.Image:
        """Return the current target as a PIL image."""
        return Image.fromarray(self.get_frame())

    def add_frame(self, frame: RGBAPixelArray, num_frames: int = 1) -> None:
        self._ensure_open()
        self._scene._get_manager()._legacy_add_frame(frame, num_frames)

    def freeze_current_frame(self, duration: float) -> None:
        self._ensure_open()
        manager = self._scene._get_manager()
        # Evaluation draws frames only when they are requested, without a target.
        manager._legacy_add_frame(
            None if manager._evaluating else self.get_frame(),
            frame_count(duration, self._scene.session_spec.frame_rate),
        )

    def show_frame(self, scene: Scene) -> None:
        self.update_frame(scene, ignore_skipping=True)
        self.get_image().show()

    def update_skipping_status(self) -> None:
        self._scene._get_manager()._update_skipping_status()

    def open(self) -> None:
        """Check that the renderer can draw.

        Cairo creates its image buffers when it first draws, so there is nothing
        to allocate here. The method exists so that callers can open any
        renderer before :meth:`.Scene.setup` runs.
        """
        self._ensure_open()

    def close(self) -> None:
        """Close the renderer and release its image buffers and drawing contexts."""
        if self._closed:
            return
        self._closed = True
        if self._target is not None:
            self._target.close()
        for target in self._sub_targets.values():
            target.close()
        self._sub_targets.clear()
        self._memo.clear()
        self._saved_pixels = None


def _background_key(config: RenderConfig) -> tuple[Any, ...]:
    return (
        config.background_image,
        tuple(config.background_color.to_rgba_with_alpha(config.background_opacity)),
    )
