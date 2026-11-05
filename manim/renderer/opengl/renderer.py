from __future__ import annotations

import contextlib
import threading
import typing
import weakref
from typing import TYPE_CHECKING, Any

import moderngl
import numpy as np
from moderngl import Framebuffer

from manim._config import config, logger
from manim.typing import Point3D

from ...constants import *
from .. import _view as _views
from ..protocol import RenderConfig, RendererCapabilities
from .drawing import DrawTarget, SnapshotDrawing
from .shader import shader_program_cache
from .window_settings import _WindowSettings

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from manim._config.render_session import RenderSessionSpec
    from manim.scene.scene import Scene
    from manim.typing import (
        RGBAPixelArray,
    )

    from ..protocol import CameraState
    from ..snapshot import RNode
    from .window import Window

__all__ = ["OpenGLRenderer"]

# Remember the active Manim renderer on each thread so captures can restore it.
_active_context = threading.local()


class OpenGLRenderer:
    """A renderer drawing with OpenGL, which can show frames in a preview window.

    Frames are drawn offscreen at the scene's pixel size; :meth:`present` shows the
    last one in the window.

    Attributes
    ----------
    anti_alias_width : float
        The width used for anti-aliasing in pixel units.
    window : Window | None
        The preview window, if any.
    """

    capabilities = RendererCapabilities(live_preview=True)
    #: What tells this renderer's frames from another's, for the play cache.
    cache_identity: tuple[str, Any] = ("opengl", {"anti_alias_width": 1.5})

    def __init__(self) -> None:
        # Measured in pixel widths, used for vector graphics; part of cache_identity.
        self.anti_alias_width = 1.5

        self.perspective_uniforms: dict[str, Any] = {}
        # Set for each frame by _set_view.
        self.camera_view: _CameraView
        self._camera_state: CameraState
        self._snapshot_drawing = SnapshotDrawing(self)
        self._camera_view_targets: dict[int, _ViewTarget] = {}
        self.window: Window | None = None
        self._context: moderngl.Context | None = None
        self._frame_buffer_object: Framebuffer | None = None
        self._context_thread: int | None = None
        self._capturing_image = False
        self._keep_image_renderer = False
        self._image_renderer: OpenGLRenderer | None = None
        self._closed = False
        #: Whether a scene draws with this renderer (one scene per renderer).
        self._scene_bound = False
        self._retiring = False
        self._resources = contextlib.ExitStack()
        self._previous_renderer: weakref.ReferenceType[OpenGLRenderer] | None = None

    def init_scene(
        self,
        scene: Scene,
        session_spec: RenderSessionSpec,
    ) -> None:
        """
        Save the scene's pixel dimensions and preview-window settings.

        :meth:`open` uses these settings to create the OpenGL context and
        framebuffer. The manager calls it before the scene's ``setup()`` method;
        an explicit request for GPU resources, such as :attr:`context`, opens
        them sooner.

        Parameters
        ----------
        scene : Scene
            The scene to be rendered
        """
        self._ensure_not_closed()
        # The window sends input to the scene and shows it as its camera sees it.
        self._window_input = scene
        self._window_camera = scene.camera
        self._pixel_size = (int(config.pixel_width), int(config.pixel_height))
        self._wireframe = config.enable_wireframe
        self._window_settings = (
            _WindowSettings.from_config(config)
            if self.should_create_window(session_spec)
            else None
        )

    def _ensure_not_closed(self) -> None:
        if self._closed or self._retiring:
            raise RuntimeError("The OpenGL renderer is closed or retiring.")

    def open(self) -> None:
        """Create or activate the scene's OpenGL context.

        The first call creates the context, framebuffer, and preview window if
        requested. Further calls activate the same context. Use and close these
        resources on the thread that first opened them.
        """
        self._ensure_not_closed()
        if self._context is not None:
            if isinstance(self._context.mglo, moderngl.InvalidObject):
                raise RuntimeError("The OpenGL context was released externally.")
            if self.window is not None and self.window._window.context is None:
                raise RuntimeError("The OpenGL window was destroyed externally.")
            if self._context_thread != threading.get_ident():
                raise RuntimeError(
                    "OpenGL resources must be used on their owning thread."
                )
            self._activate_context()
            return
        if not hasattr(self, "_pixel_size"):
            raise RuntimeError("Bind an OpenGL scene before opening its resources.")
        previous = getattr(_active_context, "renderer", None)
        resources = contextlib.ExitStack()
        try:
            window = None
            if self._window_settings is not None:
                # Import here: only preview windows need pyglet and screeninfo.
                from .window import Window

                window = Window(
                    self._window_input,
                    to_scene=self._scene_point,
                    _settings=self._window_settings,
                )
                resources.callback(window.close)
                # Closing the window also releases its context.
                context = window.ctx
            else:
                try:
                    context = moderngl.create_context(standalone=True)
                except Exception:
                    context = moderngl.create_context(standalone=True, backend="egl")
                resources.callback(context.release)
            # Frames are drawn offscreen at the scene's size; a window shows them.
            frame = self.get_frame_buffer_object(context, 0, size=self._pixel_size)
            for color in frame.color_attachments:
                resources.callback(color.release)
            if frame.depth_attachment is not None:
                resources.callback(frame.depth_attachment.release)
            resources.callback(frame.release)
            frame.use()
            context.enable(moderngl.BLEND)
            context.wireframe = self._wireframe
            context.blend_func = (
                moderngl.SRC_ALPHA,
                moderngl.ONE_MINUS_SRC_ALPHA,
                moderngl.ONE,
                moderngl.ONE,
            )
        except BaseException:
            try:
                resources.close()
            except BaseException:
                logger.exception("Failed to roll back OpenGL initialization")
            try:
                self._restore_renderer(previous)
            except BaseException:
                logger.exception("Failed to restore the previous OpenGL context")
            raise
        # Store the resources after initialization succeeds.
        self.window = window
        self._context = context
        self._frame_buffer_object = frame
        self._context_thread = threading.get_ident()
        self._capturing_image = False
        self._resources = resources.pop_all()
        self._previous_renderer = previous
        _active_context.renderer = weakref.ref(self)

    def _activate_context(self) -> None:
        if self.window is not None:
            self.window._activate_context()
        else:
            assert self._context is not None
            self._context.__enter__()
        _active_context.renderer = weakref.ref(self)

    @property
    def context(self) -> moderngl.Context:
        self.open()
        assert self._context is not None
        return self._context

    @property
    def frame_buffer_object(self) -> Framebuffer:
        self.open()
        assert self._frame_buffer_object is not None
        return self._frame_buffer_object

    @frame_buffer_object.setter
    def frame_buffer_object(self, frame: Framebuffer) -> None:
        self._ensure_not_closed()
        self._frame_buffer_object = frame

    def close(self) -> None:
        """Release GPU resources and close the preview window.

        Use :meth:`.Manager.close` for scene cleanup: it stops encoding jobs
        before closing the renderer. To render another scene, create a new
        renderer. :meth:`.Scene.get_image` can still draw with a temporary
        context.
        """
        if self._closed:
            return
        if self._capturing_image:
            raise RuntimeError("Cannot close OpenGL resources during image capture.")
        if self._context is not None and self._context_thread != threading.get_ident():
            raise RuntimeError(
                "OpenGL resources must be closed on their owning thread."
            )
        if self._context is None:
            self._closed = True
            return
        current = getattr(_active_context, "renderer", None)
        previous = (
            self._previous_renderer
            if current is not None and current() is self
            else current
        )
        # Release all resources before propagating a cleanup error or interruption.
        failures: list[BaseException] = []

        def release(callback: Callable[[], Any]) -> None:
            try:
                callback()
            except BaseException as error:
                failures.append(error)

        # Scene.interact may already have closed the window and released its GPU
        # objects. Deleting them again could affect a different active context.
        host_alive = (
            self._context is not None
            and not isinstance(self._context.mglo, moderngl.InvalidObject)
            and (self.window is None or self.window._window.context is not None)
        )
        if self._context is not None and host_alive:
            self._activate_context()
        self._retiring = True
        for name, program in list(shader_program_cache.items()):
            if program.ctx is self._context:
                del shader_program_cache[name]
                if host_alive:
                    release(program.release)
        if host_alive:
            release(self._resources.close)
        else:
            self._resources.pop_all()
            if self.window is not None and self.window._window.context is not None:
                release(self.window.close)
        self._resources = contextlib.ExitStack()
        host_still_alive = (
            not isinstance(self._context.mglo, moderngl.InvalidObject)
            if self.window is None
            else self.window._window.context is not None
        )
        if failures and host_still_alive:
            # Keep the context reachable so close() can retry. Closing it releases
            # any remaining GPU objects; rendering stays disabled until then.
            self._resources.callback(
                self._context.release if self.window is None else self.window.close
            )
        else:
            self._context = None
            self._frame_buffer_object = None
            self._context_thread = None
            self.window = None
            self._retiring = False
            self._closed = True
        _active_context.renderer = None
        release(lambda: self._restore_renderer(previous))
        if failures:
            for secondary in failures[1:]:
                logger.error("Additional OpenGL cleanup failure", exc_info=secondary)
            raise failures[0]

    @staticmethod
    def _restore_renderer(
        reference: weakref.ReferenceType[OpenGLRenderer] | None,
    ) -> None:
        prior = reference() if reference is not None else None
        if (
            prior is not None
            and not prior._closed
            and not prior._retiring
            and prior._context is not None
            and not isinstance(prior._context.mglo, moderngl.InvalidObject)
            and (prior.window is None or prior.window._window.context is not None)
        ):
            prior.open()

    def should_create_window(self, session_spec: RenderSessionSpec) -> bool:
        """Return whether the scene's saved settings request a live-preview window."""
        return session_spec.presentation.live_preview

    def get_pixel_shape(self) -> tuple[int, int] | None:
        """
        Return the pixel dimensions of the current framebuffer.

        Returns
        -------
        tuple[int, int] | None
            ``(width, height)`` in pixels, or ``None`` when no framebuffer is open.
        """
        frame_buffer = self._frame_buffer_object
        if frame_buffer is None:
            return None
        _, _, pixel_width, pixel_height = frame_buffer.viewport
        return pixel_width, pixel_height

    def _set_view(self, config: RenderConfig) -> None:
        """Set the camera uniforms for the frame of ``config``.

        The shaders rotate points about the frame center, divide by the frame
        shape and apply a perspective factor ``focal_distance / (focal_distance - z)``,
        which is what :meth:`.ThreeDCamera.project_points` does on the CPU. A
        camera without rotation draws orthographically.
        """
        self.open()
        pixel_shape = self.get_pixel_shape()
        if pixel_shape is None:
            msg = "Pixel shape is None, cannot set the view."
            raise ValueError(msg)
        _, pixel_height = pixel_shape
        self._camera_state = config.camera
        view = self.camera_view = _CameraView.of(config.camera)
        self.perspective_uniforms = self.camera_uniforms(view, pixel_height)

    def camera_uniforms(self, view: _CameraView, pixel_height: int) -> dict[str, Any]:
        """The shaders' camera uniforms for a view drawn ``pixel_height`` pixels high."""
        _, frame_height = view.frame_shape
        return {
            "frame_shape": view.frame_shape,
            # Antialiasing width, measured in pixels, converted to scene units.
            "anti_alias_width": self.anti_alias_width / (pixel_height / frame_height),
            "camera_center": tuple(view.center),
            "camera_rotation": tuple(view.rotation.T.flatten()),
            "light_source_position": tuple(view.rotation @ view.light_source),
            "focal_distance": view.focal_distance,
        }

    def _frame_target(self) -> DrawTarget:
        pixel_shape = self.get_pixel_shape()
        assert pixel_shape is not None
        return DrawTarget(
            self.frame_buffer_object,
            pixel_shape,
            self._camera_state,
            self.camera_view,
            self.perspective_uniforms,
        )

    def render(self, nodes: Sequence[RNode], config: RenderConfig, /) -> RGBAPixelArray:
        """Draw ``nodes`` as ``config`` sets them up; return the pixels.

        The picture is drawn into the renderer's framebuffer, which a preview
        window shows (see :meth:`present`).
        """
        self._draw(nodes, config)
        return self.get_frame()

    def _draw(self, nodes: Sequence[RNode], config: RenderConfig) -> None:
        """Draw a frame into the framebuffer, camera views first."""
        self._set_view(config)
        views = self._draw_camera_views(config)
        self.frame_buffer_object.use()
        background = _background_rgba(config)
        self.frame_buffer_object.clear(*background)
        self._snapshot_drawing.draw(
            _views.sort_for_display(config.camera, list(nodes)),
            self._frame_target(),
            views,
            background=background,
        )

    def _draw_camera_views(self, config: RenderConfig) -> dict[int, Any]:
        """Draw each camera view into a texture; return them by the uid of the
        view's node, and by ``("camera", camera_id)`` for copies of a view.
        """
        textures: dict[Any, Any] = {}
        drawn = set()
        for view in config.camera_views:
            view_config = view.config
            size = (view_config.pixel_width, view_config.pixel_height)
            view_target = self._camera_view_targets.get(view.uid)
            if view_target is None or view_target.size != size:
                if view_target is not None:
                    view_target.release()
                view_target = _ViewTarget(self, size)
                self._camera_view_targets[view.uid] = view_target
            state = view_config.camera
            camera_view = _CameraView.of(state)
            target = DrawTarget(
                view_target.framebuffer,
                size,
                state,
                camera_view,
                self.camera_uniforms(camera_view, size[1]),
            )
            view_target.framebuffer.use()
            view_target.framebuffer.clear(*_background_rgba(view_config))
            view_target.drawing.draw(
                _views.sort_for_display(state, list(view.nodes)), target
            )
            textures[view.uid] = textures[("camera", view.camera_id)] = (
                view_target.texture
            )
            drawn.add(view.uid)
        for uid in self._camera_view_targets.keys() - drawn:
            self._camera_view_targets.pop(uid).release()
        return textures

    @property
    def pixel_size(self) -> tuple[int, int]:
        """The width and height in pixels of frames drawn for a scene."""
        return self._pixel_size

    def _start_animation(self) -> None:
        self.open()

    def present(self) -> None:
        """Show the last frame drawn in the preview window, if there is one."""
        if self.window is not None:
            self.window.show(self.frame_buffer_object)
            self._activate_context()

    def _scene_point(self, x: float, y: float, relative: bool) -> Point3D:
        """The scene point at a window position given as fractions of its width and
        height from the bottom left; with ``relative``, the scene offset of a move
        by those fractions.
        """
        view = _CameraView.of(self._window_camera._state())
        width, height = view.frame_shape
        offset = np.array([x * width, y * height, 0.0])
        if relative:
            return typing.cast(Point3D, offset)
        return typing.cast(
            Point3D, view.center + offset - np.array([width / 2, height / 2, 0.0])
        )

    @contextlib.contextmanager
    def _scene_images(self) -> Iterator[None]:
        """Keep the temporary renderer of :meth:`_get_scene_image` for many images.

        Creating an OpenGL context for each image costs far more than drawing it,
        so evaluation, which draws every requested frame this way, keeps one.
        """
        self._keep_image_renderer = True
        try:
            yield
        finally:
            self._keep_image_renderer = False
            kept, self._image_renderer = self._image_renderer, None
            if kept is not None:
                kept.close()

    def _image(self, nodes: Sequence[RNode], config: RenderConfig) -> RGBAPixelArray:
        """Draw a frame for inspection, apart from the live-preview framebuffer.

        An existing context is used on its rendering thread. Otherwise, the frame
        is drawn with a temporary context and renderer.
        """
        if (
            self._context_thread is not None
            and threading.get_ident() != self._context_thread
        ):
            raise RuntimeError(
                "OpenGL scene images must be requested on the render thread."
            )
        if self._capturing_image:
            raise RuntimeError("Recursive OpenGL scene image capture is not supported.")
        if self._context is None:
            kept = self._image_renderer
            temporary = kept if kept is not None else OpenGLRenderer()
            temporary._scene_bound = True
            temporary._pixel_size = self._pixel_size
            temporary._wireframe = self._wireframe
            temporary._window_settings = None
            self._capturing_image = True
            try:
                try:
                    pixels = temporary.render(nodes, config)
                except BaseException:
                    self._image_renderer = None
                    try:
                        temporary.close()
                    except BaseException:
                        logger.exception(
                            "Failed to close the temporary OpenGL image scope"
                        )
                    raise
                if self._keep_image_renderer:
                    self._image_renderer = temporary
                else:
                    temporary.close()
                return pixels
            finally:
                self._capturing_image = False
        target = self.frame_buffer_object
        bound = self.context.fbo
        viewport = self.context.viewport
        size = target.size
        self._capturing_image = True
        try:
            with contextlib.ExitStack() as resources:
                color = self.context.texture(size, components=4)
                resources.callback(color.release)
                depth = self.context.depth_renderbuffer(size)
                resources.callback(depth.release)
                frame = self.context.framebuffer(color, depth)
                resources.callback(frame.release)
                drawing = self._snapshot_drawing
                # A separate drawing state: the reuse kept for the live frames stays.
                self._snapshot_drawing = SnapshotDrawing(self)
                try:
                    self.frame_buffer_object = frame
                    frame.use()
                    return self.render(nodes, config)
                finally:
                    self._snapshot_drawing.release()
                    self._snapshot_drawing = drawing
                    self.frame_buffer_object = target
                    (target if bound is None else bound).use()
                    self.context.viewport = viewport
        finally:
            self._capturing_image = False

    def get_frame_buffer_object(
        self,
        context: moderngl.Context,
        samples: int = 0,
        *,
        size: tuple[int, int] | None = None,
    ) -> Framebuffer:
        """
        Creates and returns a framebuffer object configured with color
        and depth attachments.

        Parameters
        ----------
        context : moderngl.Context
            The ModernGL context used to create the framebuffer and
            its attachments.
        samples : int, optional
            The number of samples for multisample anti-aliasing (MSAA)[1]_.
            Default is 0 (no MSAA).

        Returns
        -------
        Framebuffer
            A framebuffer object with a color texture attachment and
            a depth renderbuffer attachment, both sized according to
            the current configuration's pixel width and height.

        Notes
        -----
        Framebuffer's color attachment is supposed RGBA.
        Pixel dimensions are taken from the global config of Manim.

        References
        ----------
        .. [1] Wikipedia, "Multisample anti-aliasing",
               https://en.wikipedia.org/wiki/Multisample_anti-aliasing
        """
        pixel_width, pixel_height = (
            (config["pixel_width"], config["pixel_height"]) if size is None else size
        )
        num_channels = 4
        resources = contextlib.ExitStack()
        try:
            color = context.texture(
                (pixel_width, pixel_height), components=num_channels, samples=samples
            )
            resources.callback(color.release)
            depth = context.depth_renderbuffer(
                (pixel_width, pixel_height), samples=samples
            )
            resources.callback(depth.release)
            frame = context.framebuffer(color_attachments=color, depth_attachment=depth)
        except BaseException:
            try:
                resources.close()
            except BaseException:
                logger.exception("Failed to roll back OpenGL framebuffer allocation")
            raise
        resources.pop_all()
        return frame

    def get_raw_frame_buffer_object_data(self, dtype: str = "f1") -> bytes:
        """
        Get the raw data from the current frame buffer object as bytes.

        This method reads the pixel data from the frame buffer object using the specified data type.
        The data is read with 4 color channels (typically RGBA).

        Args:
            dtype (str, optional): The data type to use when reading the buffer.
            Defaults to "f1" (i.e., float with 1 byte).

        Returns:
            bytes: The raw pixel data from the frame buffer object.
        """
        # Copy blocks from the fbo_msaa to the drawn fbo using Blit
        # pw, ph = self.get_pixel_shape()
        # gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, self.fbo_msaa.glo)
        # gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, self.fbo.glo)
        # gl.glBlitFramebuffer(
        #     0, 0, pw, ph, 0, 0, pw, ph, gl.GL_COLOR_BUFFER_BIT, gl.GL_LINEAR
        # )
        num_channels = 4
        ret: bytes = self.frame_buffer_object.read(
            viewport=self.frame_buffer_object.viewport,
            components=num_channels,
            dtype=dtype,
        )
        return ret

    def get_frame(self) -> RGBAPixelArray:
        """
        Get the current frame buffer as a Numpy array of RGBA pixel values.

        Returns
        -------
        RGBAPixelArray
            A Numpy array of shape (height, width, 4) containing the
            RGBA pixel data of the current frame, with dtype uint8.

        Raises
        ------
        ValueError
            If the pixel shape cannot be determined.
        """
        # get current pixel values as numpy data in order to test output
        raw = self.get_raw_frame_buffer_object_data(dtype="f1")
        pixel_shape = self.get_pixel_shape()
        if pixel_shape is None:
            msg = "Pixel shape is None, cannot get frame."
            raise ValueError(msg)

        result_dimensions = (pixel_shape[1], pixel_shape[0], 4)
        np_buf = np.frombuffer(raw, dtype="uint8").reshape(result_dimensions)
        return np.flipud(np_buf).copy()


#: Focal distance standing in for "no perspective" (a camera without rotation).
_ORTHOGRAPHIC_FOCAL_DISTANCE = 1e6


class _CameraView(typing.NamedTuple):
    """What the shaders need to know about a camera."""

    center: Point3D
    #: Rotation applied to ``point - center``, as in ``ThreeDCamera.project_points``.
    rotation: np.ndarray
    #: Frame width and height, divided by the zoom factor.
    frame_shape: tuple[float, float]
    focal_distance: float
    light_source: Point3D

    @classmethod
    def of(cls, state: CameraState) -> _CameraView:
        zoom = state.zoom
        focal_distance = state.focal_distance
        return cls(
            center=state.center,
            rotation=state.rotation,
            frame_shape=(state.frame_width / zoom, state.frame_height / zoom),
            focal_distance=(
                _ORTHOGRAPHIC_FOCAL_DISTANCE
                if focal_distance is None
                else focal_distance
            ),
            light_source=state.light,
        )


class _ViewTarget:
    """An offscreen target for one camera view, with its own drawing state."""

    def __init__(self, renderer: OpenGLRenderer, size: tuple[int, int]) -> None:
        context = renderer.context
        self.size = size
        self.texture = context.texture(size, components=4)
        self.texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.framebuffer = context.framebuffer(color_attachments=[self.texture])
        self.drawing = SnapshotDrawing(renderer)
        renderer._resources.callback(self.release)

    def release(self) -> None:
        """Release the GPU objects; safe to call more than once."""
        self.drawing.release()
        for resource in (self.framebuffer, self.texture):
            if not isinstance(resource.mglo, moderngl.InvalidObject):
                resource.release()


def _background_rgba(config: RenderConfig) -> tuple[float, float, float, float]:
    """The background of a frame, as the framebuffer is cleared to it."""
    r, g, b = config.background_color.to_rgb()
    return float(r), float(g), float(b), float(config.background_opacity)
