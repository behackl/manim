"""Cairo rendering backend."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .renderer import CairoRenderer

__all__ = ["CairoRenderer"]


def __getattr__(name: str) -> Any:
    value: Any
    if name == "CairoRenderer":
        from .renderer import CairoRenderer

        value = CairoRenderer
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    globals()[name] = value
    return value
