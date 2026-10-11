"""Versioned mobject properties.

A :class:`Field` is a mobject property that renderers draw from. Assigning to it
changes the field's version, so a renderer can tell whether the value changed since it
last looked.

Modifying a field's array in place (``mobject.points[0] = ...``) is deprecated: assign
a new array instead. In-place modifications are still detected when the version is read
and log a deprecation warning. Setting the environment variable
``MANIM_STRICT_FIELDS=1`` makes field arrays read-only, so in-place modifications raise
an error at the line that makes them.
"""

from __future__ import annotations

import itertools
import logging
import os
import zlib
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Generic, Self, TypeVar, overload

import numpy as np

__all__ = ["ArrayField", "Field", "check_in_place_modifications", "field_version"]

logger = logging.getLogger("manim")


#: Whether field arrays are read-only (set ``MANIM_STRICT_FIELDS=1``).
STRICT = os.environ.get("MANIM_STRICT_FIELDS", "") not in ("", "0")

T = TypeVar("T")

_warned: set[tuple[type, str]] = set()

# Versions come from one counter: a new value always gets a version that no value of
# this field had before, which is all a reader needs.
_next_version = itertools.count(1).__next__

_UNSET: Any = object()
# Types whose equal values are interchangeable and cheap to compare.
_EQ_TYPES = (int, float, bool, str)


class Field(Generic[T]):
    """A versioned property of a mobject.

    The value lives in the instance ``__dict__`` under the field's name, so code that
    walks ``__dict__`` (copying, hashing for the play cache) sees it as a plain
    attribute. Versions are kept per instance in ``_field_versions``.

    The descriptor only intercepts assignments; reads find the value in the instance
    ``__dict__`` directly and cost no more than for a plain attribute. A field must
    therefore be assigned before it is read (usually in ``__init__``): until then,
    reading it returns the descriptor itself.

    Values of a plain :class:`Field` are stored as given and must not be modified in
    place (numbers, enums, flags). Use :class:`ArrayField` for arrays.
    """

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    if TYPE_CHECKING:

        @overload
        def __get__(self, obj: None, owner: type | None = None) -> Self: ...

        @overload
        def __get__(self, obj: object, owner: type | None = None) -> T: ...

        def __get__(
            self, obj: object | None, owner: type | None = None
        ) -> Self | T: ...

    def __set__(self, obj: object, value: Any) -> None:
        name = self.name
        attributes = obj.__dict__
        old = attributes.get(name, _UNSET)
        # Assigning an equal value is not a change: keep the version.
        if old is value or (
            type(old) is type(value) and type(value) in _EQ_TYPES and old == value
        ):
            return
        attributes[name] = value
        try:
            attributes["_field_versions"][name] = _next_version()
        except KeyError:
            attributes["_field_versions"] = {name: _next_version()}

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name!r}>"


class ArrayField(Field[T]):
    """A versioned array property of a mobject.

    Assigned values are converted to arrays of the field's dtype. In strict mode the
    field stores a read-only copy (or the value itself if it is read-only already).

    Parameters
    ----------
    dtype
        The dtype assigned values are converted to; ``None`` keeps the dtype.
    """

    def __init__(self, dtype: type[np.generic] | None = None) -> None:
        self.dtype = dtype

    def __set__(self, obj: object, value: Any) -> None:
        name = self.name
        attributes = obj.__dict__
        # Assigning the array the field already holds is not a change.
        if value is attributes.get(name):
            return
        if not STRICT:
            array = np.asarray(value, dtype=self.dtype)
        elif (
            type(value) is np.ndarray
            and not value.flags.writeable
            and (self.dtype is None or value.dtype == self.dtype)
        ):
            array = value  # read-only already: safe to share
        else:
            array = np.array(value, dtype=self.dtype)
            array.flags.writeable = False
        attributes[name] = array
        try:
            attributes["_field_versions"][name] = _next_version()
        except KeyError:
            attributes["_field_versions"] = {name: _next_version()}


def field_version(obj: object, name: str) -> int:
    """Return the version of the field ``name`` of ``obj``.

    The version changes with every assignment and is 0 while nothing has been
    assigned. Outside strict mode, an in-place modification of an array value since
    the last call also changes it and logs a deprecation warning (once per class and
    field).
    """
    if not STRICT:
        check_in_place_modifications(obj, (name,))
    version: int = obj.__dict__.get("_field_versions", {}).get(name, 0)
    return version


def check_in_place_modifications(obj: object, names: Iterable[str]) -> None:
    """Give the array fields ``names`` of ``obj`` a new version if they were modified
    in place since the last check, and log a deprecation warning (once per class and
    field).

    Does nothing in strict mode, where field arrays are read-only.
    """
    if STRICT:
        return
    attributes = obj.__dict__
    versions = attributes.get("_field_versions")
    if versions is None:
        return
    checksums = attributes.setdefault("_field_checksums", {})
    for name in names:
        value = attributes.get(name)
        if not isinstance(value, np.ndarray):
            continue
        version = versions.get(name, 0)
        checksum = zlib.crc32(np.ascontiguousarray(value))
        # A checksum is only comparable if no assignment happened since it was taken.
        previous = checksums.get(name)
        if previous is not None and previous[0] == version and previous[1] != checksum:
            version = versions[name] = _next_version()
            key = (type(obj), name)
            if key not in _warned:
                _warned.add(key)
                logger.warning(
                    f"Modifying {type(obj).__name__}.{name} in place is deprecated "
                    "and will stop working in a future release; assign a new array "
                    "instead."
                )
        checksums[name] = (version, checksum)
