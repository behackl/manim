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
- Mobjects fixed in the frame (:meth:`.Mobject.fix_in_frame`) are drawn after all
  other mobjects, in scene order and by ``z_index`` among themselves. Earlier, a
  fixed mobject added before another mobject could be covered by it. A fixed mesh
  hides its own triangles, but neither hides nor is hidden by the depth of the
  scene.

Drawing frames
--------------

- Renderers draw what they are given: ``renderer.render(nodes, config)`` draws
  the render snapshots of a frame as its :class:`.RenderConfig` sets them up and
  returns a :class:`.Frame`; ``frame.pixels()`` reads its RGBA pixels. The
  manager's :class:`.FrameBuilder` makes both from the scene's mobjects and
  camera. ``update_frame()``, ``render_mobjects()``, ``get_frame()``,
  ``get_image()`` and ``render(scene, time)`` of the renderers are gone; use
  :meth:`.Scene.get_image` for an image of the scene's current state.
- Renderers keep no camera: ``renderer.camera`` and the ``camera`` and
  ``camera_class`` arguments of :class:`.CairoRenderer` and
  :class:`.OpenGLRenderer` are gone. The scene's camera is ``scene.camera``.
- :class:`.OpenGLRenderer` takes its options as arguments (``wireframe``,
  ``anti_alias_width``); the scene passes ``config.enable_wireframe`` when it
  creates one. Both options are part of the play cache's key.
- Frames are drawn at the size the scene was created with
  (``scene.session_spec.pixel_size``); renderers have no pixel size of their own.

Removed renderer methods
------------------------

Renderers only draw (see :class:`.Renderer`). These methods are gone:

.. list-table::
   :header-rows: 1

   * - Removed
     - Use instead
   * - ``renderer.file_writer``
     - ``scene.manager.file_writer`` (or ``scene._get_manager().file_writer``)
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

A renderer draws the frames of one scene: passing a renderer that another scene
uses to :class:`.Scene` raises ``RuntimeError``.

The animation clock and counters belong to the :class:`.Manager`:
``renderer.time``, ``renderer.num_plays``, ``renderer.skip_animations`` and
``renderer.animations_hashes`` are gone; use ``scene.time`` or the attributes of
the same names on ``scene.manager``. ``Scene(skip_animations=True)`` now leaves
plays out with any renderer, and the renderers' ``skip_animations`` argument is
gone.
