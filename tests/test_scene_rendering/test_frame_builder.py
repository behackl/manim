"""Renderers draw what a FrameBuilder makes from a scene, and nothing else."""

from __future__ import annotations

import numpy as np
import pytest

from manim import (
    BLUE,
    PURE_RED,
    RIGHT,
    Camera,
    ImageMobjectFromCamera,
    MultiCamera,
    Square,
    tempconfig,
)
from manim.renderer.cairo import CairoRenderer
from manim.renderer.frame import FrameBuilder
from manim.renderer.opengl import OpenGLRenderer
from manim.renderer.protocol import CameraView, RenderConfig


def _scene_contents():
    camera = MultiCamera(background_color=BLUE)
    view = ImageMobjectFromCamera(Camera(background_color=PURE_RED)).set(height=2)
    view.shift(3 * RIGHT)
    camera.add_image_mobject_from_camera(view)
    return camera, [Square(fill_opacity=1), view]


def test_frames_carry_the_camera_and_its_views():
    camera, mobjects = _scene_contents()
    nodes, config = FrameBuilder(160, 90).build(camera, mobjects)

    assert isinstance(config, RenderConfig)
    assert (config.pixel_width, config.pixel_height) == (160, 90)
    assert config.background_color == camera.background_color
    np.testing.assert_allclose(config.camera.center, camera.frame_center)
    assert [node.uid for node in nodes] == [m.uid for m in mobjects]
    (view,) = config.camera_views
    assert isinstance(view, CameraView)
    assert view.uid == mobjects[1].uid
    # A view does not show itself.
    assert [node.uid for node in view.nodes] == [mobjects[0].uid]
    assert view.config.pixel_height == int(90 * 2 / camera.frame_height)


@pytest.mark.parametrize("renderer_class", [CairoRenderer, OpenGLRenderer])
def test_renderers_draw_frames_without_scenes(renderer_class):
    with tempconfig(
        {"dry_run": True, "pixel_width": 160, "pixel_height": 90, "format": "none"}
    ):
        renderer = renderer_class()
        if renderer_class is OpenGLRenderer:
            from manim import Scene

            # OpenGL takes its pixel size and window settings from a scene.
            Scene(renderer=renderer)
        camera, mobjects = _scene_contents()
        try:
            pixels = renderer.render(*FrameBuilder(160, 90).build(camera, mobjects))
        finally:
            renderer.close()

    assert pixels.shape == (90, 160, 4)
    red = (pixels[..., 0] > 200) & (pixels[..., 2] < 50)
    blue_background = pixels[2, 2, 2] > 200
    assert red[:, 100:].any()  # the view shows its camera's background
    assert blue_background
