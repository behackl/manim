#version 330

uniform vec3 light_source_position;
uniform float gloss;
uniform float shadow;
uniform float has_texture;
uniform sampler2D image;
// Half the width of the faces' outlines in pixels; 0 for none.
uniform float edge_width;

in vec3 v_point;
in vec3 v_normal;
in vec4 v_color;
in vec2 v_uv;
in vec4 v_edge;
in vec4 v_stroke;

out vec4 frag_color;

#include ../include/add_light.glsl

void main(){
    vec4 color = v_color;
    if(bool(has_texture)){
        vec4 texel = texture(image, v_uv);
        color = vec4(texel.rgb, texel.a * v_color.a);
    }
    if(edge_width > 0.0){
        // Pixels to the nearest side of the face.
        vec4 sides = v_edge / max(fwidth(v_edge), vec4(1e-6));
        float distance = min(min(sides.x, sides.y), min(sides.z, sides.w));
        float coverage = clamp(edge_width + 0.5 - distance, 0.0, 1.0) * v_stroke.a;
        color.rgb = mix(color.rgb, v_stroke.rgb, coverage);
    }
    frag_color = add_light(
        color, v_point, normalize(v_normal), light_source_position, gloss, shadow
    );
}
