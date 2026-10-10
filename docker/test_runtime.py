"""Offline runtime checks for the installed Docker image (no source tree needed).

Run from the repository root, substituting the image tag:
    docker run --rm --network none \
        --mount type=bind,source="$PWD/docker/test_runtime.py",target=/tmp/test_runtime.py,readonly \
        IMAGE python /tmp/test_runtime.py

Optionally set MANIM_EXPECTED_VERSION to require an exact installed version.
"""

from __future__ import annotations

import json
import math
import os
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave
from importlib.metadata import version
from pathlib import Path

SCENES = r"""
import os
from pathlib import Path

from manim import DOWN, RIGHT, Circle, MathTex, Scene, Tex, TexTemplate, Text, VGroup
from manim.scene.scene_file_writer import convert_audio


class CairoTest(Scene):
    def construct(self):
        # PyAV MP3 encode; add_sound below tests decode without FFmpeg CLI.
        convert_audio(Path("tone.wav"), Path("tone.mp3"), "libmp3lame")
        latex = TexTemplate(tex_compiler="latex", output_format=".dvi")
        xelatex = TexTemplate(tex_compiler="xelatex", output_format=".xdv")
        xelatex.add_to_preamble(r"\usepackage{fontspec}\setmainfont{Noto Sans}")
        labels = VGroup(
            Text("Pango text"),
            Tex("LaTeX text", tex_template=latex),
            MathTex(r"\int_0^1 x^2\,dx = \frac{1}{3}", tex_template=latex),
            Tex("XeLaTeX text", tex_template=xelatex),
        ).arrange(DOWN)
        assert all(label.width > 0 and label.height > 0 for label in labels)
        self.add(labels)
        self.add_sound("tone.mp3")
        self.play(labels.animate.shift(RIGHT * 0.25), run_time=0.6)
        self.wait(0.2)


class OpenGLTest(Scene):
    def construct(self):
        assert "DISPLAY" not in os.environ
        assert self.renderer.window is None
        circle = Circle(fill_opacity=1)
        self.add(circle)
        self.play(circle.animate.shift(RIGHT), run_time=0.4)
"""


def run(command: list[str], timeout: int = 180) -> str:
    """Bound each CLI invocation, including its TeX subprocesses."""
    print("+", *command, flush=True)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate(timeout=10)
        raise RuntimeError(f"Command timed out after {timeout}s:\n{output}") from None
    print(output, end="", flush=True)
    if process.returncode:
        raise RuntimeError(f"Command exited with status {process.returncode}")
    return output


def check_movie(media: Path, scene: str, *, audio: bool = False) -> None:
    """Decode actual frames/samples, rather than trusting file sizes."""
    import av

    movies = list(media.rglob(f"{scene}.mp4"))
    assert len(movies) == 1, f"Expected one final {scene} movie, got {movies}"
    with av.open(movies[0]) as movie:
        frames = list(movie.decode(video=0))
        assert frames, f"No decoded video frames in {movies[0]}"
        assert (frames[0].width, frames[0].height) == (320, 180)
        assert any(frame.to_ndarray(format="rgb24").any() for frame in frames)
    samples = 0
    if audio:
        with av.open(movies[0]) as movie:
            sound = list(movie.decode(audio=0))
            samples = sum(frame.samples for frame in sound)
            assert samples > 0, "Missing output audio samples"
            assert any(frame.to_ndarray().any() for frame in sound), (
                "Silent output audio"
            )
    print(f"[ok] {scene}: {len(frames)} decoded frames, {samples} audio samples")


def check_jupyter(work: Path) -> None:
    """Probe authenticated loopback HTTP; --network none still permits loopback."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    command = [sys.executable, "-I", "-m", "jupyterlab", "--no-browser"]
    command += ["--ip=127.0.0.1", f"--port={port}", "--ServerApp.port_retries=0"]
    command += ["--IdentityProvider.token=runtime-test", f"--ServerApp.root_dir={work}"]
    with (work / "jupyter.log").open("w+", encoding="utf-8") as log:
        server = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError("Jupyter exited before becoming ready")
                try:
                    url = f"http://127.0.0.1:{port}/api/status?token=runtime-test"
                    with opener.open(url, timeout=1) as response:
                        assert response.status == 200
                        assert "kernels" in json.load(response)
                    print("[ok] Jupyter server responded on loopback")
                    return
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.2)
            raise TimeoutError("Jupyter did not become ready within 45s")
        except Exception:
            log.flush()
            log.seek(0)
            print(log.read(), flush=True)
            raise
        finally:
            if server.poll() is None:
                server.terminate()  # SIGTERM requests Jupyter's graceful shutdown.
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGKILL)
                server.wait(timeout=5)


def main() -> None:
    assert os.geteuid() != 0, "The runtime image must use a non-root user"
    installed = version("manim")
    expected = os.environ.get("MANIM_EXPECTED_VERSION")
    assert not expected or installed == expected, (installed, expected)
    base = Path("/manim") if Path("/manim").is_dir() else Path(tempfile.gettempdir())
    with tempfile.TemporaryDirectory(prefix="manim-runtime-", dir=base) as directory:
        work = Path(directory)
        assert os.access(work, os.W_OK), f"Working directory is not writable: {work}"
        os.chdir(work)
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "PYTHONPATH"):
            os.environ.pop(key, None)
        os.environ.update(
            LIBGL_ALWAYS_SOFTWARE="1",
            EGL_PLATFORM="surfaceless",
            JUPYTER_CONFIG_DIR=str(work / "jupyter-config"),
            JUPYTER_RUNTIME_DIR=str(work / "jupyter-runtime"),
            XDG_CACHE_HOME=str(work / "cache"),
        )
        # -I excludes both the checkout and PYTHONPATH from package resolution.
        cli = [sys.executable, "-I", "-m", "manim"]
        assert f"v{installed}" in run([*cli, "--version"], timeout=30)
        run(["tlmgr", "--version"], timeout=30)
        run(["curl", "--version"], timeout=30)
        (work / "scenes.py").write_text(SCENES, encoding="utf-8")
        (work / "runtime.cfg").write_text(
            "[CLI]\ndry_run=False\npreview=False\nlive_preview=False\nenable_gui=False\n",
            encoding="utf-8",
        )
        pcm = (int(12000 * math.sin(i * math.tau / 100)) for i in range(22050))
        with wave.open("tone.wav", "wb") as tone:
            tone.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
            tone.writeframes(b"".join(struct.pack("<h", sample) for sample in pcm))
        media = work / "media"
        common = [*cli, "render", "--config_file=runtime.cfg", "--format=mp4"]
        common += ["--resolution=320,180", "--fps=15", "--disable_caching", "--silent"]
        common += ["--no_latex_cleanup", f"--media_dir={media}"]
        run([*common, "--renderer=cairo", "scenes.py", "CairoTest"])
        check_movie(media, "CairoTest", audio=True)
        for extension in ("dvi", "xdv"):
            artifacts = list((media / "Tex").glob(f"*.{extension}"))
            assert artifacts, f"Missing {extension.upper()} compiler output"
            assert all(
                path.stat().st_size and path.with_suffix(".svg").is_file()
                for path in artifacts
            ), f"Missing {extension.upper()} to SVG conversion"
        print("[ok] LaTeX/DVI and XeLaTeX/XDV converted to SVG")
        run([*common, "--renderer=opengl", "scenes.py", "OpenGLTest"])
        check_movie(media, "OpenGLTest")
        check_jupyter(work)
    print(f"[ok] Docker runtime checks passed (Manim {installed})")


if __name__ == "__main__":
    # Also isolate this script's imports from the checkout and PYTHONPATH.
    if not sys.flags.isolated:
        os.execv(sys.executable, [sys.executable, "-I", str(Path(__file__).resolve())])
    main()
