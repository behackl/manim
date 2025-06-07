"""Typst-powered text and formula mobjects."""

__all__ = ["Typst", "MathTypst"]

import re

from dataclasses import dataclass, fields
from enum import Enum
from textwrap import dedent
from typing import TYPE_CHECKING, Literal

from manim.mobject.svg.svg_mobject import SVGMobject


TYPST_MEASUREMENT_REGEX = re.compile(r"^\d+.*$")

class TypstLiteral(Enum):
    AUTO = "auto"
    NONE = "none"
    TRUE = "true"
    FALSE = "false"


@dataclass
class TypstSettings:
    """Settings for rendering Typst documents.

    Refer to the Typst documentation at <https://typst.app/docs/> for more details
    on the available settings and their usage.
    """
    page_width: str = "10cm"
    page_height: str | Literal[TypstLiteral.AUTO] = TypstLiteral.AUTO
    par_leading: str = "0.65em"
    par_justify: bool = True
    par_linebreaks: Literal[TypstLiteral.AUTO, "simple", "optimized"] = TypstLiteral.AUTO
    par_first_line_indent: str = "0pt"
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

    def __post_init__(self):
        self._extra_settings = {}

    def add_extra_setting(self, function_name: str, setting: str, value: str | TypstLiteral) -> None:
        """Adds a custom setting to the Typst document.

        If you add a setting whose value needs to be quoted, the quotes
        have to be added manually.

        Args:
            function_name: The Typst function to which the setting applies.
            setting: The name of the setting.
            value: The value of the setting, which can be a string or a TypstLiteral.
        """
        if function_name not in self._extra_settings:
            self._extra_settings[function_name] = {}
        if isinstance(value, TypstLiteral):
            value = value.value

        self._extra_settings[function_name][setting] = value


    def preamble(self) -> str:
        """Generates a preamble for the Typst document based on the settings."""
        settings = {}
        for field in fields(self):
            function_name, setting_name = field.name.split("_", 1)
            value = getattr(self, field.name)
            if isinstance(value, str) and not TYPST_MEASUREMENT_REGEX.match(value) and not value.startswith(('"', '(')) and '+' not in value:
                # If the value is a string that does not look like a measurement,
                # we assume it is a setting that should be quoted.
                value = f'"{value}"'
            elif isinstance(value, bool):
                # Convert boolean values to TypstLiteral for consistency
                value = TypstLiteral.TRUE if value else TypstLiteral.FALSE
            
            if isinstance(value, TypstLiteral):
                value = value.value

            if function_name not in settings:
                settings[function_name] = {}
            settings[function_name][setting_name] = value
        
        for function_name, extra_settings in self._extra_settings.items():
            if function_name not in settings:
                settings[function_name] = {}
            settings[function_name].update(extra_settings)
        preamble_lines = []
        for function_name, function_settings in settings.items():
            settings_str = ", ".join(f"{k}: {v}" for k, v in function_settings.items())
            preamble_lines.append(f"#set {function_name}({settings_str})")
        return "\n".join(preamble_lines).strip() + "\n\n"
        


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