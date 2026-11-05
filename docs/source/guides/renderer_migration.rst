Migrating to the drawing-only renderers
=======================================

The Cairo and OpenGL renderers only draw: the :class:`.Manager` runs the scene,
owns the animation clock and the output files, and hands the renderer what to draw
in each frame. This page lists what changed for code that used the renderers,
cameras or scene classes directly.

Removed scene classes and camera options
----------------------------------------

- ``SpecialThreeDScene`` is gone. It could not be constructed (it read a
  renderer setting that no longer existed); use :class:`.ThreeDScene` and create
  the axes and spheres it offered directly.
- The ``exponential_projection`` argument and attribute of :class:`.ThreeDCamera`
  are gone. Only ``SpecialThreeDScene`` used them, and the OpenGL renderer
  ignored them. Points are projected with the factor
  ``focal_distance / (focal_distance - z)``.

Changed drawing
---------------

- The OpenGL renderer clears frames to the camera's ``background_color`` and
  ``background_opacity``, as the Cairo renderer does; it used to clear to the
  configured background color whatever the camera said.
- Camera views do not show camera views. Earlier, the Cairo renderer drew a
  :class:`.MultiCamera` used as a secondary camera with its own insets; now each
  view shows the scene without insets on both renderers, and registrations that
  form a cycle are not an error anymore.

Removed renderer methods
------------------------

Renderers only draw (see :class:`.Renderer`). These methods are gone:

.. list-table::
   :header-rows: 1

   * - Removed
     - Use instead
   * - ``renderer.file_writer``
     - ``scene.manager.file_writer``, once a :class:`.Manager` renders the scene
   * - ``renderer.play(scene, ...)``
     - :meth:`.Scene.play`
   * - ``renderer.scene_finished(scene)``
     - Nothing: :meth:`.Manager.render` finishes the movie and saves the last
       frame.
   * - ``renderer.freeze_current_frame(duration)``, ``renderer.add_frame(...)``
     - :meth:`.Scene.pause` (a frozen :meth:`.Scene.wait`)
   * - ``renderer.update_skipping_status()``
     - Nothing: each play checks whether it is part of the output.
   * - ``renderer.show_frame(scene)``
     - ``scene.get_image().show()``
   * - ``renderer.get_frame()``, ``renderer.get_image()``,
       ``renderer.update_frame(scene)``, ``renderer.render_scene(...)``,
       ``renderer.render_mobjects(...)``
     - :meth:`.Scene.get_image` or :meth:`.Mobject.get_image` for images. To
       draw a frame yourself, build its input with a :class:`.FrameBuilder` and
       call ``renderer.render(nodes, config)``, which returns the pixels.
   * - ``renderer.time``, ``renderer.num_plays``, ``renderer.skip_animations``
     - :attr:`.Scene.time`, ``scene.num_plays``, ``scene.skip_animations``
       (the Manager keeps the clock); pass ``skip_animations`` to the scene's
       constructor.
   * - ``renderer.camera``, ``CairoRenderer(camera_class=...)``,
       ``OpenGLRenderer(camera=...)``
     - ``scene.camera``; pass ``camera_class`` to the scene's constructor.
   * - ``OpenGLRenderer.pixel_coords_to_space_coords``,
       ``renderer.pressed_keys``, ``renderer.animation_start_time``,
       ``renderer.animation_elapsed_time``
     - The preview window maps positions to scene points itself and sends them
       to the scene's input callbacks; ``renderer.window.pressed_keys`` holds
       the keys held down. The Manager paces the preview.
   * - ``CairoRenderer(file_writer_class=...)``,
       ``OpenGLRenderer(file_writer_class=...)``
     - Nothing; the Manager creates a :class:`.SceneFileWriter`.

The camera belongs to the scene: ``scene.camera`` (created from ``camera_class``).

Writing a renderer
------------------

A renderer implements :class:`.Renderer`: ``render(nodes, config)`` draws the
render snapshots ``nodes`` (see :mod:`manim.renderer.snapshot`) as the
:class:`.RenderConfig` sets them up, and returns RGBA pixels with row zero at the
top. ``config`` holds the camera's :class:`.CameraState` and the views of
:class:`.MultiCamera` cameras, each with its own nodes. Everything else (the
clock, caching, output files, previews) is the :class:`.Manager`'s, so a
renderer does not see scenes, mobjects or cameras.

Preview window
--------------

With the OpenGL renderer and a live preview, frames are drawn offscreen at the
scene's pixel size and shown in the window, scaled to it. The window used to be
drawn into directly, so frames had the window's size: writing a movie while
previewing in a window of another size failed.
