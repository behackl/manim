from __future__ import annotations

import contextlib

with contextlib.suppress(ImportError):
    from dearpygui import dearpygui as dpg


from ..renderer.opengl.shader import *
from ..utils.opengl import *
