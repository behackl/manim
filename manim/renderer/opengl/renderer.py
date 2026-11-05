from __future__ import annotations

import contextlib
import threading
import time
import typing
import weakref
from typing import TYPE_CHECKING, Any

import moderngl
import numpy as np
from moderngl import Framebuffer
from PIL import Image

from manim._config import config, logger
from manim.typing import Point3D
from manim.utils.iterables import list_update

from ...camera import Camera
from ...constants import *
from .. import _view as _views
from .._execution import _RendererExecutionView
from ..frame import FrameBuilder
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


class OpenGLRenderer(_RendererExecutionView):
    """
    An OpenGL-based renderer.

    Attributes
    ----------
    animation_elapsed_time : float
        The elapsed time of the current animation.
    animation_start_time : float
        The start time of the current animation.
    animations_hashes : list[str | None]
        List of animation hashes for caching.
    anti_alias_width : float
        The width used for anti-aliasing in pixel units.
    camera : Camera
        The camera used for rendering: the same camera classes as the Cairo renderer.
    num_plays : float
        The number of animation plays executed.
    pressed_keys : set[int]
        Set of currently pressed key codes.
    skip_animations : bool
        Whether animations are currently being skipped.
    time : float
        The total elapsed time for the renderer.
    window : Window | None
        The window used for previewing, if any.
    """

    capabilities = RendererCapabilities(live_preview=True)

    def __init__(
        self,
        skip_animations: bool = False,
        camera_class: type[Camera] | None = None,
        camera: Camera | None = None,
    ) -> None:
        """Initializes the OpenGLRenderer.

        Parameters
        ----------
        skip_animations : bool, optional
            Whether to skip animations during rendering, by default False.
        camera_class
            The camera class to instantiate, by default :class:`.Camera`.
        camera
            A camera to use instead of instantiating ``camera_class``.
        """
        if camera is not None and camera_class is not None:
            raise ValueError("Pass either camera or camera_class, not both.")
        # Measured in pixel widths, used for vector graphics
        self.anti_alias_width = 1.5

        self._initialize_execution(skip_animations)
        self.animation_start_time = 0.0
        self.animation_elapsed_time = 0.0

        self.camera: Camera = (
            camera if camera is not None else (camera_class or Camera)()
        )
        self.perspective_uniforms: dict[str, Any] = {}
        self.camera_view: _CameraView = _CameraView.of(self.camera._state())
        self._camera_state = self.camera._state()
        self._snapshot_drawing = SnapshotDrawing(self)
        self._frame_builder: FrameBuilder | None = None
        self._camera_view_targets: dict[int, _ViewTarget] = {}
        self.pressed_keys: set[int] = set()
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
        Attach a scene and save its pixel dimensions and preview-window settings.

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
        if hasattr(self, "scene"):
            raise RuntimeError("This renderer is already bound to a Scene.")
        self.partial_movie_files: list[str | None] = []
        self.scene = scene

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
        if not hasattr(self, "scene"):
            raise RuntimeError("Bind an OpenGL scene before opening its resources.")
        previous = getattr(_active_context, "renderer", None)
        resources = contextlib.ExitStack()
        try:
            window = None
            if self._window_settings is not None:
                # Import here: only preview windows need pyglet and screeninfo.
                from .window import Window

                window = Window(self, _settings=self._window_settings)
                resources.callback(window.close)
                # Closing the window also releases its context and default framebuffer.
                context = window.ctx
                frame = context.detect_framebuffer()
            else:
                try:
                    context = moderngl.create_context(standalone=True)
                except Exception:
                    context = moderngl.create_context(standalone=True, backend="egl")
                resources.callback(context.release)
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
        self.pressed_keys.clear()
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
        window shows (see :meth:`_present_frame`).
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

    def _frames(self) -> FrameBuilder:
        if self._frame_builder is None:
            self._frame_builder = FrameBuilder(*self.pixel_size)
        return self._frame_builder

    @property
    def pixel_size(self) -> tuple[int, int]:
        """The width and height in pixels of frames drawn for a scene."""
        return self._pixel_size

    def _animation_cache_identity(self, scene: Scene) -> tuple[str, Any]:
        return "opengl", {
            "anti_alias_width": self.anti_alias_width,
        }

    def _start_animation(self) -> None:
        self.open()
        self.animation_start_time = time.time()

    def _present_frozen_frame(self, scene: Scene, duration: float) -> None:
        if self.window is not None:
            self.window.swap_buffers()
            while time.time() - self.animation_start_time < duration:
                pass
        self.animation_elapsed_time = duration

    def clear_screen(self) -> None:
        """
        Clears the current frame buffer and updates the display window
        accordingly.

        The screen is cleared using the camera's background color.
        """
        self.frame_buffer_object.clear(*_camera_background_rgba(self.camera))
        if self.window is None:
            return
        self.window.swap_buffers()

    def render_scene(self, scene: Scene, frame_offset: float) -> None:
        """Draw a frame of the scene's current state into the framebuffer."""
        self.update_frame(scene)

    def _note_drawn(self) -> None:
        """Note the wall-clock time of a frame drawn for the preview window."""
        self.animation_elapsed_time = time.time() - self.animation_start_time

    def _present_frame(self, scene: Scene, frame_offset: float) -> None:
        """Refresh the preview window until wall-clock time reaches the frame offset."""
        if self.window is not None:
            self.window.swap_buffers()
            while self.animation_elapsed_time < frame_offset:
                self.update_frame(scene)
                self.window.swap_buffers()

    def update_frame(self, scene: Scene) -> None:
        """Draw a frame of the scene's current state into the framebuffer, and
        note the wall-clock time for pacing the preview window.
        """
        self._draw_scene(scene)
        self.animation_elapsed_time = time.time() - self.animation_start_time

    def _draw_scene(self, scene: Scene) -> None:
        self._draw(
            *self._frames().build(
                self.camera, list_update(scene.mobjects, scene.foreground_mobjects)
            )
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

    def _get_scene_image(self, scene: Scene) -> Image.Image:
        """Draw a snapshot separately from the live-preview framebuffer.

        An existing context is used on its rendering thread. Otherwise, the scene
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
            temporary.scene = scene
            temporary.camera = self.camera
            temporary._pixel_size = self._pixel_size
            temporary._wireframe = self._wireframe
            temporary._window_settings = None
            self._capturing_image = True
            try:
                try:
                    temporary._draw_scene(scene)
                    image = temporary.get_image()
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
                return image
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
                try:
                    self.frame_buffer_object = frame
                    frame.use()
                    self._draw_scene(scene)
                    return Image.fromarray(self.get_frame())
                finally:
                    self.frame_buffer_object = target
                    (target if bound is None else bound).use()
                    self.context.viewport = viewport
        finally:
            self._capturing_image = False

    def get_image(self) -> Image.Image:
        """
        Get the current OpenGL frame buffer as a PIL Image.

        Returns
        -------
        Image.Image
            The image representation of the current frame buffer.

        Raises
        ------
        ValueError
            If the pixel shape cannot be determined.

        Notes
        -----
        The image is constructed from raw RGBA buffer data, with the
        origin at the bottom-left.
        """
        raw_buffer_data = self.get_raw_frame_buffer_object_data()
        pixel_shape = self.get_pixel_shape()
        if pixel_shape is None:
            msg = "Pixel shape is None, cannot get image."
            raise ValueError(msg)

        image = Image.frombytes(
            "RGBA",  # mode (rgb, a for alpha (transparency)))
            pixel_shape,  # size
            raw_buffer_data,  # data
            "raw",  # decoder_name
            # *args for the decoder
            "RGBA",  # raw mode
            0,  # stride (O = no extra padding)
            -1,  # orientation (-1 = bottom to top, 1 = top to bottom)
        )
        return image

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

    # Returns offset from the bottom left corner in pixels.
    # top_left flag should be set to True when using a GUI framework
    # where the (0,0) is at the top left: e.g. PySide6
    def pixel_coords_to_space_coords(
        self, px: float, py: float, relative: bool = False, top_left: bool = False
    ) -> Point3D:
        """
        Converts pixel coordinates to space (scene) coordinates.

        top_left flag should be set to True when using a GUI framework
        where the (0,0) is at the top left: e.g. PySide6.

        Parameters
        ----------
        px : float
            The x-coordinate in pixel space.
        py : float
            The y-coordinate in pixel space.
        relative : bool, optional
            If True, returns coordinates relative to the frame (normalized to [-1, 1]).
            If False, returns absolute space coordinates. Default is False.
        top_left : bool, optional
            If True, treats the origin (0, 0) as the top-left corner of the pixel space.
            If False, treats the origin as the bottom-left. Default is False.

        Returns
        -------
        Point3D
            The corresponding coordinates in space as a NumPy array of shape (3,).

        Notes
        -----
        If the pixel shape is not available, returns the origin [0, 0, 0].
        """
        pixel_shape = self.get_pixel_shape()
        if pixel_shape is None:
            return typing.cast(Point3D, np.array([0.0, 0.0, 0.0]))
        pixel_width, pixel_height = pixel_shape
        view = _CameraView.of(self.camera._state())
        frame_height = view.frame_shape[1]
        frame_center = view.center
        if relative:
            # relative -> just normalize to [-1, 1]
            return 2 * np.array([px / pixel_width, py / pixel_height, 0])

        scale = frame_height / pixel_height
        y_direction = -1 if top_left else 1

        return typing.cast(
            Point3D,
            frame_center
            + scale
            * np.array(
                [(px - pixel_width / 2), y_direction * (py - pixel_height / 2), 0.0]
            ),
        )


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


def _camera_background_rgba(camera: Camera) -> tuple[float, float, float, float]:
    r, g, b = camera.background_color.to_rgb()
    return float(r), float(g), float(b), float(camera.background_opacity)
