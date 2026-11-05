"""When a renderer can reuse the drawing of the previous frame.

A frame draws a list of render snapshots in order. The nodes at the start of the
list that are drawn from the same values as in the previous frame, from the same
view, give the same pixels: a renderer keeps their drawing and draws only the
rest. That holds whatever changed them, so animations, updaters and direct
changes between frames need no announcement.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePath
from typing import TYPE_CHECKING, Any

from manim.renderer.snapshot import RCameraView, RImage, RMesh, RPath, RPoints

if TYPE_CHECKING:
    from manim.renderer.protocol import CameraState
    from manim.renderer.snapshot import RNode

__all__: list[str] = []


def node_key(node: RNode) -> Any:
    """What a node is drawn from: equal keys give equal drawings from one view.

    Field versions cover the arrays and style values; the payload's derived
    values that are not fields (gradient ends, depth reference, placement) are
    part of the key too. Camera views and paths colored by an image object are
    never equal: their pixels can change without a field changing.
    """
    payload = node.payload
    if isinstance(payload, RPath):
        image = payload.background_image
        if image is not None and not isinstance(image, (str, PurePath)):
            # An image object can change in place.
            return object()
        derived: tuple[Any, ...] = (
            image,
            payload.stroke_width,
            payload.background_stroke_width,
            payload.tolerance,
            _points(payload.gradient),
            _point(payload.z_reference_point),
        )
    elif isinstance(payload, RPoints):
        derived = (payload.stroke_width,)
    elif isinstance(payload, RImage):
        derived = (payload.resampling_algorithm,)
    elif isinstance(payload, RMesh):
        derived = ()
    else:
        assert isinstance(payload, RCameraView)
        return object()
    versions = node.versions
    return (
        node.uid,
        # Versions come from one counter that only goes up, so a mobject's
        # versions change exactly when their largest one or their count does.
        max(versions.values(), default=0),
        len(versions),
        node.fixed_in_frame,
        _point(node.fixed_orientation_center),
        derived,
    )


def view_key(state: CameraState, size: tuple[int, int], background: Any) -> Any:
    """What a frame's drawing depends on besides its nodes: the camera state, the
    pixel size and the background the target starts from.
    """
    return (
        tuple(size),
        _point(state.center),
        float(state.frame_width),
        float(state.frame_height),
        tuple(map(float, state.rotation.ravel())),
        state.focal_distance,
        float(state.zoom),
        _point(state.light),
        state.shade_3d,
        float(state.default_frame_width),
        background,
    )


def common_prefix(a: Sequence[Any], b: Sequence[Any]) -> int:
    """The number of equal items at the start of ``a`` and ``b``."""
    count = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        count += 1
    return count


class PrefixMemo:
    """The keys of the last frame drawn into one target, and of its view.

    :meth:`reusable` tells how many leading nodes of a new frame can be copied
    from a saved drawing, and :meth:`worth_saving` how many to save after this
    frame: the nodes that did not change since the previous frame, which are
    likely to stay unchanged in the next ones.
    """

    def __init__(self) -> None:
        self._previous_keys: list[Any] = []
        self._previous_view: Any = None
        #: Keys of the nodes whose drawing is saved, and their view.
        self.saved_keys: list[Any] = []
        self.saved_view: Any = None

    def reusable(self, keys: list[Any], view: Any) -> int:
        """How many leading nodes of ``keys`` the saved drawing holds (0 or all of it)."""
        count = len(self.saved_keys)
        if count and view == self.saved_view and keys[:count] == self.saved_keys:
            return count
        return 0

    def worth_saving(self, keys: list[Any], view: Any) -> int:
        """How many leading nodes to save after this frame, if the saved drawing
        cannot be reused: those unchanged since the previous frame.
        """
        if view != self._previous_view:
            return 0
        return common_prefix(keys, self._previous_keys)

    def saved(self, keys: list[Any], view: Any) -> None:
        self.saved_keys, self.saved_view = keys, view

    def forget_saved(self) -> None:
        self.saved_keys, self.saved_view = [], None

    def drew(self, keys: list[Any], view: Any) -> None:
        """Remember the frame just drawn, for :meth:`worth_saving`."""
        self._previous_keys, self._previous_view = keys, view

    def clear(self) -> None:
        self.forget_saved()
        self._previous_keys, self._previous_view = [], None


def _point(point: Any) -> Any:
    return None if point is None else tuple(map(float, point))


def _points(points: Any) -> Any:
    return None if points is None else tuple(_point(p) for p in points)
