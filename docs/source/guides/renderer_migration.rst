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
