"""Shared interfaces and values for live frame presentation."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from manim._config.render_session import RenderSessionSpec
    from manim.typing import RGBAPixelArray

__all__ = [
    "FrameInfo",
    "FramePresenter",
    "PresentationContext",
    "PresentationFrame",
]


@dataclass(frozen=True, slots=True)
class PresentationContext:
    """Immutable information about the scene being presented."""

    scene_name: str
    session_spec: RenderSessionSpec
    frame_rate: float


@dataclass(frozen=True, slots=True)
class FrameInfo:
    """Timing and progress information associated with one rendered frame."""

    play_index: int
    frame_index: int
    frame_count: int
    animation_time: float
    animation_duration: float
    scene_time: float
    skipped: bool

    @classmethod
    def for_animation(
        cls,
        *,
        play_index: int,
        animation_time: float,
        animation_duration: float,
        scene_time: float,
        frame_rate: float,
        frozen: bool = False,
        skipped: bool = False,
    ) -> FrameInfo:
        """Build progress metadata from Manim's animation timing values."""
        frame_count = max(1, math.ceil(animation_duration * frame_rate))
        if frozen:
            frame_index = frame_count
        else:
            frame_index = min(
                frame_count,
                max(1, math.floor(max(0.0, animation_time) * frame_rate) + 1),
            )
        displayed_time = min(
            animation_duration,
            frame_index / frame_rate,
        )
        return cls(
            play_index=play_index,
            frame_index=frame_index,
            frame_count=frame_count,
            animation_time=displayed_time,
            animation_duration=animation_duration,
            scene_time=scene_time,
            skipped=skipped,
        )

    @property
    def progress(self) -> float:
        """Return animation progress in the inclusive interval ``[0, 1]``."""
        if self.frame_count <= 0:
            return 1.0
        return min(1.0, max(0.0, self.frame_index / self.frame_count))


class PresentationFrame:
    """One rendered frame with lazily materialized RGBA pixels.

    Presenters are called synchronously. They may inspect :attr:`pixels` during
    :meth:`~FramePresenter.present`, but must not mutate or retain the array.
    Pixel materialization is cached so a presenter and an artifact writer share
    one renderer readback.
    """

    __slots__ = ("_pixels", "_read_pixels", "info")

    def __init__(
        self,
        read_pixels: Callable[[], RGBAPixelArray],
        info: FrameInfo,
    ) -> None:
        self._read_pixels = read_pixels
        self._pixels: RGBAPixelArray | None = None
        self.info = info

    @property
    def pixels(self) -> RGBAPixelArray:
        """Return pixels for this frame, reading them from the backend once."""
        if self._pixels is None:
            self._pixels = self._read_pixels()
        return self._pixels

    @property
    def pixels_materialized(self) -> bool:
        """Whether the backend pixel reader has already been invoked."""
        return self._pixels is not None


class FramePresenter(Protocol):
    """A synchronous consumer displaying rendered frames during a session."""

    handles_progress: bool

    def start(self, context: PresentationContext) -> None:
        """Start presenting one scene."""

    def present(self, frame: PresentationFrame) -> None:
        """Display one rendered frame without retaining or mutating its pixels."""

    def finish(self) -> None:
        """Finish the current scene and restore presentation resources."""
