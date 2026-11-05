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
   * - ``renderer.get_frame()`` after a render, for the final state
     - :meth:`.Scene.get_image`
   * - ``CairoRenderer(file_writer_class=...)``,
       ``OpenGLRenderer(file_writer_class=...)``
     - Nothing; the Manager creates a :class:`.SceneFileWriter`.

The camera belongs to the scene: ``scene.camera`` (created from ``camera_class``).
