"""The animation clock and play state of a run, owned by the Manager."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _ExecutionState:
    """Animation clock, counters, and cache/skip state for one scene."""

    frame: int = 0
    """The number of frames played so far: the clock."""
    frame_rate: float | None = None
    """Set by the manager that takes over this state."""
    time_offset: float = 0.0
    """Added to the frame time; only assigning :attr:`time` changes it."""
    num_plays: int = 0
    skip_animations: bool = False
    original_skipping_status: bool = False
    animations_hashes: list[str | None] = field(default_factory=list)

    @property
    def time(self) -> float:
        """The elapsed animation time in seconds."""
        if self.frame_rate is None:
            return self.time_offset
        return self.time_offset + self.frame / self.frame_rate

    @time.setter
    def time(self, value: float) -> None:
        self.time_offset = value - (
            0.0 if self.frame_rate is None else self.frame / self.frame_rate
        )
