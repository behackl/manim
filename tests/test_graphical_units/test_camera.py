from __future__ import annotations

from manim import (
    BLUE,
    GREEN,
    RED,
    RIGHT,
    Dot,
    NumberPlane,
    Scene,
    Square,
    ZoomedScene,
)
from manim.utils.testing.frames_comparison import frames_comparison

__module_test__ = "camera"


@frames_comparison(base_scene=Scene)
def test_moving_camera_frame(scene: Scene):
    plane = NumberPlane()
    marker = Dot(2 * RIGHT, color=RED)
    scene.add(plane, marker)
    scene.play(scene.camera.frame.animate.set(width=6).move_to(marker))


@frames_comparison(base_scene=ZoomedScene)
def test_zoomed_camera_view(scene: ZoomedScene):
    square = Square(color=BLUE, fill_opacity=0.35)
    dot = Dot(color=GREEN)
    scene.add(square, dot)
    scene.activate_zooming(animate=False)
    scene.play(dot.animate.shift(RIGHT))
