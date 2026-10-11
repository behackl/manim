"""Both renderers draw meshes: OpenGL with depth testing and lighting per pixel,
Cairo as faces sorted far to near, lit per face.
"""

import numpy as np
import pytest

from manim import (
    BLUE,
    DEGREES,
    PI,
    PURE_BLUE,
    PURE_RED,
    RIGHT,
    TAU,
    ImageMobject,
    ParametricSurface,
    Scene,
    ThreeDScene,
    config,
    tempconfig,
)

WIDTH, HEIGHT = 384, 216


def _image(renderer, mobjects, scene_class=Scene, **orientation):
    with tempconfig(
        {
            "renderer": renderer,
            "dry_run": True,
            "pixel_width": WIDTH,
            "pixel_height": HEIGHT,
        }
    ):
        scene = scene_class()
        try:
            if orientation:
                scene.set_camera_orientation(**orientation)
            scene.add(*mobjects())
            pixels = np.asarray(scene.get_image().convert("RGB"), dtype=float) / 255
            camera = scene.renderer.camera
        finally:
            scene.renderer.close()
    return pixels, camera


def _pixel(pixels, x, y):
    """The pixel at scene coordinates ``(x, y)`` seen from the default camera."""
    column = int((x / config.frame_width + 0.5) * WIDTH)
    row = int((0.5 - y / config.frame_height) * HEIGHT)
    return pixels[row, column]


RENDERERS = pytest.mark.parametrize("renderer", ["cairo", "opengl"])


def _plane(z, color, resolution=4, **kwargs):
    return ParametricSurface(
        lambda u, v: [u, v, z],
        u_range=[-3, 3],
        v_range=[-2, 2],
        resolution=resolution,
        color=color,
        gloss=0,
        shadow=0,
        **kwargs,
    )


def _sphere(radius=2, **kwargs):
    return ParametricSurface(
        lambda u, v: radius
        * np.array([np.cos(u) * np.sin(v), np.sin(u) * np.sin(v), -np.cos(v)]),
        u_range=[0, TAU],
        v_range=[0, np.pi],
        resolution=(48, 24),
        **kwargs,
    )


@RENDERERS
def test_texture_is_drawn_like_an_image(renderer):
    # u runs left to right across the image, v from its bottom to its top.
    texture = np.zeros((40, 60, 4), dtype=np.uint8)
    texture[..., 0] = np.linspace(0, 255, 60)[None, :]
    texture[..., 2] = np.linspace(255, 0, 40)[:, None]
    texture[..., 3] = 255

    # Cairo colours each face by the texture at its middle.
    surface, _ = _image(
        renderer, lambda: [_plane(0, BLUE, resolution=(60, 40), texture=texture)]
    )
    image, _ = _image(
        "cairo",
        lambda: [
            ImageMobject(texture).stretch_to_fit_width(6).stretch_to_fit_height(4)
        ],
    )

    assert np.abs(surface - image).mean() < 0.01


@RENDERERS
def test_opaque_meshes_hide_what_is_behind_them(renderer):
    front = _plane(1, PURE_RED)
    back = _plane(-1, PURE_BLUE)

    pixels, _ = _image(renderer, lambda: [front, back], ThreeDScene)

    np.testing.assert_allclose(_pixel(pixels, 0, 0), [1, 0, 0])


@RENDERERS
@pytest.mark.parametrize("scene_class", [Scene, ThreeDScene])
def test_faces_of_a_mesh_hide_those_behind_them(renderer, scene_class):
    # The sphere's near half is red, its far half blue. Turned over, its faces come
    # near to far.
    sphere = _sphere(1, gloss=0, shadow=0).rotate(PI, RIGHT)
    near = sphere.points[:, 2] > 0
    rgbas = np.zeros((len(near), 4))
    rgbas[:, 0], rgbas[:, 2], rgbas[:, 3] = near, ~near, 1
    sphere.set_vertex_colors(rgbas)

    pixels, _ = _image(renderer, lambda: [sphere], scene_class)

    # Off the pole, where on Cairo many faces meet.
    np.testing.assert_allclose(_pixel(pixels, 0.4, 0.3), [1, 0, 0], atol=0.05)


def test_translucent_meshes_show_only_their_front_layer(using_opengl_renderer):
    sphere = _sphere(opacity=0.5, gloss=0, shadow=0)
    top = sphere.points[:, 2] > 0
    rgbas = np.zeros((len(top), 4))
    rgbas[:, 0], rgbas[:, 2], rgbas[:, 3] = top, ~top, 0.5
    sphere.set_vertex_colors(rgbas)

    pixels, _ = _image("opengl", lambda: [sphere], ThreeDScene)

    np.testing.assert_allclose(_pixel(pixels, 0.5, 0.5), [0.5, 0, 0], atol=0.01)


@RENDERERS
def test_meshes_are_lit_from_the_light_source(renderer):
    pixels, camera = _image(
        renderer,
        lambda: [_sphere(gloss=0, shadow=1)],
        ThreeDScene,
        phi=60 * DEGREES,
        theta=30 * DEGREES,
    )

    # Seen from the camera, the light is above the sphere in this direction.
    light = camera.project_point(camera.light_source.get_center())[:2]
    toward = 1.5 * light / np.linalg.norm(light)
    lit, unlit = _pixel(pixels, *toward), _pixel(pixels, *-toward)

    assert lit.sum() > 2 * unlit.sum()


@RENDERERS
def test_meshes_fixed_in_frame_ignore_the_camera(renderer):
    plane = _plane(0, PURE_RED).fix_in_frame()

    pixels, _ = _image(renderer, lambda: [plane], ThreeDScene, phi=80 * DEGREES)

    np.testing.assert_allclose(_pixel(pixels, 2.5, 1.5), [1, 0, 0])


def test_shaded_faces_and_outlines_look_alike_on_both_renderers(using_opengl_renderer):
    def surface():
        sphere = _sphere(
            2,
            shade_in_3d=True,
            stroke_color=PURE_RED,
            stroke_width=3,
            gloss=0,
            shadow=0,
        )
        return [sphere.set_fill_by_checkerboard(BLUE, PURE_BLUE)]

    orientation = {"phi": 60 * DEGREES, "theta": 30 * DEGREES}
    cairo, _ = _image("cairo", surface, ThreeDScene, **orientation)
    opengl, _ = _image("opengl", surface, ThreeDScene, **orientation)

    # The outlines (and edges of the faces) land on the same pixels.
    assert np.abs(opengl - cairo).mean() < 0.01
    # The faces are shaded alike: the same brightness in the middle of the sphere.
    middle = np.s_[
        HEIGHT // 2 - 25 : HEIGHT // 2 + 25, WIDTH // 2 - 25 : WIDTH // 2 + 25
    ]
    assert opengl[middle].mean() == pytest.approx(cairo[middle].mean(), abs=0.005)
