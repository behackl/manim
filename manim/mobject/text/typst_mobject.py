"""Typst-powered text and formula mobjects."""

__all__ = ["Typst", "MathTypst"]

from dataclasses import dataclass
from enum import Enum
from textwrap import dedent
from typing import TYPE_CHECKING, Literal

from manim.mobject.svg.svg_mobject import SVGMobject

class TypstLiteral(Enum):
    AUTO = "auto"
    NONE = "none"


@dataclass
class TypstSettings:
    page_width: str = "10cm"
    page_height: str = "auto"
    par_leading: str = "0.65em"
    par_justify: bool = True
    par_linebreaks: Literal[TypstLiteral.AUTO, "simple", "optimized"] = TypstLiteral.AUTO
    par_fist_line_indent: str = "0pt"
    par_hanging_indent: str = "0pt"
    text_font: str = "linux libertine"
    text_style: Literal["normal", "italic", "oblique"] = "normal"
    text_weight: int | Literal["thin", "extralight", "light", "regular", "medium", "semibold", "bold", "extrabold", "black"] = "regular"
    text_stretch: str = "100%"
    text_size: str = "11pt"
    text_tracking: str = "0pt"
    text_spacing: str = "100%"
    text_cjk_latin_spacing: Literal[TypstLiteral.AUTO, TypstLiteral.NONE] = TypstLiteral.AUTO
    text_baseline: str = "0pt"
    text_overhang: bool = True
    text_lang: str = "en"
    text_region: str | Literal[TypstLiteral.NONE] = TypstLiteral.NONE
    text_script: str | Literal[TypstLiteral.AUTO] = TypstLiteral.AUTO
    text_dir: Literal["ltr", "rtl", TypstLiteral.AUTO] = TypstLiteral.AUTO
    text_hyphenate: bool | Literal[TypstLiteral.AUTO] = TypstLiteral.AUTO
    text_kerning: bool = True
    text_alternates: bool = False
    text_ligatures: bool = True

    def preamble(self) -> str:
        return ""  # TODO: implement generation of a suitable preamble
    # careful: string literals need to be inserted with quotes,
    # typst literals without.
    




class Typst(SVGMobject):
    def __init__(
        self, 
        source: str, 
        typst_settings: TypstSettings | None = None,

        **kwargs
    ):
        self._source = source
        self._settings = typst_settings or TypstSettings()

    @property
    def source(self) -> str:
        """The Typst source used to render the mobject."""
        return self._source

    @property
    def settings(self) -> TypstSettings:
        """The settings used to render the mobject."""
        return self._settings
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.source})"
    


class MathTypst(Typst):
    pass