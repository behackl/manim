from __future__ import annotations

import contextlib
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any

from ..._config import config
from .. import _view
from .._reuse import PrefixMemo, node_key, view_key
from ..protocol import RenderConfig, RendererCapabilities
from ..snapshot import RMesh
from .mesh_faces import mesh_faces
from .rendering import _CairoDrawingContext, reusable_boundary
from .target import _CairoRasterSettings, _CairoRenderTarget

if TYPE_CHECKING:
    from ...typing import RGBAPixelArray
    from ..snapshot import RCameraView, RNode

__all__ = ["CairoRenderer"]


class CairoRenderer:
    """A renderer using Cairo.

    The renderer draws the camera's view, including inset views, into image
    buffers. It manages the PyCairo drawing contexts and caches images of
    stationary mobjects. Construction saves the pixel dimensions; the buffers
    are allocated on the first draw or request for pixels.
    """

    capabilities = RendererCapabilities(live_preview=False)
    #: What tells this renderer's frames from another's, for the play cache.
    cache_identity: tuple[str, Any] = ("cairo", ())

    def __init__(
        self,
        *,
        _raster_settings: _CairoRasterSettings | None = None,
    ) -> None:
        self._raster_settings = _raster_settings or _CairoRasterSettings(
            pixel_width=int(config["pixel_width"]),
            pixel_height=int(config["pixel_height"]),
            base_pixel_width=int(config["pixel_width"]),
            base_pixel_height=int(config["pixel_height"]),
        )
        self._target: _CairoRenderTarget | None = None
        self._sub_targets: dict[int, _CairoRenderTarget] = {}
        # The drawing of the leading nodes of a frame of the whole scene that did
        # not change, and their keys.
        self._memo = PrefixMemo()
        self._saved_pixels: RGBAPixelArray | None = None
        self._closed = False
        #: Whether a scene draws with this renderer (one scene per renderer).
        self._scene_bound = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("The Cairo renderer is closed.")

    @property
    def pixel_size(self) -> tuple[int, int]:
        """The width and height in pixels of frames drawn for a scene."""
        settings = self._raster_settings
        return settings.pixel_width, settings.pixel_height

    def _start_animation(self) -> None:
        self._ensure_open()

    def present(self) -> None:
        """Nothing to show: Cairo has no preview window."""

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

    @contextlib.contextmanager
    def _scene_images(self) -> Iterator[None]:
        """See OpenGLRenderer._scene_images; Cairo images are cheap to set up."""
        yield

    def _image(self, nodes: Sequence[RNode], config: RenderConfig) -> RGBAPixelArray:
        """Draw a frame for inspection, apart from the frames of a render.

        A temporary renderer draws it, so that it works before the scene renders
        and after the renderer closed, and leaves the drawing kept for the next
        frame alone.
        """
        renderer = CairoRenderer(_raster_settings=self._raster_settings)
        try:
            return renderer.render(nodes, config)
        finally:
            renderer.close()

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
