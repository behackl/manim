import numpy as np
import pytest

from manim import (
    BLUE,
    RED,
    WHITE,
    Dot3D,
    Mobject,
    ParametricSurface,
    Sphere,
    Square,
    Surface,
    ThreeDAxes,
    VGroup,
    VMobject,
)


def _saddle(resolution=(4, 3), **kwargs):
    return ParametricSurface(
        lambda u, v: [u, v, u * v],
        u_range=[-1, 1],
        v_range=[0, 3],
        resolution=resolution,
        **kwargs,
    )


def _uv_area(surface):
    corners = surface.points[surface.triangles][..., :2]
    (ux, uy), (vx, vy) = (
        (corners[:, 1] - corners[:, 0]).T,
        (corners[:, 2] - corners[:, 0]).T,
    )
    return (ux * vy - uy * vx) / 2


@pytest.mark.parametrize("flat", [False, True])
def test_surface_triangles_tile_the_parameter_domain(flat):
    surface = _saddle(flat=flat)

    np.testing.assert_allclose(
        surface.points[:, 2], surface.points[:, 0] * surface.points[:, 1]
    )
    # Same orientation and no overlap: the areas add up to the domain's.
    assert (_uv_area(surface) > 0).all()
    assert _uv_area(surface).sum() == pytest.approx(2 * 3)
    assert len(surface.triangles) == 2 * 4 * 3


def test_checkerboard_alternates_between_neighbouring_quads():
    surface = _saddle().set_fill_by_checkerboard(RED, BLUE)

    # Four vertices per quad, quads in (u, v) order; all of a quad's are its colour.
    colors = surface.rgbas[:, :3].reshape(4, 3, 4, 3)
    assert (colors == colors[:, :, :1]).all()
    is_red = np.isclose(colors[:, :, 0], RED.to_rgb()).all(axis=-1)
    np.testing.assert_array_equal(is_red, np.add.outer(range(4), range(3)) % 2 == 0)


def test_color_by_xyz_func_maps_values_onto_the_colorscale():
    surface = _saddle().set_color_by_xyz_func(lambda p: p[:, 2], [BLUE, WHITE], 0, 3)

    weights = np.clip(surface.points[:, 2] / 3, 0, 1)[:, None]
    expected = (1 - weights) * BLUE.to_rgb() + weights * WHITE.to_rgb()
    np.testing.assert_allclose(surface.rgbas[:, :3], expected, atol=1e-6)


def test_partial_surface_keeps_triangles_and_stops_at_the_given_proportion():
    surface = _saddle()
    partial = surface.copy().pointwise_become_partial(surface, 0, 0.5)

    np.testing.assert_array_equal(partial.triangles, surface.triangles)
    assert partial.points[:, 1].max() == pytest.approx(1.5)
    assert partial.points[:, 1].min() == pytest.approx(0)


def test_surfaces_of_different_resolution_cannot_be_aligned():
    with pytest.raises(ValueError, match="same resolution"):
        _saddle().align_points(_saddle(resolution=(5, 3)))


def test_wireframe_follows_the_parameter_lines():
    wireframe = _saddle().get_wireframe()

    assert len(wireframe) == (4 + 1) + (3 + 1)
    np.testing.assert_allclose(wireframe[0].get_start(), [-1, 0, 0])
    np.testing.assert_allclose(wireframe[0].get_end(), [-1, 3, -3])


def test_surface_colours_faces_by_value_at_their_outlines_middle():
    from manim.mobject.three_d.three_dimensions import _halfway_around

    axes = ThreeDAxes(x_range=[0, 4], y_range=[0, 4], z_range=[0, 4])
    surface = Surface(
        lambda u, v: axes.c2p(u, v, u * v / 4),
        u_range=[0, 4],
        v_range=[0, 4],
        resolution=4,
    )
    # Halfway around a face's outline, as get_midpoint of the face as a path.
    for corners, point in zip(
        surface.points[surface.get_faces()], _halfway_around(surface), strict=True
    ):
        face = VMobject().set_points_as_corners([*corners, corners[0]])
        np.testing.assert_allclose(point, face.get_midpoint(), atol=1e-9)

    surface.set_fill_by_value(axes, [(RED, 0), (WHITE, 4)], axis=2)

    values = axes.point_to_coords(_halfway_around(surface))[:, 2] / 4
    expected = (1 - values[:, None]) * RED.to_rgb() + values[:, None] * WHITE.to_rgb()
    np.testing.assert_allclose(surface.rgbas[::4, :3], expected, atol=1e-9)
    # The outlines take the faces' colours, as the faces' strokes did.
    np.testing.assert_allclose(surface.stroke_rgbas[:, :3], expected, atol=1e-9)


def test_meshes_can_be_in_vector_groups():
    group = VGroup(Square(), Sphere(), Dot3D())

    group.set_color(RED)

    assert group[1].fill_color == RED
    with pytest.raises(TypeError, match="Group instead"):
        VGroup(Square(), Mobject())


def test_partial_surfaces_show_whole_faces_with_their_outlines():
    surface = Surface(lambda u, v: [u, v, 0], resolution=4)
    surface.set_fill_by_value(
        ThreeDAxes(x_range=[0, 1], y_range=[0, 1], z_range=[0, 1]), [RED, WHITE], axis=0
    )
    partial = surface.copy().pointwise_become_partial(surface, 0, 0.5)

    assert len(partial.get_faces()) == 8
    np.testing.assert_array_equal(partial.stroke_rgbas, surface.stroke_rgbas[:8])
