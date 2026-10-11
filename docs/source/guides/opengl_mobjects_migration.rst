Migrating from the OpenGL mobject classes
=========================================

Earlier versions of Manim had two sets of mobject classes: the common ones
(:class:`.Mobject`, :class:`.VMobject`, ...) and OpenGL ones (``OpenGLMobject``,
``OpenGLVMobject``, ...). With ``--renderer=opengl``, a metaclass swapped the base
classes of every mobject class for their OpenGL counterparts, so the same scene
code ran on different classes depending on the renderer.

Now both renderers draw the same classes. Scenes that only use the classes
exported by ``from manim import *`` keep working; under ``--renderer=opengl`` they
now look like they do with Cairo (strokes, fills, gradients, ``z_index``, cameras).
This page lists what was removed and what to use instead.

Removed classes
---------------

.. list-table::
   :header-rows: 1

   * - Removed
     - Use instead
   * - ``OpenGLMobject``, ``OpenGLGroup``, ``OpenGLPoint``
     - :class:`.Mobject`, :class:`.Group`, :class:`.Point`
   * - ``OpenGLVMobject``, ``OpenGLVGroup``, ``OpenGLVectorizedPoint``,
       ``OpenGLCurvesAsSubmobjects``, ``OpenGLDashedVMobject``
     - :class:`.VMobject`, :class:`.VGroup`, :class:`.VectorizedPoint`,
       :class:`.CurvesAsSubmobjects`, :class:`.DashedVMobject`
   * - ``OpenGLPMobject``, ``OpenGLPGroup``, ``OpenGLPMPoint``
     - :class:`.PMobject`, :class:`.PGroup`, :class:`.Point`
   * - ``TrueDot``, ``DotCloud``
     - :class:`.Dot`, or :class:`.PMobject` / :class:`.PointCloudDot` for clouds
   * - ``OpenGLImageMobject``
     - :class:`.ImageMobject`
   * - ``OpenGLSurface``
     - :class:`.ParametricSurface`, a smooth lit surface (OpenGL only for now),
       or :class:`.Surface`, a group of polygon faces drawn by both renderers
   * - ``OpenGLTexturedSurface``
     - :class:`.ParametricSurface` with ``texture=``. One texture: the separate
       night-side texture is gone.
   * - ``OpenGLSurfaceMesh``
     - :meth:`.MeshMobject.get_wireframe`
   * - ``OpenGLArc``, ``OpenGLCircle``, ``OpenGLLine``, ... (``opengl_geometry``)
     - :class:`.Arc`, :class:`.Circle`, :class:`.Line`, ...
   * - ``OpenGLCamera``
     - :class:`.Camera`, :class:`.MovingCamera`, :class:`.ThreeDCamera`
       (see :doc:`cameras`)

The modules ``manim.mobject.opengl`` and ``manim.mobject.utils`` are gone.
``manim.opengl`` now only exports the shader utilities (``Shader``, ``Mesh``,
``FullScreenQuad``) and ``manim.utils.opengl``.

Removed functions and options
-----------------------------

- ``ConvertToOpenGL`` and ``uses_opengl_mobjects()``: subclass the common classes
  directly; they work with both renderers.
- ``get_mobject_class()``, ``get_vectorized_mobject_class()``,
  ``get_point_mobject_class()``: use :class:`.Mobject`, :class:`.VMobject` and
  :class:`.PMobject`.
- The ``use_projection_fill_shaders`` and ``use_projection_stroke_shaders`` config
  options and ``--use_projection_fill_shaders`` / ``--use_projection_stroke_shaders``
  CLI flags.
- The ``long_lines``, ``should_subdivide_sharp_curves`` and
  ``should_remove_null_curves`` arguments of :class:`.VMobjectFromSVGPath`, which
  only had an effect on the OpenGL classes.

Changed behavior of mobject methods
-----------------------------------

Methods of the OpenGL classes that the common classes do not have are gone. The
most common ones:

.. list-table::
   :header-rows: 1

   * - OpenGL classes
     - Common classes
   * - ``mob.fix_in_frame()``, ``mob.unfix_from_frame()``,
       ``mob.fix_orientation()``
     - The same methods exist on :class:`.Mobject`, and now work on both
       renderers and with every camera.
   * - ``mob.set_color(..., recurse=False)``
     - ``mob.set_color(..., family=False)``
   * - ``mob.data[...]``, ``mob.uniforms[...]``
     - The attributes themselves (``mob.points``, ``mob.fill_rgbas``, ...).
   * - ``mob.set_color_by_code(glsl)``
     - :meth:`.MeshMobject.set_color_by_xyz_func`, which takes a Python function
       of the points.
   * - ``set_gloss``, ``set_shadow``, ``apply_depth_test``
     - The ``gloss``, ``shadow`` and ``depth_test`` arguments and attributes of
       :class:`.MeshMobject`.
   * - Stroke widths per point
     - One stroke width per :class:`.VMobject`.
   * - ``get_shader_wrapper_list()`` and other shader-wrapper methods
     - None. Custom shaders can be drawn with ``Mesh`` from ``manim.opengl``.

Things that look different
--------------------------

- :class:`.Sphere` and :class:`.Torus` have the same default resolution on both
  renderers; on OpenGL it used to be much finer. Use :class:`.ParametricSurface`
  for smooth spheres.
- Under :class:`.ThreeDScene`, lines and other paths are drawn in the order they
  are added, as with Cairo; only :class:`.MeshMobject` takes part in the depth
  test.
