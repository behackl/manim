from pathlib import Path

import manim.utils.opengl as opengl
from manim import *
from manim.opengl import *

# Copied from https://3b1b.github.io/manim/getting_started/example_scenes.html#surfaceexample.
# Lines that do not yet work with the Community Version are commented.


VERTEX_COLORS_SHADER = {
    "vertex_shader": """
        #version 330

        uniform mat4 u_model_matrix;
        uniform mat4 u_view_matrix;
        uniform mat4 u_projection_matrix;
        in vec4 in_vert;
        in vec4 in_color;
        out vec4 v_color;

        void main() {
            v_color = in_color;
            gl_Position = u_projection_matrix * u_view_matrix * u_model_matrix * in_vert;
        }
    """,
    "fragment_shader": """
        #version 330

        in vec4 v_color;
        out vec4 frag_color;

        void main() {
            frag_color = v_color;
        }
    """,
}


def get_plane_mesh(context):
    shader = Shader(context, source=VERTEX_COLORS_SHADER)
    attributes = np.zeros(
        18,
        dtype=[
            ("in_vert", np.float32, (4,)),
            ("in_color", np.float32, (4,)),
        ],
    )
    attributes["in_vert"] = np.array(
        [
            # xy plane
            [-1, -1, 0, 1],
            [-1, 1, 0, 1],
            [1, 1, 0, 1],
            [-1, -1, 0, 1],
            [1, -1, 0, 1],
            [1, 1, 0, 1],
            # yz plane
            [0, -1, -1, 1],
            [0, -1, 1, 1],
            [0, 1, 1, 1],
            [0, -1, -1, 1],
            [0, 1, -1, 1],
            [0, 1, 1, 1],
            # xz plane
            [-1, 0, -1, 1],
            [-1, 0, 1, 1],
            [1, 0, 1, 1],
            [-1, 0, -1, 1],
            [1, 0, -1, 1],
            [1, 0, 1, 1],
        ],
    )
    attributes["in_color"] = np.array(
        [
            # xy plane
            [1, 0, 0, 1],
            [1, 0, 0, 1],
            [1, 0, 0, 1],
            [1, 0, 0, 1],
            [1, 0, 0, 1],
            [1, 0, 0, 1],
            # yz plane
            [0, 1, 0, 1],
            [0, 1, 0, 1],
            [0, 1, 0, 1],
            [0, 1, 0, 1],
            [0, 1, 0, 1],
            [0, 1, 0, 1],
            # xz plane
            [0, 0, 1, 1],
            [0, 0, 1, 1],
            [0, 0, 1, 1],
            [0, 0, 1, 1],
            [0, 0, 1, 1],
            [0, 0, 1, 1],
        ],
    )
    return Mesh(shader, attributes)


class TextTest(Scene):
    def construct(self):
        import string

        text = Text(string.ascii_lowercase, stroke_width=4, stroke_color=BLUE).scale(2)
        text2 = (
            Text(string.ascii_uppercase, stroke_width=4, stroke_color=BLUE)
            .scale(2)
            .next_to(text, DOWN)
        )
        # self.add(text, text2)
        self.play(Write(text))
        self.play(Write(text2))
        self.interactive_embed()


class GuiTest(Scene):
    def construct(self):
        mesh = get_plane_mesh(self.renderer.context)
        # mesh.attributes["in_vert"][:, 0]
        self.add(mesh)

        def update_mesh(mesh, dt):
            mesh.model_matrix = np.matmul(
                opengl.rotation_matrix(z=dt),
                mesh.model_matrix,
            )

        mesh.add_updater(update_mesh)

        self.interactive_embed()


class GuiTest2(Scene):
    def construct(self):
        mesh = get_plane_mesh(self.renderer.context)
        mesh.attributes["in_vert"][:, 0] -= 2
        self.add(mesh)

        mesh2 = get_plane_mesh(self.renderer.context)
        mesh2.attributes["in_vert"][:, 0] += 2
        self.add(mesh2)

        def callback(sender, data):
            mesh2.attributes["in_color"][:, 3] = dpg.get_value(sender)

        self.widgets.append(
            {
                "name": "mesh2 opacity",
                "widget": "slider_float",
                "callback": callback,
                "min_value": 0,
                "max_value": 1,
                "default_value": 1,
            },
        )

        self.interactive_embed()


class ThreeDMobjectTest(Scene):
    def construct(self):
        # config["background_color"] = "#333333"

        s = Square(fill_opacity=0.5).shift(2 * RIGHT)
        self.add(s)

        sp = Sphere().shift(2 * LEFT)
        self.add(sp)

        mesh = get_plane_mesh(self.renderer.context)
        self.add(mesh)

        def update_mesh(mesh, dt):
            mesh.model_matrix = np.matmul(
                opengl.rotation_matrix(z=dt),
                mesh.model_matrix,
            )

        mesh.add_updater(update_mesh)

        self.interactive_embed()


class InlineFullScreenQuad(Scene):
    def construct(self):
        surface = FullScreenQuad(
            self.renderer.context,
            """
            #version 330


            #define TWO_PI 6.28318530718

            uniform vec2 u_resolution;
            uniform float u_time;
            out vec4 frag_color;

            //  Function from Iñigo Quiles
            //  https://www.shadertoy.com/view/MsS3Wc
            vec3 hsb2rgb( in vec3 c ){
                vec3 rgb = clamp(abs(mod(c.x*6.0+vec3(0.0,4.0,2.0),
                                         6.0)-3.0)-1.0,
                                 0.0,
                                 1.0 );
                rgb = rgb*rgb*(3.0-2.0*rgb);
                return c.z * mix( vec3(1.0), rgb, c.y);
            }

            void main(){
                vec2 st = gl_FragCoord.xy/u_resolution;
                vec3 color = vec3(0.0);

                // Use polar coordinates instead of cartesian
                vec2 toCenter = vec2(0.5)-st;
                float angle = atan(toCenter.y,toCenter.x);
                angle += u_time;
                float radius = length(toCenter)*2.0;

                // Map the angle (-PI to PI) to the Hue (from 0 to 1)
                // and the Saturation to the radius
                color = hsb2rgb(vec3((angle/TWO_PI)+0.5,radius,1.0));

                frag_color = vec4(color,1.0);
            }
            """,
        )
        surface.shader.set_uniform(
            "u_resolution",
            (config["pixel_width"], config["pixel_height"]),
        )
        shader_time = 0

        def update_surface(surface):
            nonlocal shader_time
            surface.shader.set_uniform("u_time", shader_time)
            shader_time += 1 / 60.0

        surface.add_updater(update_surface)
        self.add(surface)
        # self.wait(5)
        self.interactive_embed()


class SimpleInlineFullScreenQuad(Scene):
    def construct(self):
        surface = FullScreenQuad(
            self.renderer.context,
            """
            #version 330

            uniform float v_red;
            uniform float v_green;
            uniform float v_blue;
            out vec4 frag_color;

            void main() {
              frag_color = vec4(v_red, v_green, v_blue, 1);
            }
            """,
        )
        surface.shader.set_uniform("v_red", 0)
        surface.shader.set_uniform("v_green", 0)
        surface.shader.set_uniform("v_blue", 0)

        increase = True
        val = 0.5
        surface.shader.set_uniform("v_red", val)
        surface.shader.set_uniform("v_green", val)
        surface.shader.set_uniform("v_blue", val)

        def update_surface(mesh, dt):
            nonlocal increase
            nonlocal val
            if increase:
                val += dt
            else:
                val -= dt
            if val >= 1:
                increase = False
            elif val <= 0:
                increase = True
            surface.shader.set_uniform("v_red", val)
            surface.shader.set_uniform("v_green", val)
            surface.shader.set_uniform("v_blue", val)

        surface.add_updater(update_surface)

        self.add(surface)
        self.wait(5)


class InlineShaderExample(Scene):
    def construct(self):
        config["background_color"] = "#333333"

        c = Circle(fill_opacity=0.7).shift(UL)
        self.add(c)

        shader = Shader(
            self.renderer.context,
            source={
                "vertex_shader": """
                #version 330

                in vec4 in_vert;
                in vec4 in_color;
                out vec4 v_color;
                uniform mat4 u_model_view_matrix;
                uniform mat4 u_projection_matrix;

                void main() {
                    v_color = in_color;
                    vec4 camera_space_vertex = u_model_view_matrix * in_vert;
                    vec4 clip_space_vertex = u_projection_matrix * camera_space_vertex;
                    gl_Position = clip_space_vertex;
                }
            """,
                "fragment_shader": """
            #version 330

            in vec4 v_color;
            out vec4 frag_color;

            void main() {
              frag_color = v_color;
            }
            """,
            },
        )
        shader.set_uniform("u_model_view_matrix", opengl.view_matrix())
        shader.set_uniform(
            "u_projection_matrix",
            opengl.orthographic_projection_matrix(),
        )

        attributes = np.zeros(
            6,
            dtype=[
                ("in_vert", np.float32, (4,)),
                ("in_color", np.float32, (4,)),
            ],
        )
        attributes["in_vert"] = np.array(
            [
                [-1, -1, 0, 1],
                [-1, 1, 0, 1],
                [1, 1, 0, 1],
                [-1, -1, 0, 1],
                [1, -1, 0, 1],
                [1, 1, 0, 1],
            ],
        )
        attributes["in_color"] = np.array(
            [
                [0, 0, 1, 1],
                [0, 0, 1, 1],
                [0, 0, 1, 1],
                [0, 0, 1, 1],
                [0, 0, 1, 1],
                [0, 0, 1, 1],
            ],
        )
        mesh = Mesh(shader, attributes)
        self.add(mesh)

        self.wait(5)
        # self.embed_2()


class InteractiveDevelopment(Scene):
    def construct(self):
        circle = Circle()
        circle.set_fill(BLUE, opacity=0.5)
        circle.set_stroke(BLUE_E, width=4)
        square = Square()

        self.play(Create(square))
        self.wait()

        # This opens an iPython terminal where you can keep writing
        # lines as if they were part of this construct method.
        # In particular, 'square', 'circle' and 'self' will all be
        # part of the local namespace in that terminal.
        # self.embed()

        # Try copying and pasting some of the lines below into
        # the interactive shell
        self.play(ReplacementTransform(square, circle))
        self.wait()
        self.play(circle.animate.stretch(4, 0))
        self.play(Rotate(circle, 90 * DEGREES))
        self.play(circle.animate.shift(2 * RIGHT).scale(0.25))

        # text = Text(
        #     """
        #     In general, using the interactive shell
        #     is very helpful when developing new scenes
        # """
        # )
        # self.play(Write(text))

        # # In the interactive shell, you can just type
        # # play, add, remove, clear, wait, save_state and restore,
        # # instead of self.play, self.add, self.remove, etc.

        # # To interact with the window, type touch().  You can then
        # # scroll in the window, or zoom by holding down 'z' while scrolling,
        # # and change camera perspective by holding down 'd' while moving
        # # the mouse.  Press 'r' to reset to the standard camera position.
        # # Press 'q' to stop interacting with the window and go back to
        # # typing new commands into the shell.

        # # In principle you can customize a scene to be responsive to
        # # mouse and keyboard interactions
        # always(circle.move_to, self.mouse_point)


class SurfaceExample(ThreeDScene):
    def construct(self):
        surface_text = Text("For 3d scenes, try using surfaces")
        surface_text.to_edge(UP)
        self.add_fixed_in_frame_mobjects(surface_text)
        self.wait(0.1)

        def sphere(u, v, radius=3):
            return radius * np.array(
                [np.cos(u) * np.sin(v), np.sin(u) * np.sin(v), -np.cos(v)]
            )

        def torus(u, v, major_radius, minor_radius):
            return np.array(
                [
                    (major_radius + minor_radius * np.cos(v)) * np.cos(u),
                    (major_radius + minor_radius * np.cos(v)) * np.sin(u),
                    minor_radius * np.sin(v),
                ]
            )

        # The texture is drawn onto the parameter domain: u runs left to right
        # across the image, v from its bottom to its top.
        texture = (
            Path(__file__).resolve().parent
            / "assets"
            / "1280px-Whole_world_-_land_and_oceans.jpg"
        )
        # Surfaces with the same resolution can be transformed into each other.
        surfaces = [
            ParametricSurface(
                func,
                u_range=[0, TAU],
                v_range=v_range,
                resolution=(64, 32),
                texture=texture,
            )
            for func, v_range in [
                (sphere, [0, PI]),
                (lambda u, v: torus(u, v, 1, 1), [0, TAU]),
                (lambda u, v: torus(u, v, 3, 1), [0, TAU]),
            ]
        ]
        for mob in surfaces:
            mob.shift(IN)

        self.set_camera_orientation(phi=70 * DEGREES, theta=-30 * DEGREES)

        surface = surfaces[0]
        wireframe = surface.get_wireframe(color=BLUE, stroke_width=0.5)
        self.play(
            FadeIn(surface),
            Create(wireframe, lag_ratio=0.01, run_time=3),
        )
        self.play(FadeOut(wireframe))
        self.play(Rotate(surface, PI / 2), run_time=2)
        for mob in surfaces[1:]:
            mob.rotate(PI / 2)

        self.play(Transform(surface, surfaces[1]), run_time=3)

        # Move the camera during the transition.
        self.move_camera(
            phi=60 * DEGREES,
            theta=-50 * DEGREES,
            added_anims=[Transform(surface, surfaces[2])],
            run_time=3,
        )
        self.begin_ambient_camera_rotation(rate=-0.1)

        # Play around with where the light is.
        light_text = Text("You can move around the light source")
        light_text.move_to(surface_text)
        self.add_fixed_in_frame_mobjects(light_text)
        self.play(FadeTransform(surface_text, light_text))
        light = self.camera.light_source
        self.play(light.animate.move_to(3 * IN), run_time=5)
        self.play(light.animate.shift(10 * OUT), run_time=5)
