"""The OpenGL renderer draws meshes with textures, depth testing and lighting."""

import numpy as np

from manim import (
    BLUE,
    DEGREES,
    PURE_BLUE,
    PURE_RED,
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


def _plane(z, color, **kwargs):
    return ParametricSurface(
        lambda u, v: [u, v, z],
        u_range=[-3, 3],
        v_range=[-2, 2],
        resolution=4,
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


def test_texture_is_drawn_like_an_image(using_opengl_renderer):
    # u runs left to right across the image, v from its bottom to its top.
    texture = np.zeros((40, 60, 4), dtype=np.uint8)
    texture[..., 0] = np.linspace(0, 255, 60)[None, :]
    texture[..., 2] = np.linspace(255, 0, 40)[:, None]
    texture[..., 3] = 255

    surface, _ = _image("opengl", lambda: [_plane(0, BLUE, texture=texture)])
    image, _ = _image(
        "cairo",
        lambda: [
            ImageMobject(texture).stretch_to_fit_width(6).stretch_to_fit_height(4)
        ],
    )

    assert np.abs(surface - image).mean() < 0.01


def test_opaque_meshes_hide_what_is_behind_them(using_opengl_renderer):
    front = _plane(1, PURE_RED)
    back = _plane(-1, PURE_BLUE)

    pixels, _ = _image("opengl", lambda: [front, back], ThreeDScene)

    np.testing.assert_allclose(_pixel(pixels, 0, 0), [1, 0, 0])


def test_translucent_meshes_show_only_their_front_layer(using_opengl_renderer):
    sphere = _sphere(opacity=0.5, gloss=0, shadow=0)
    top = sphere.points[:, 2] > 0
    rgbas = np.zeros((len(top), 4))
    rgbas[:, 0], rgbas[:, 2], rgbas[:, 3] = top, ~top, 0.5
    sphere.set_vertex_colors(rgbas)

    pixels, _ = _image("opengl", lambda: [sphere], ThreeDScene)

    np.testing.assert_allclose(_pixel(pixels, 0.5, 0.5), [0.5, 0, 0], atol=0.01)


def test_meshes_are_lit_from_the_light_source(using_opengl_renderer):
    pixels, camera = _image(
        "opengl",
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


def test_meshes_fixed_in_frame_ignore_the_camera(using_opengl_renderer):
    plane = _plane(0, PURE_RED).fix_in_frame()

    pixels, _ = _image("opengl", lambda: [plane], ThreeDScene, phi=80 * DEGREES)

    np.testing.assert_allclose(_pixel(pixels, 2.5, 1.5), [1, 0, 0])
