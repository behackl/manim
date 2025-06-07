import pytest

def test_typst_settings_preamble():
    from manim.mobject.text.typst_mobject import TypstSettings

    settings = TypstSettings(
        text_font="Arial",
        text_size="12pt",
    )
    settings.add_extra_setting("text", "stroke", "(paint: blue)")

    expected_preamble = (
        '#set page(width: 10cm, height: auto)\n'
        '#set par(leading: 0.65em, justify: true, linebreaks: auto, first_line_indent: 0pt, hanging_indent: 0pt)\n'
        '#set text(font: "Arial", style: "normal", weight: "regular", stretch: 100%, size: 12pt, tracking: 0pt, spacing: 100%, cjk_latin_spacing: auto, baseline: 0pt, overhang: true, lang: "en", region: none, script: auto, dir: auto, hyphenate: auto, kerning: true, alternates: false, ligatures: true, stroke: (paint: blue))'
        '\n\n'
    )
    
    assert settings.preamble() == expected_preamble