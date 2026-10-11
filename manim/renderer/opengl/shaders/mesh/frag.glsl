#version 330

uniform vec3 light_source_position;
uniform float gloss;
uniform float shadow;
uniform float has_texture;
uniform sampler2D image;

in vec3 v_point;
in vec3 v_normal;
in vec4 v_color;
in vec2 v_uv;

out vec4 frag_color;

#include ../include/add_light.glsl

void main(){
    vec4 color = v_color;
    if(bool(has_texture)){
        vec4 texel = texture(image, v_uv);
        color = vec4(texel.rgb, texel.a * v_color.a);
    }
    frag_color = add_light(
        color, v_point, normalize(v_normal), light_source_position, gloss, shadow
    );
}
