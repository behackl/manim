from __future__ import annotations

import copy
from io import StringIO
from unittest.mock import Mock

import numpy as np
import pytest
from rich.console import Console

from manim import Circle, Create, Scene
from manim._config.output import OutputFormat
from manim._config.render_session import resolve_render_session
from manim.presentation import (
    FrameInfo,
    PresentationFrame,
    TerminalPresenter,
)
from manim.renderer.protocol import RendererCapabilities


class RecordingPresenter:
    handles_progress = True

    def __init__(self) -> None:
        self.contexts = []
        self.frames = []
        self.finished = 0

    def start(self, context) -> None:
        self.contexts.append(context)

    def present(self, frame) -> None:
        self.frames.append((frame.info, frame.pixels.copy()))

    def finish(self) -> None:
        self.finished += 1


def test_presentation_frame_materializes_pixels_once():
    pixels = np.zeros((2, 3, 4), dtype=np.uint8)
    read_pixels = Mock(return_value=pixels)
    info = FrameInfo.for_animation(
        play_index=0,
        animation_time=0,
        animation_duration=1,
        scene_time=0,
        frame_rate=30,
    )
    frame = PresentationFrame(read_pixels, info)

    assert frame.pixels_materialized is False
    assert frame.pixels is pixels
    assert frame.pixels is pixels
    assert frame.pixels_materialized is True
    read_pixels.assert_called_once_with()


def test_explicit_presenter_resolves_automatic_output_to_none(config):
    config.format = "auto"

    session = resolve_render_session(
        config,
        RendererCapabilities(live_preview=False),
        renderer_name="TestRenderer",
        presenter_requested=True,
    )

    assert session.presentation.live_preview is True
    assert session.output.format is OutputFormat.NONE


def test_scene_presents_cairo_frames_programmatically(config):
    config.disable_caching = True
    config.frame_rate = 5
    config.pixel_width = 64
    config.pixel_height = 36
    presenter = RecordingPresenter()

    class PresentedScene(Scene):
        def construct(self):
            self.play(Create(Circle()), run_time=0.2)

    scene = PresentedScene(presenter=presenter)
    scene.render()

    assert scene.session_spec.output.format is OutputFormat.NONE
    assert len(presenter.contexts) == 1
    assert len(presenter.frames) == 1
    assert presenter.frames[0][0].progress == 1
    assert presenter.frames[0][1].shape == (36, 64, 4)
    assert presenter.finished == 1


def test_presenter_finishes_when_scene_raises(config):
    config.format = "none"
    presenter = RecordingPresenter()

    class BrokenScene(Scene):
        def construct(self):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        BrokenScene(presenter=presenter).render()

    assert len(presenter.contexts) == 1
    assert presenter.finished == 1


def test_scene_deepcopy_shares_presenter_without_copying_it(config):
    config.format = "none"
    presenter = RecordingPresenter()
    scene = Scene(presenter=presenter)
    scene.queue = None

    clone = copy.deepcopy(scene)

    assert clone.presenter is presenter
    assert clone.manager is None


def test_terminal_half_block_uses_two_vertical_pixels():
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=True,
        color_system="truecolor",
        width=20,
        height=10,
    )
    presenter = TerminalPresenter(console=console, realtime=False)
    pixels = np.array(
        [
            [[255, 0, 0, 255]],
            [[0, 0, 255, 255]],
        ],
        dtype=np.uint8,
    )

    rendered = presenter._frame_to_text(pixels, max_width=1, max_rows=1)
    style = rendered.get_style_at_offset(console, 0)

    assert rendered.plain == "▀"
    assert style.color is not None
    assert style.color.get_truecolor().red == 255
    assert style.bgcolor is not None
    assert style.bgcolor.get_truecolor().blue == 255


def test_terminal_differential_output_only_repaints_changed_cells():
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=True,
        color_system="truecolor",
        width=20,
        height=10,
    )
    presenter = TerminalPresenter(console=console, realtime=False)
    presenter._output_file = output
    info = FrameInfo.for_animation(
        play_index=0,
        animation_time=1,
        animation_duration=1,
        scene_time=1,
        frame_rate=1,
    )
    first_pixels = np.zeros((2, 2, 4), dtype=np.uint8)
    first_pixels[:, :, 3] = 255
    first_pixels[0, 0, 0] = 255
    second_pixels = first_pixels.copy()
    second_pixels[0, 0, :3] = [0, 255, 0]

    presenter._write_differential(PresentationFrame(lambda: first_pixels, info))
    output.seek(0)
    output.truncate()
    presenter._write_differential(PresentationFrame(lambda: second_pixels, info))

    update = output.getvalue()
    assert "\x1b[2J" not in update
    assert update.count("▀") == 1
