"""Rich-based terminal presentation of rasterized frames."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, TextIO

import numpy as np
from PIL import Image
from rich.align import Align
from rich.color import Color
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.progress_bar import ProgressBar
from rich.style import Style
from rich.table import Table
from rich.text import Text

from manim._config import console as default_console

if TYPE_CHECKING:
    from manim.typing import RGBAPixelArray

    from .protocol import PresentationContext, PresentationFrame

__all__ = ["TerminalPresenter"]

RGBColor = tuple[int, int, int]
TerminalCell = tuple[RGBColor, RGBColor]


class TerminalPresenter:
    """Display rendered RGBA frames and progress directly in a terminal.

    Two vertical image pixels are represented by one upper-half block character.
    The upper pixel becomes the foreground color and the lower pixel becomes the
    background color, providing true-color output at twice the terminal's row
    resolution.

    Parameters
    ----------
    max_fps
        Maximum number of terminal redraws per second. Intermediate rendered
        frames are omitted from presentation when necessary.
    realtime
        Whether animations that render faster than their requested duration are
        paced in real time. Cached and otherwise skipped animations are not paced.
    leave_last_frame
        Whether the last rendered terminal frame remains visible after rendering.
    console
        Rich console used for display. Manim's shared console is used by default.
    background_color
        RGB color used to composite transparent frame pixels.
    """

    handles_progress = True

    def __init__(
        self,
        *,
        max_fps: float = 15,
        realtime: bool = True,
        leave_last_frame: bool = True,
        console: Console | None = None,
        background_color: tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        if max_fps <= 0:
            raise ValueError("max_fps must be positive.")
        if len(background_color) != 3 or not all(
            0 <= channel <= 255 for channel in background_color
        ):
            raise ValueError(
                "background_color must contain three values from 0 to 255."
            )

        self.max_fps = float(max_fps)
        self.realtime = realtime
        self.leave_last_frame = leave_last_frame
        self.console = default_console if console is None else console
        self.background_color = background_color
        self._context: PresentationContext | None = None
        self._live: Live | None = None
        self._last_refresh = -float("inf")
        self._last_frame: PresentationFrame | None = None
        self._last_rendered_frame: PresentationFrame | None = None
        self._play_index: int | None = None
        self._play_started_at = 0.0
        self._differential = False
        self._previous_cells: list[list[TerminalCell | None]] | None = None
        self._terminal_size: tuple[int, int] | None = None
        self._output_file: TextIO | None = None

    def start(self, context: PresentationContext) -> None:
        """Start the Rich live region for a scene."""
        if self._live is not None:
            self.finish()
        self._context = context
        self._last_refresh = -float("inf")
        self._last_frame = None
        self._last_rendered_frame = None
        self._play_index = None
        self._differential = self.console.is_terminal and not self.console.is_jupyter
        self._previous_cells = None
        self._terminal_size = None
        # Live redirects sys.stdout; retain the actual terminal stream for raw,
        # batched cursor-addressed writes before enabling that redirection.
        self._output_file = self.console.file
        self._live = Live(
            Text(""),
            console=self.console,
            auto_refresh=False,
            transient=not self.leave_last_frame,
            redirect_stdout=True,
            redirect_stderr=True,
            screen=self._differential,
            vertical_overflow="crop",
        )
        self._live.start(refresh=not self._differential)

    def present(self, frame: PresentationFrame) -> None:
        """Update the terminal image, throttling expensive terminal redraws."""
        self._last_frame = frame
        now = time.monotonic()
        if self.realtime and not frame.info.skipped:
            if frame.info.play_index != self._play_index:
                self._play_index = frame.info.play_index
                self._play_started_at = now
            delay = self._play_started_at + frame.info.animation_time - now
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
        final_frame = frame.info.frame_index >= frame.info.frame_count
        if not final_frame and now - self._last_refresh < 1 / self.max_fps:
            return
        self._refresh(frame)
        self._last_refresh = now

    def finish(self) -> None:
        """Show the most recent frame and close the Rich live region."""
        live = self._live
        if live is None:
            return
        if (
            self._last_frame is not None
            and self._last_frame is not self._last_rendered_frame
        ):
            self._refresh(self._last_frame)
        live.stop()
        if (
            self._differential
            and self.leave_last_frame
            and self._last_frame is not None
        ):
            self.console.print(self._renderable(self._last_frame))
        self._live = None
        self._context = None
        self._last_frame = None
        self._last_rendered_frame = None
        self._play_index = None
        self._differential = False
        self._previous_cells = None
        self._terminal_size = None
        self._output_file = None

    def _refresh(self, frame: PresentationFrame) -> None:
        live = self._live
        if live is None:
            return
        if self._differential:
            self._write_differential(frame)
        else:
            live.update(self._renderable(frame), refresh=True)
        self._last_rendered_frame = frame

    def _write_differential(self, frame: PresentationFrame) -> None:
        """Paint only terminal cells which differ from the previous frame."""
        terminal_width = max(1, self.console.size.width)
        terminal_height = max(2, self.console.size.height)
        terminal_size = (terminal_width, terminal_height)
        image_rows = max(1, terminal_height - 2)
        image_cells = self._frame_to_cells(
            frame.pixels,
            max_width=terminal_width,
            max_rows=image_rows,
        )
        cells: list[list[TerminalCell | None]] = [
            [None] * terminal_width for _ in range(image_rows)
        ]
        x_offset = max(0, (terminal_width - len(image_cells[0])) // 2)
        for y, row in enumerate(image_cells[:image_rows]):
            cells[y][x_offset : x_offset + len(row)] = row

        previous = self._previous_cells
        resized = terminal_size != self._terminal_size
        if resized:
            previous = None

        changed = self._changed_cell_count(previous, cells)
        total_cells = terminal_width * image_rows
        full_repaint = previous is None or changed > total_cells * 0.55

        chunks: list[str] = []
        if full_repaint:
            chunks.append("\x1b[2J")
            previous = [[None] * terminal_width for _ in range(image_rows)]
        chunks.extend(self._changed_runs(previous, cells))
        chunks.append(f"\x1b[{terminal_height};1H\x1b[2K")
        chunks.append(self._progress_ansi(frame, terminal_width))
        chunks.append("\x1b[0m")

        output = self._output_file
        if output is None:
            return
        output.write("".join(chunks))
        output.flush()
        self._previous_cells = cells
        self._terminal_size = terminal_size

    @staticmethod
    def _changed_cell_count(
        previous: list[list[TerminalCell | None]] | None,
        current: list[list[TerminalCell | None]],
    ) -> int:
        if previous is None:
            return sum(len(row) for row in current)
        return sum(
            previous_cell != current_cell
            for previous_row, current_row in zip(previous, current, strict=True)
            for previous_cell, current_cell in zip(
                previous_row,
                current_row,
                strict=True,
            )
        )

    def _changed_runs(
        self,
        previous: list[list[TerminalCell | None]] | None,
        current: list[list[TerminalCell | None]],
    ) -> list[str]:
        """Encode changed horizontal cell runs with absolute cursor movement."""
        chunks: list[str] = []
        for y, row in enumerate(current):
            changed_columns = [
                x
                for x, cell in enumerate(row)
                if previous is None or cell != previous[y][x]
            ]
            if not changed_columns:
                continue

            run_start = changed_columns[0]
            run_end = run_start
            for column in changed_columns[1:]:
                # Repainting a tiny unchanged gap costs less than another cursor
                # positioning escape sequence.
                if column <= run_end + 3:
                    run_end = column
                    continue
                chunks.append(
                    self._encode_run(y, run_start, row[run_start : run_end + 1])
                )
                run_start = run_end = column
            chunks.append(self._encode_run(y, run_start, row[run_start : run_end + 1]))
        return chunks

    @staticmethod
    def _encode_run(
        row: int,
        column: int,
        cells: list[TerminalCell | None],
    ) -> str:
        chunks = [f"\x1b[{row + 1};{column + 1}H"]
        active_cell: TerminalCell | None = None
        for cell in cells:
            if cell is None:
                if active_cell is not None:
                    chunks.append("\x1b[0m")
                    active_cell = None
                chunks.append(" ")
                continue
            if cell != active_cell:
                foreground, background = cell
                chunks.append(
                    "\x1b[38;2;"
                    f"{foreground[0]};{foreground[1]};{foreground[2]};"
                    "48;2;"
                    f"{background[0]};{background[1]};{background[2]}m"
                )
                active_cell = cell
            chunks.append("▀")
        chunks.append("\x1b[0m")
        return "".join(chunks)

    @staticmethod
    def _progress_ansi(
        frame: PresentationFrame,
        terminal_width: int,
    ) -> str:
        info = frame.info
        label = f"Animation {info.play_index}"
        timing = f"{info.animation_time:.2f}/{info.animation_duration:.2f}s"
        percent = f"{info.progress:.0%}"
        fixed_width = len(label) + len(timing) + len(percent) + 6
        if terminal_width <= fixed_width:
            compact = f"{percent} {timing}"[:terminal_width]
            return f"\x1b[1m{compact}\x1b[0m"
        bar_width = max(1, terminal_width - fixed_width)
        completed = round(bar_width * info.progress)
        bar = "━" * completed + "─" * (bar_width - completed)
        return (
            f"\x1b[1;36m{label}\x1b[0m "
            f"\x1b[32m{bar}\x1b[0m "
            f"\x1b[1m{percent:>4}\x1b[0m "
            f"\x1b[2m{timing}\x1b[0m"
        )

    def _renderable(self, frame: PresentationFrame) -> RenderableType:
        terminal_width = max(1, self.console.size.width)
        terminal_height = max(1, self.console.size.height)
        image_rows = max(1, terminal_height - 2)
        image = self._frame_to_text(
            frame.pixels,
            max_width=terminal_width,
            max_rows=image_rows,
        )
        return Group(
            Align.center(image),
            self._progress_row(frame, terminal_width),
        )

    def _progress_row(
        self,
        frame: PresentationFrame,
        terminal_width: int,
    ) -> RenderableType:
        info = frame.info
        label = f"Animation {info.play_index}"
        timing = f"{info.animation_time:.2f}/{info.animation_duration:.2f}s"
        percent = f"{info.progress:>4.0%}"
        bar_width = max(4, terminal_width - len(label) - len(timing) - len(percent) - 6)

        row = Table.grid(expand=True, padding=(0, 1))
        row.add_column(no_wrap=True)
        row.add_column(ratio=1)
        row.add_column(no_wrap=True)
        row.add_column(no_wrap=True)
        row.add_row(
            Text(label, style="bold cyan"),
            ProgressBar(
                total=max(1, info.frame_count),
                completed=max(0, info.frame_index),
                width=bar_width,
            ),
            Text(percent, style="bold"),
            Text(timing, style="dim"),
        )
        return row

    def _frame_to_text(
        self,
        pixels: RGBAPixelArray,
        *,
        max_width: int,
        max_rows: int,
    ) -> Text:
        cells = self._frame_to_cells(
            pixels,
            max_width=max_width,
            max_rows=max_rows,
        )
        text = Text(no_wrap=True, overflow="crop")
        for y, row in enumerate(cells):
            for foreground, background in row:
                text.append(
                    "▀",
                    style=Style(
                        color=Color.from_rgb(*foreground),
                        bgcolor=Color.from_rgb(*background),
                    ),
                )
            if y + 1 < len(cells):
                text.append("\n")
        return text

    def _frame_to_cells(
        self,
        pixels: RGBAPixelArray,
        *,
        max_width: int,
        max_rows: int,
    ) -> list[list[TerminalCell]]:
        image = Image.fromarray(pixels, mode="RGBA")
        background = Image.new("RGBA", image.size, (*self.background_color, 255))
        image = Image.alpha_composite(background, image).convert("RGB")
        image.thumbnail(
            (max(1, max_width), max(2, max_rows * 2)),
            Image.Resampling.BOX,
        )
        array = np.asarray(image, dtype=np.uint8)

        fallback = np.asarray(self.background_color, dtype=np.uint8)
        rows: list[list[TerminalCell]] = []
        for y in range(0, array.shape[0], 2):
            upper = array[y]
            lower = array[y + 1] if y + 1 < array.shape[0] else None
            row: list[TerminalCell] = []
            for x, upper_pixel in enumerate(upper):
                lower_pixel = fallback if lower is None else lower[x]
                row.append(
                    (
                        tuple(int(channel) for channel in upper_pixel),
                        tuple(int(channel) for channel in lower_pixel),
                    )
                )
            rows.append(row)
        return rows
