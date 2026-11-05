from __future__ import annotations

import platform

import numpy as np
import pytest

from manim import RIGHT, Square
from manim.renderer.opengl import OpenGLRenderer
from tests.assert_utils import assert_file_exists
from tests.test_scene_rendering.simple_scenes import *


def test_file_output_disables_window(
    config, using_temp_opengl_config, disabling_caching
):
    """File output should disable the window by default."""
    scene = SquareToCircle()
    renderer = scene.renderer
    scene.render()
    assert renderer.window is None
    assert_file_exists(scene._get_manager().file_writer.final_file_path)


@pytest.mark.skip(reason="Temporarily skip due to failing in Windows CI")
def test_live_preview_opengl_render_with_movies(
    config,
    using_temp_opengl_config,
    live_preview_config_movie,
    disabling_caching,
):
    """Live preview can be displayed while movie output is enabled."""
    scene = SquareToCircle()
    renderer = scene.renderer
    with scene._get_manager():
        scene.render()
        assert renderer.window is not None
        assert_file_exists(scene._get_manager().file_writer.final_file_path)
    assert renderer.window is None


@pytest.mark.skipif(
    platform.processor() == "aarch64", reason="Fails on Linux-ARM runners"
)
def test_live_preview_opengl_render_with_image_sequence(
    using_temp_opengl_config,
    live_preview_config_pngs,
    disabling_caching,
):
    """Live preview can be displayed while an image sequence is written."""
    scene = SquareToCircle()
    renderer = scene.renderer
    with scene._get_manager():
        scene.render()
        assert renderer.window is not None
    assert renderer.window is None


def test_frames_have_the_scene_size_without_a_live_preview(
    config, using_opengl_renderer
):
    config.live_preview = False
    scene = SquareToCircle()
    assert isinstance(scene.renderer, OpenGLRenderer)

    frame = scene.renderer.render(*scene._get_manager()._frame())

    assert frame.shape == (config.pixel_height, config.pixel_width, 4)
    assert frame.dtype == np.uint8
    assert frame.flags.c_contiguous


@pytest.mark.slow
def test_frames_have_the_scene_size_with_a_live_preview(config, using_opengl_renderer):
    # The window can have any size; frames are drawn offscreen at the scene's.
    config.live_preview = True
    config.window_size = (100, 300)

    scene = SquareToCircle()
    renderer = scene.renderer
    renderer.open()
    try:
        assert renderer.window is not None
        frame = renderer.render(*scene._get_manager()._frame())
        assert frame.shape == (config.pixel_height, config.pixel_width, 4)
        renderer.present()
        scene.add(Square(fill_opacity=1))
        image = scene.get_image()
        assert image.size == (config.pixel_width, config.pixel_height)
        assert not np.array_equal(image, frame)
    finally:
        renderer.close()


def test_window_positions_map_to_scene_points(config, using_opengl_renderer):
    config.live_preview = False
    scene = SquareToCircle()
    scene.camera.frame.shift(RIGHT)
    renderer = scene.renderer
    width, height = scene.camera.frame_width, scene.camera.frame_height
    center = scene.camera.frame_center

    np.testing.assert_allclose(renderer._scene_point(0.5, 0.5, False), center)
    np.testing.assert_allclose(
        renderer._scene_point(0, 1, False), center + [-width / 2, height / 2, 0]
    )
    np.testing.assert_allclose(renderer._scene_point(0.25, 0, True), [width / 4, 0, 0])


def test_moving_camera_frame_animates(config, using_opengl_renderer):
    from manim import MovingCameraScene

    config.dry_run = True

    class PanAndZoom(MovingCameraScene):
        def construct(self):
            self.add(Square())
            self.play(self.camera.frame.animate.scale(0.5).shift(RIGHT))

    scene = PanAndZoom()
    scene.render()
    np.testing.assert_allclose(scene.camera.frame_center, RIGHT, atol=1e-12)


@pytest.mark.slow
def test_movies_are_written_at_the_scene_size_with_a_live_preview(
    config, using_opengl_renderer, tmp_path
):
    # The window has another size than the movie; it used to be drawn into.
    config.live_preview = True
    config.format = "mp4"
    config.window_size = (100, 300)
    config.media_dir = str(tmp_path)
    config.disable_caching = True

    scene = SquareToCircle()
    with scene._get_manager() as manager:
        manager.render()
        assert scene.renderer.window is not None
        assert_file_exists(manager.file_writer.final_file_path)
