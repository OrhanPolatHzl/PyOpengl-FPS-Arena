"""Single-file OpenGL 3.3 FPS test arena with directional shadows + Dear ImGui.

Requires: numpy, glfw, PyOpenGL and EITHER imgui-bundle OR imgui (pyimgui).
Run in the currently selected Python environment: python main.py

Controls: WASD move, mouse look, Q toggle mouse capture, ESC quit.
"""

from __future__ import annotations

import ctypes
import math
import os
import sys
from dataclasses import dataclass

# On Linux/Wayland, PyOpenGL's native-context detection can need this workaround.
if os.environ.get("XDG_SESSION_TYPE") == "wayland" and not os.environ.get("PYOPENGL_PLATFORM"):
    os.environ["PYOPENGL_PLATFORM"] = "x11"

try:
    import glfw
    import numpy as np
    from OpenGL.GL import (
        GL_ARRAY_BUFFER, GL_BACK, GL_CLAMP_TO_BORDER, GL_COLOR_BUFFER_BIT,
        GL_COMPILE_STATUS, GL_CULL_FACE, GL_DEPTH_ATTACHMENT,
        GL_DEPTH_BUFFER_BIT, GL_DEPTH_COMPONENT, GL_DEPTH_COMPONENT24,
        GL_DEPTH_TEST, GL_FALSE, GL_FLOAT, GL_FRAGMENT_SHADER,
        GL_FRAMEBUFFER, GL_FRAMEBUFFER_COMPLETE, GL_FRONT, GL_LINEAR,
        GL_NEAREST, GL_NONE, GL_POLYGON_OFFSET_FILL, GL_STATIC_DRAW,
        GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE_2D, GL_TEXTURE_BORDER_COLOR,
        GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_S,
        GL_TEXTURE_WRAP_T, GL_TRIANGLES, GL_TRUE, GL_VERTEX_SHADER,
        GL_VIEWPORT, GL_LINK_STATUS,
        glActiveTexture, glAttachShader, glBindBuffer, glBindFramebuffer,
        glBindTexture, glBindVertexArray, glBufferData, glCheckFramebufferStatus,
        glClear, glClearColor, glCullFace, glDeleteBuffers, glDeleteFramebuffers,
        glDeleteProgram, glDeleteShader, glDeleteTextures, glDeleteVertexArrays,
        glDisable, glDrawArrays, glDrawBuffer, glEnable, glEnableVertexAttribArray,
        glFramebufferTexture2D, glGenBuffers, glGenFramebuffers, glGenTextures,
        glGenVertexArrays, glGetProgramInfoLog, glGetProgramiv,
        glGetShaderInfoLog, glGetShaderiv, glGetUniformLocation,
        glLinkProgram, glPolygonOffset, glReadBuffer, glShaderSource,
        glTexImage2D, glTexParameteri, glTexParameterfv, glUniform1f,
        glUniform1i, glUniform3f, glUniformMatrix4fv, glUseProgram,
        glVertexAttribPointer, glViewport, glCreateProgram, glCreateShader,
        glCompileShader,
    )
except ImportError as exc:
    raise SystemExit(
        f"Missing package: {exc}. In your existing environment, install only missing "
        "modules: python -m pip install numpy glfw PyOpenGL"
    ) from exc

# Prefer imgui_bundle (the user's existing installation may already provide it).
try:
    from imgui_bundle import imgui
    from imgui_bundle.python_backends.glfw_backend import GlfwRenderer
    USING_IMGUI_BUNDLE = True
except ImportError:
    try:
        import imgui
        from imgui.integrations.glfw import GlfwRenderer
        USING_IMGUI_BUNDLE = False
    except ImportError as exc:
        raise SystemExit(
            "An ImGui backend is missing. Install ONE of: "
            "python -m pip install 'imgui-bundle[glfw,opengl]' "
            "or python -m pip install 'imgui[glfw]'"
        ) from exc


WIDTH, HEIGHT = 1280, 720
SHADOW_SIZE = 2048
PLAYER_HEIGHT = 1.80
EYE_HEIGHT = 1.66
PLAYER_RADIUS = 0.35
MOUSE_SENSITIVITY = 0.092
WORLD_UP = np.array([0.0, 1.0, 0.0], dtype=np.float32)


SCENE_VS = """#version 330 core
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;
uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProjection;
uniform mat4 uLightSpace;
out vec3 vNormal;
out vec3 vWorldPos;
out vec4 vLightPos;
void main() {
    vec4 worldPos = uModel * vec4(aPos, 1.0);
    vWorldPos = worldPos.xyz;
    // All models are translated and axis-aligned scaled cubes. Unit cube
    // face normals remain valid under those transformations.
    vNormal = aNormal;
    vLightPos = uLightSpace * worldPos;
    gl_Position = uProjection * uView * worldPos;
}
"""

SCENE_FS = """#version 330 core
in vec3 vNormal;
in vec3 vWorldPos;
in vec4 vLightPos;
out vec4 FragColor;
uniform vec3 uBaseColor;
uniform vec3 uLightColor;
uniform vec3 uLightDir;  // direction travelled by sun rays
uniform vec3 uCameraPos;
uniform float uIntensity;
uniform float uAmbient;
uniform int uUseShadows;
uniform sampler2D uShadowMap;

float calculateShadow(vec4 lightPosition, vec3 normal, vec3 lightTowardSun) {
    vec3 projected = lightPosition.xyz / lightPosition.w;
    projected = projected * 0.5 + 0.5;
    if (projected.z <= 0.0 || projected.z >= 1.0 ||
        projected.x < 0.0 || projected.x > 1.0 ||
        projected.y < 0.0 || projected.y > 1.0) return 0.0;

    float incidence = max(dot(normal, lightTowardSun), 0.0);
    float bias = max(0.0015 * (1.0 - incidence), 0.00032);
    vec2 texel = 1.0 / vec2(textureSize(uShadowMap, 0));
    float shadow = 0.0;
    for (int y = -1; y <= 1; ++y) {
        for (int x = -1; x <= 1; ++x) {
            float closestDepth = texture(uShadowMap, projected.xy + vec2(x, y) * texel).r;
            shadow += (projected.z - bias > closestDepth) ? 1.0 : 0.0;
        }
    }
    return shadow / 9.0; // simple 3x3 PCF
}

void main() {
    vec3 n = normalize(vNormal);
    vec3 towardSun = normalize(-uLightDir);
    float diffuse = max(dot(n, towardSun), 0.0);
    float shadow = (uUseShadows == 1 && diffuse > 0.0)
        ? calculateShadow(vLightPos, n, towardSun) : 0.0;

    vec3 lighting = vec3(uAmbient) +
        (1.0 - shadow) * diffuse * uIntensity * uLightColor;
    vec3 linearColor = uBaseColor * lighting;
    // Simple distance haze for spatial depth (lightweight, non-PBR).
    float distanceToCamera = length(vWorldPos - uCameraPos);
    float fog = 1.0 - exp(-0.00065 * distanceToCamera * distanceToCamera);
    vec3 skyColor = vec3(0.60, 0.72, 0.82);
    linearColor = mix(linearColor, skyColor, clamp(fog, 0.0, 0.35));
    FragColor = vec4(pow(max(linearColor, vec3(0.0)), vec3(1.0 / 2.2)), 1.0);
}
"""

DEPTH_VS = """#version 330 core
layout(location = 0) in vec3 aPos;
uniform mat4 uModel;
uniform mat4 uLightSpace;
void main() {
    gl_Position = uLightSpace * uModel * vec4(aPos, 1.0);
}
"""

DEPTH_FS = """#version 330 core
void main() { }
"""


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    z: float
    sx: float
    sy: float
    sz: float
    color: tuple[float, float, float]
    solid: bool = True
    casts_shadow: bool = True

    def model_matrix(self) -> np.ndarray:
        matrix = np.eye(4, dtype=np.float32)
        matrix[0, 0], matrix[1, 1], matrix[2, 2] = self.sx, self.sy, self.sz
        matrix[0, 3], matrix[1, 3], matrix[2, 3] = self.x, self.y, self.z
        return matrix


def normalized(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    return (vector / length).astype(np.float32) if length > 1e-8 else vector


def perspective(fov_degrees: float, aspect: float, near: float, far: float) -> np.ndarray:
    focus = 1.0 / math.tan(math.radians(fov_degrees) * 0.5)
    matrix = np.zeros((4, 4), dtype=np.float32)
    matrix[0, 0] = focus / aspect
    matrix[1, 1] = focus
    matrix[2, 2] = (far + near) / (near - far)
    matrix[2, 3] = (2.0 * far * near) / (near - far)
    matrix[3, 2] = -1.0
    return matrix


def orthographic(left: float, right: float, bottom: float, top: float,
                 near: float, far: float) -> np.ndarray:
    matrix = np.eye(4, dtype=np.float32)
    matrix[0, 0] = 2.0 / (right - left)
    matrix[1, 1] = 2.0 / (top - bottom)
    matrix[2, 2] = -2.0 / (far - near)
    matrix[0, 3] = -(right + left) / (right - left)
    matrix[1, 3] = -(top + bottom) / (top - bottom)
    matrix[2, 3] = -(far + near) / (far - near)
    return matrix


def look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
    forward = normalized(target - eye)
    right = normalized(np.cross(forward, up))
    real_up = np.cross(right, forward)
    matrix = np.eye(4, dtype=np.float32)
    matrix[0, :3], matrix[1, :3], matrix[2, :3] = right, real_up, -forward
    matrix[0, 3] = -float(np.dot(right, eye))
    matrix[1, 3] = -float(np.dot(real_up, eye))
    matrix[2, 3] = float(np.dot(forward, eye))
    return matrix


def create_cube_vertices() -> np.ndarray:
    # Outward-facing CCW quads, with face normals. Two triangles per face.
    faces = [
        ((0, 0, 1), [(-.5, -.5, .5), (.5, -.5, .5), (.5, .5, .5), (-.5, .5, .5)]),
        ((0, 0, -1), [(.5, -.5, -.5), (-.5, -.5, -.5), (-.5, .5, -.5), (.5, .5, -.5)]),
        ((1, 0, 0), [(.5, -.5, .5), (.5, -.5, -.5), (.5, .5, -.5), (.5, .5, .5)]),
        ((-1, 0, 0), [(-.5, -.5, -.5), (-.5, -.5, .5), (-.5, .5, .5), (-.5, .5, -.5)]),
        ((0, 1, 0), [(-.5, .5, .5), (.5, .5, .5), (.5, .5, -.5), (-.5, .5, -.5)]),
        ((0, -1, 0), [(-.5, -.5, -.5), (.5, -.5, -.5), (.5, -.5, .5), (-.5, -.5, .5)]),
    ]
    data = []
    for normal, corners in faces:
        for index in (0, 1, 2, 0, 2, 3):
            data.extend((*corners[index], *normal))
    return np.asarray(data, dtype=np.float32)


def compile_program(vertex_shader: str, fragment_shader: str) -> int:
    shaders = []
    program = glCreateProgram()
    try:
        for kind, source in ((GL_VERTEX_SHADER, vertex_shader), (GL_FRAGMENT_SHADER, fragment_shader)):
            shader = glCreateShader(kind)
            shaders.append(shader)
            glShaderSource(shader, source)
            glCompileShader(shader)
            if not glGetShaderiv(shader, GL_COMPILE_STATUS):
                log = glGetShaderInfoLog(shader)
                raise RuntimeError(f"Shader compile error: {log.decode(errors='replace') if isinstance(log, bytes) else log}")
            glAttachShader(program, shader)
        glLinkProgram(program)
        if not glGetProgramiv(program, GL_LINK_STATUS):
            log = glGetProgramInfoLog(program)
            raise RuntimeError(f"Shader link error: {log.decode(errors='replace') if isinstance(log, bytes) else log}")
        return program
    except Exception:
        glDeleteProgram(program)
        raise
    finally:
        for shader in shaders:
            glDeleteShader(shader)


def uniform_mat(location: int, matrix: np.ndarray) -> None:
    # NumPy arrays are row-major; transpose on upload to GLSL column-major.
    glUniformMatrix4fv(location, 1, GL_TRUE, matrix)


def make_arena() -> list[Box]:
    boxes: list[Box] = []
    add = boxes.append
    concrete = (0.50, 0.55, 0.57)
    wall = (0.48, 0.52, 0.57)
    crate = (0.55, 0.38, 0.23)
    metal = (0.27, 0.35, 0.41)
    orange = (0.85, 0.45, 0.15)

    # Floor and enclosing walls: one open, accessible arena, not a maze.
    add(Box(0, -0.35, 0, 62, 0.70, 62, (0.38, 0.41, 0.41), False, False))
    add(Box(0, 2.8, -30.9, 62, 5.6, 1.2, wall))
    add(Box(0, 2.8, 30.9, 62, 5.6, 1.2, wall))
    add(Box(-30.9, 2.8, 0, 1.2, 5.6, 62, wall))
    add(Box(30.9, 2.8, 0, 1.2, 5.6, 62, wall))

    # Practice cover / blocks on the left flank.
    add(Box(-17, .75, -3, 3.0, 1.5, 3.0, crate))
    add(Box(-20, .75, -7, 2.5, 1.5, 2.5, crate))
    add(Box(-17, 2.2, -3, 2.1, 1.4, 2.1, crate))
    add(Box(-10, .65, -11, 7, 1.3, .9, concrete))
    add(Box(-13, .8, -17, 2.6, 1.6, 2.6, metal))
    add(Box(-21, 1.05, -21, 4, 2.1, 3.5, concrete))
    add(Box(-21, 2.70, -21, 2.2, 1.2, 2.2, metal))

    # Center test targets and cover; open gaps permit free movement.
    add(Box(0, .55, -10, 5.5, 1.1, .9, concrete))
    add(Box(0, 1.95, -15, 1.0, 3.9, 1.0, orange))
    add(Box(-5, .90, -22, 2.0, 1.8, 2.0, metal))
    add(Box(5, .90, -22, 2.0, 1.8, 2.0, metal))
    add(Box(0, .45, -26, 9.0, .9, .75, concrete))
    for x, h in [(-9, 1.6), (0, 2.6), (9, 3.8)]:
        add(Box(x, h / 2, -27.6, 1.3, h, 1.3, orange))

    # Right side: multiple elevations for visible shadow and occlusion tests.
    add(Box(14, .60, -3, 5.5, 1.2, 1.0, concrete))
    add(Box(20, .90, -7, 2.7, 1.8, 2.7, crate))
    add(Box(23, .90, -7, 2.7, 1.8, 2.7, crate))
    add(Box(21.5, 2.65, -7, 2.7, 1.7, 2.7, crate))
    add(Box(13, 1.50, -17, 3, 3, 3, metal))
    add(Box(19, .50, -20, 6.5, 1.0, 1, concrete))
    add(Box(24, 2.3, -24, 2, 4.6, 2, metal))

    # Spawn end cover, separated to retain a clear starting point.
    add(Box(-14, .55, 12, 5.0, 1.1, 1.0, concrete))
    add(Box(15, .55, 13, 5.0, 1.1, 1.0, concrete))
    add(Box(-22, .85, 20, 3, 1.7, 3, crate))
    add(Box(21, .85, 22, 3, 1.7, 3, crate))
    add(Box(-9, .5, 24, 4, 1, 1.0, concrete))
    add(Box(9, .5, 24, 4, 1, 1.0, concrete))

    # Flat paint stripes / targets are deliberately NON-solid.
    for x in (-20, -10, 0, 10, 20):
        add(Box(x, .008, 7, .10, .016, 8, (0.72, .69, .43), False, False))
    for x in (-6, 0, 6):
        add(Box(x, .012, -18, 1.5, .024, .12, (0.82, .45, .24), False, False))
    return boxes


class FPSPlayer:
    def __init__(self) -> None:
        self.x, self.z = 0.0, 18.0
        self.vx, self.vz = 0.0, 0.0
        self.yaw, self.pitch = -90.0, -7.0
        self.speed = 6.0

    @property
    def eye(self) -> np.ndarray:
        return np.array([self.x, EYE_HEIGHT, self.z], dtype=np.float32)

    def forward(self) -> np.ndarray:
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        return normalized(np.array([
            math.cos(yaw) * math.cos(pitch), math.sin(pitch),
            math.sin(yaw) * math.cos(pitch),
        ], dtype=np.float32))

    @staticmethod
    def collides(x: float, z: float, scene: list[Box]) -> bool:
        for box in scene:
            if not box.solid:
                continue
            # The player occupies y=[0, PLAYER_HEIGHT].
            if box.y - box.sy * .5 >= PLAYER_HEIGHT or box.y + box.sy * .5 <= 0:
                continue
            if (abs(x - box.x) < PLAYER_RADIUS + box.sx * .5 and
                    abs(z - box.z) < PLAYER_RADIUS + box.sz * .5):
                return True
        return False

    def move(self, dt: float, scene: list[Box], w: bool, s: bool, a: bool, d: bool) -> None:
        heading = math.radians(self.yaw)
        forward_xz = np.array([math.cos(heading), math.sin(heading)], dtype=np.float32)
        right_xz = np.array([-forward_xz[1], forward_xz[0]], dtype=np.float32)
        direction = np.zeros(2, dtype=np.float32)
        direction += forward_xz * (int(w) - int(s))
        direction += right_xz * (int(d) - int(a))
        direction = normalized(direction)

        target_v = direction * self.speed
        blend = 1.0 - math.exp(-15.0 * dt)
        self.vx += (float(target_v[0]) - self.vx) * blend
        self.vz += (float(target_v[1]) - self.vz) * blend
        # Substeps avoid tunneling at higher speeds / on slower frames.
        dx, dz = self.vx * dt, self.vz * dt
        iterations = max(1, math.ceil(max(abs(dx), abs(dz)) / 0.12))
        dx /= iterations
        dz /= iterations
        for _ in range(iterations):
            if not self.collides(self.x + dx, self.z, scene):
                self.x += dx
            else:
                self.vx = 0.0
            if not self.collides(self.x, self.z + dz, scene):
                self.z += dz
            else:
                self.vz = 0.0


class ArenaApp:
    def __init__(self) -> None:
        self.window = None
        self.imgui_renderer = None
        self.scene = make_arena()
        self.player = FPSPlayer()
        self.light_azimuth = 36.0
        self.light_elevation = 51.0
        self.light_color = [1.0, 0.94, 0.82]
        self.light_intensity = 1.50
        self.ambient = 0.23
        self.use_shadows = True
        self.mouse_locked = True
        self.prev_mouse_pos: tuple[float, float] | None = None
        self.q_was_down = False
        self.fps = 60.0
        self.scene_program = 0
        self.depth_program = 0
        self.depth_texture = 0
        self.depth_fbo = 0
        self.vao = 0
        self.vbo = 0
        self.scene_locations: dict[str, int] = {}
        self.depth_locations: dict[str, int] = {}
        self.mesh_matrices = [box.model_matrix() for box in self.scene]

    def create_window(self) -> None:
        if not glfw.init():
            raise RuntimeError("GLFW could not initialize. Check your graphics/display drivers.")
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)
        glfw.window_hint(glfw.SAMPLES, 4)
        self.window = glfw.create_window(WIDTH, HEIGHT, "OpenGL FPS Test Arena | Q: mouse", None, None)
        if not self.window:
            raise RuntimeError("Failed to create an OpenGL 3.3 window.")
        glfw.make_context_current(self.window)
        glfw.swap_interval(1)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        glCullFace(GL_BACK)

    def create_gpu_resources(self) -> None:
        self.scene_program = compile_program(SCENE_VS, SCENE_FS)
        self.depth_program = compile_program(DEPTH_VS, DEPTH_FS)
        for name in ("uModel", "uView", "uProjection", "uLightSpace", "uBaseColor",
                     "uLightColor", "uLightDir", "uCameraPos", "uIntensity", "uAmbient",
                     "uUseShadows", "uShadowMap"):
            self.scene_locations[name] = glGetUniformLocation(self.scene_program, name)
        for name in ("uModel", "uLightSpace"):
            self.depth_locations[name] = glGetUniformLocation(self.depth_program, name)

        vertices = create_cube_vertices()
        self.vao = glGenVertexArrays(1)
        self.vbo = glGenBuffers(1)
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_STATIC_DRAW)
        stride = 6 * vertices.itemsize
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(3 * vertices.itemsize))
        glBindVertexArray(0)

        self.depth_fbo = glGenFramebuffers(1)
        self.depth_texture = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self.depth_texture)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, SHADOW_SIZE, SHADOW_SIZE,
                     0, GL_DEPTH_COMPONENT, GL_FLOAT, None)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER)
        glTexParameterfv(GL_TEXTURE_2D, GL_TEXTURE_BORDER_COLOR,
                         np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32))
        glBindFramebuffer(GL_FRAMEBUFFER, self.depth_fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                               GL_TEXTURE_2D, self.depth_texture, 0)
        glDrawBuffer(GL_NONE)
        glReadBuffer(GL_NONE)
        status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        if status != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError(f"Shadow framebuffer is incomplete: {status}")
        glBindTexture(GL_TEXTURE_2D, 0)

    def light_direction(self) -> np.ndarray:
        a = math.radians(self.light_azimuth)
        e = math.radians(self.light_elevation)
        return normalized(np.array([
            math.cos(e) * math.cos(a), -math.sin(e), math.cos(e) * math.sin(a)
        ], dtype=np.float32))

    def light_space_matrix(self, direction: np.ndarray) -> np.ndarray:
        # Large fixed orthographic region: stable coverage of the full arena.
        eye = -direction * 82.0
        up = WORLD_UP if abs(float(np.dot(direction, WORLD_UP))) < .97 else np.array([0, 0, 1], dtype=np.float32)
        light_view = look_at(eye, np.array([0, 0, 0], dtype=np.float32), up)
        light_proj = orthographic(-72, 72, -72, 72, 0.1, 205.0)
        return light_proj @ light_view

    def set_mouse_capture(self, locked: bool) -> None:
        self.mouse_locked = locked
        glfw.set_input_mode(self.window, glfw.CURSOR,
                            glfw.CURSOR_DISABLED if locked else glfw.CURSOR_NORMAL)
        self.prev_mouse_pos = None  # prevent jump on state transition
        self.player.vx, self.player.vz = 0.0, 0.0

    def key_down(self, key: int) -> bool:
        return glfw.get_key(self.window, key) == glfw.PRESS

    def update_controls(self, dt: float) -> None:
        q_down = self.key_down(glfw.KEY_Q)
        if q_down and not self.q_was_down:
            self.set_mouse_capture(not self.mouse_locked)
        self.q_was_down = q_down

        if self.key_down(glfw.KEY_ESCAPE):
            glfw.set_window_should_close(self.window, True)

        if not self.mouse_locked or not glfw.get_window_attrib(self.window, glfw.FOCUSED):
            self.prev_mouse_pos = None
            return

        mouse_x, mouse_y = glfw.get_cursor_pos(self.window)
        if self.prev_mouse_pos is not None:
            delta_x = mouse_x - self.prev_mouse_pos[0]
            delta_y = mouse_y - self.prev_mouse_pos[1]
            self.player.yaw += delta_x * MOUSE_SENSITIVITY
            self.player.pitch = max(-88.5, min(88.5,
                self.player.pitch - delta_y * MOUSE_SENSITIVITY))
        self.prev_mouse_pos = (mouse_x, mouse_y)
        self.player.move(dt, self.scene, self.key_down(glfw.KEY_W),
                         self.key_down(glfw.KEY_S), self.key_down(glfw.KEY_A),
                         self.key_down(glfw.KEY_D))

    def render_depth(self, light_space: np.ndarray) -> None:
        glViewport(0, 0, SHADOW_SIZE, SHADOW_SIZE)
        glBindFramebuffer(GL_FRAMEBUFFER, self.depth_fbo)
        glClear(GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(1.5, 2.5)
        glUseProgram(self.depth_program)
        uniform_mat(self.depth_locations["uLightSpace"], light_space)
        glBindVertexArray(self.vao)
        for box, model in zip(self.scene, self.mesh_matrices):
            if not box.casts_shadow:
                continue
            uniform_mat(self.depth_locations["uModel"], model)
            glDrawArrays(GL_TRIANGLES, 0, 36)
        glBindVertexArray(0)
        glDisable(GL_POLYGON_OFFSET_FILL)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def render_scene(self, light_space: np.ndarray, direction: np.ndarray) -> None:
        framebuffer_width, framebuffer_height = glfw.get_framebuffer_size(self.window)
        if framebuffer_width <= 0 or framebuffer_height <= 0:
            return
        glViewport(0, 0, framebuffer_width, framebuffer_height)
        glClearColor(0.60, 0.72, 0.82, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST)

        projection = perspective(72.0, framebuffer_width / framebuffer_height, 0.07, 190.0)
        eye = self.player.eye
        view = look_at(eye, eye + self.player.forward(), WORLD_UP)
        glUseProgram(self.scene_program)
        loc = self.scene_locations
        uniform_mat(loc["uView"], view)
        uniform_mat(loc["uProjection"], projection)
        uniform_mat(loc["uLightSpace"], light_space)
        glUniform3f(loc["uCameraPos"], *map(float, eye))
        glUniform3f(loc["uLightDir"], *map(float, direction))
        glUniform3f(loc["uLightColor"], *self.light_color)
        glUniform1f(loc["uIntensity"], self.light_intensity)
        glUniform1f(loc["uAmbient"], self.ambient)
        glUniform1i(loc["uUseShadows"], int(self.use_shadows))
        glActiveTexture(GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_2D, self.depth_texture)
        glUniform1i(loc["uShadowMap"], 1)
        glBindVertexArray(self.vao)
        for box, model in zip(self.scene, self.mesh_matrices):
            uniform_mat(loc["uModel"], model)
            glUniform3f(loc["uBaseColor"], *box.color)
            glDrawArrays(GL_TRIANGLES, 0, 36)
        glBindVertexArray(0)
        glActiveTexture(GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_2D, 0)
        glActiveTexture(GL_TEXTURE0)

    def draw_imgui(self) -> None:
        imgui.begin("FPS Test | Live Settings")
        imgui.text(f"FPS: {self.fps:.0f}    OpenGL 3.3")
        imgui.text(f"Player X: {self.player.x:.1f}   Z: {self.player.z:.1f}")
        imgui.text("WASD move  |  Mouse look")
        imgui.text("Q release/capture cursor  |  ESC quit")
        imgui.text("Mouse: " + ("Captured" if self.mouse_locked else "Free (edit settings)"))
        imgui.separator()
        _, self.player.speed = imgui.slider_float("Move speed", self.player.speed, 1.0, 18.0)
        imgui.separator()
        imgui.text("Directional sunlight")
        _, self.light_azimuth = imgui.slider_float("Azimuth", self.light_azimuth, -180.0, 180.0)
        _, self.light_elevation = imgui.slider_float("Elevation", self.light_elevation, 8.0, 88.0)
        _, self.light_intensity = imgui.slider_float("Intensity", self.light_intensity, 0.0, 3.5)
        _, self.ambient = imgui.slider_float("Ambient", self.ambient, 0.0, 0.70)
        if USING_IMGUI_BUNDLE:
            _, new_color = imgui.color_edit3("Light color", list(self.light_color))
        else:
            _, new_color = imgui.color_edit3("Light color", *self.light_color)
        self.light_color = [float(v) for v in new_color]
        _, self.use_shadows = imgui.checkbox("Real-time shadows (3x3 PCF)", self.use_shadows)
        imgui.text(f"Shadow map: {SHADOW_SIZE} x {SHADOW_SIZE}")
        imgui.end()

    def cleanup(self) -> None:
        # Release GL resources before destroying the GLFW context.
        if self.window:
            glfw.make_context_current(self.window)
            if self.imgui_renderer is not None:
                self.imgui_renderer.shutdown()
                self.imgui_renderer = None
            if self.depth_fbo:
                glDeleteFramebuffers(1, [self.depth_fbo])
            if self.depth_texture:
                glDeleteTextures(1, [self.depth_texture])
            if self.vbo:
                glDeleteBuffers(1, [self.vbo])
            if self.vao:
                glDeleteVertexArrays(1, [self.vao])
            if self.scene_program:
                glDeleteProgram(self.scene_program)
            if self.depth_program:
                glDeleteProgram(self.depth_program)
            glfw.destroy_window(self.window)
        glfw.terminate()

    def run(self) -> None:
        try:
            self.create_window()
            self.create_gpu_resources()
            imgui.create_context()
            self.imgui_renderer = GlfwRenderer(self.window)
            self.set_mouse_capture(True)
            previous_time = glfw.get_time()
            while not glfw.window_should_close(self.window):
                glfw.poll_events()
                current_time = glfw.get_time()
                dt = min(max(current_time - previous_time, 0.0), 0.075)
                previous_time = current_time
                if dt > 0.0001:
                    self.fps += (1.0 / dt - self.fps) * (1.0 - math.exp(-4.0 * dt))
                self.update_controls(dt)

                # Shadow pass and camera pass share the SAME live lighting direction.
                direction = self.light_direction()
                light_space = self.light_space_matrix(direction)
                if self.use_shadows:
                    self.render_depth(light_space)
                self.render_scene(light_space, direction)

                self.imgui_renderer.process_inputs()
                imgui.new_frame()
                self.draw_imgui()
                imgui.render()
                # The scene used depth testing; ImGui's backend manages the UI state.
                self.imgui_renderer.render(imgui.get_draw_data())
                glfw.swap_buffers(self.window)
        finally:
            self.cleanup()


if __name__ == "__main__":
    try:
        ArenaApp().run()
    except Exception as error:
        print(f"FPS arena error: {error}", file=sys.stderr)
        raise
