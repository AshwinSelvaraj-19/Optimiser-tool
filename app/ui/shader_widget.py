"""
Heaven Society — Real-Time Shader Background

Lightweight GPU-rendered visual effect for the application UI.
Uses QOpenGLWidget with GLSL fragment shaders.

The shader is purely cosmetic — it does NOT:
- modify games
- inject into processes
- modify game memory
- alter game rendering
- bypass anti-cheat
- manipulate gameplay

Quality levels: LOW, MEDIUM, HIGH
Can be disabled entirely via settings.
"""

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtOpenGL import (
    QOpenGLShaderProgram,
    QOpenGLShader,
    QOpenGLBuffer,
)

GL_COLOR_BUFFER_BIT = 0x00004000
GL_FLOAT = 0x1406
GL_TRIANGLES = 0x0004

from app.utils.logger import get_logger

logger = get_logger("ui.shader_widget")


# ── GLSL Shaders ──────────────────────────────────────────────

VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 position;
layout(location = 1) in vec2 texCoord;
out vec2 vTexCoord;
void main() {
    vTexCoord = texCoord;
    gl_Position = vec4(position, 0.0, 1.0);
}
"""

FRAGMENT_SHADER = """
#version 330 core
uniform float uTime;
uniform vec2 uResolution;
uniform float uIntensity;  // 0.0 = off, 0.5 = low, 0.75 = medium, 1.0 = high
in vec2 vTexCoord;
out vec4 fragColor;

// Simplex-style hash
vec2 hash22(vec2 p) {
    p = vec2(dot(p, vec2(127.1, 311.7)),
             dot(p, vec2(269.5, 183.3)));
    return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
}

// 2D value noise
float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(dot(hash22(i + vec2(0.0, 0.0)), f - vec2(0.0, 0.0)),
                   dot(hash22(i + vec2(1.0, 0.0)), f - vec2(1.0, 0.0)), u.x),
               mix(dot(hash22(i + vec2(0.0, 1.0)), f - vec2(0.0, 1.0)),
                   dot(hash22(i + vec2(1.0, 1.0)), f - vec2(1.0, 1.0)), u.x), u.y);
}

// Fractal Brownian Motion
float fbm(vec2 p) {
    float value = 0.0;
    float amplitude = 0.5;
    float frequency = 1.0;
    for (int i = 0; i < 5; i++) {
        value += amplitude * noise(p * frequency);
        frequency *= 2.0;
        amplitude *= 0.5;
    }
    return value;
}

void main() {
    vec2 uv = vTexCoord;
    float t = uTime * 0.15;

    // Dark futuristic energy field
    vec2 q = vec2(fbm(uv * 2.0 + t * 0.3),
                  fbm(uv * 2.0 + vec2(1.0) + t * 0.2));

    vec2 r = vec2(fbm(uv * 3.0 + q * 2.0 + t * 0.15),
                  fbm(uv * 3.0 + q * 2.0 + vec2(5.2, 1.3) + t * 0.12));

    float f = fbm(uv * 2.0 + r * 1.5 + t * 0.1);

    // Color palette — dark with subtle red/silver accent
    vec3 baseColor = vec3(0.04, 0.04, 0.06);   // Very dark blue-black
    vec3 accentColor = vec3(0.35, 0.08, 0.08);  // Dark red accent
    vec3 silverColor = vec3(0.15, 0.15, 0.18);  // Dark silver

    vec3 color = mix(baseColor, silverColor, smoothstep(-0.3, 0.8, f));
    color = mix(color, accentColor, smoothstep(0.3, 0.9, f) * 0.35);

    // Subtle flowing energy
    float energy = smoothstep(0.1, 0.8, f * f);
    color += vec3(0.22, 0.04, 0.04) * energy * 0.3;

    // Subtle vignette
    float vignette = 1.0 - 0.3 * length((uv - 0.5) * 1.8);
    color *= vignette;

    // Apply intensity
    color *= uIntensity;

    fragColor = vec4(color, 1.0);
}
"""


class ShaderWidget(QOpenGLWidget):
    """Lightweight real-time shader background effect.

    Renders a subtle dark futuristic energy field behind the UI.
    Supports LOW / MEDIUM / HIGH quality levels.
    Can be toggled ON/OFF. Performance-aware: stops rendering when hidden.
    """

    QUALITY_LOW = "LOW"
    QUALITY_MEDIUM = "MEDIUM"
    QUALITY_HIGH = "HIGH"

    _QUALITY_FPS = {
        "LOW": 20,
        "MEDIUM": 30,
        "HIGH": 60,
    }

    def __init__(self, parent=None, enabled=True, quality="LOW"):
        fmt = QSurfaceFormat()
        fmt.setDepthBufferSize(0)
        fmt.setStencilBufferSize(0)
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        QSurfaceFormat.setDefaultFormat(fmt)

        super().__init__(parent)

        self._enabled = enabled
        self._quality = quality.upper() if quality.upper() in self._QUALITY_FPS else "LOW"
        self._program = None
        self._vbo = None
        self._vbo_tex = None
        self._start_time = time.time()
        self._visible = True
        self._gl = None

        # Cached uniform locations (set in initializeGL)
        self._loc_time = -1
        self._loc_resolution = -1
        self._loc_intensity = -1

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._interval = int(1000 / self._QUALITY_FPS.get(self._quality, 20))
        if self._enabled:
            self._timer.start(self._interval)

        self.setMinimumSize(100, 100)

    # ── Public API ────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, on: bool):
        """Toggle shader on/off."""
        self._enabled = on
        if on:
            self._start_time = time.time()
            self._timer.start(self._interval)
            self.show()
        else:
            self._timer.stop()
            self.hide()

    @property
    def quality(self) -> str:
        return self._quality

    def set_quality(self, q: str):
        """Change render quality."""
        q = q.upper()
        if q not in self._QUALITY_FPS:
            return
        self._quality = q
        self._interval = int(1000 / self._QUALITY_FPS[q])
        if self._timer.isActive():
            self._timer.start(self._interval)  # Restart with new interval

    # ── Qt GL overrides ───────────────────────────────────────

    def initializeGL(self):
        try:
            # Obtain an initialized QOpenGLFunctions object from the
            # current context.  The old code called a non-existent
            # QOpenGLFunctions.initializeGL() which always failed.
            ctx = self.context()
            if ctx is None or not ctx.isValid():
                logger.warning("No valid OpenGL context — shader disabled")
                self._program = None
                return
            self._gl = ctx.functions()

            self._program = QOpenGLShaderProgram(self)

            vs = QOpenGLShader(QOpenGLShader.Vertex)
            vs.compileSourceCode(VERTEX_SHADER)
            fs = QOpenGLShader(QOpenGLShader.Fragment)
            fs.compileSourceCode(FRAGMENT_SHADER)

            self._program.addShader(vs)
            self._program.addShader(fs)
            self._program.link()

            if not self._program.isLinked():
                logger.warning("Shader program failed to link")
                self._program = None
                return

            # Cache uniform locations — int-based overloads are guaranteed
            # in every PySide6 version; name-based overloads may not accept
            # scalar floats on all builds.
            self._loc_time = self._program.uniformLocation(b"uTime")
            self._loc_resolution = self._program.uniformLocation(b"uResolution")
            self._loc_intensity = self._program.uniformLocation(b"uIntensity")

            # ── Vertex data via QOpenGLBuffer (PySide6-safe) ──
            # Position attribute (location 0): vec2
            # fmt: off
            positions = [
                -1.0, -1.0,
                 1.0, -1.0,
                 1.0,  1.0,
                -1.0, -1.0,
                 1.0,  1.0,
                -1.0,  1.0,
            ]
            # TexCoord attribute (location 1): vec2
            texcoords = [
                0.0, 0.0,
                1.0, 0.0,
                1.0, 1.0,
                0.0, 0.0,
                1.0, 1.0,
                0.0, 1.0,
            ]
            # fmt: on

            import ctypes

            # Position VBO
            pos_bytes = (ctypes.c_float * len(positions))(*positions)
            self._vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            self._vbo.create()
            self._vbo.bind()
            self._vbo.allocate(pos_bytes, len(positions) * 4)
            self._vbo.release()
            self._vbo_count = len(positions) // 2  # 6 vertices

            # TexCoord VBO
            tex_bytes = (ctypes.c_float * len(texcoords))(*texcoords)
            self._vbo_tex = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            self._vbo_tex.create()
            self._vbo_tex.bind()
            self._vbo_tex.allocate(tex_bytes, len(texcoords) * 4)
            self._vbo_tex.release()

            logger.debug("Shader initialized successfully")

        except Exception as e:
            logger.warning(f"Shader init failed (falling back): {e}")
            self._program = None

    def paintGL(self):
        gl = self._gl
        if not gl or not self._program or not self._enabled:
            if gl:
                gl.glClearColor(0.04, 0.04, 0.06, 1.0)
                gl.glClear(GL_COLOR_BUFFER_BIT)
            return

        gl.glClear(GL_COLOR_BUFFER_BIT)

        self._program.bind()

        # Uniforms — use cached int locations
        elapsed = time.time() - self._start_time
        self._program.setUniformValue(self._loc_time, float(elapsed))
        self._program.setUniformValue(
            self._loc_resolution,
            float(self.width()),
            float(self.height()),
        )
        intensity = {"LOW": 0.5, "MEDIUM": 0.75, "HIGH": 1.0}.get(self._quality, 0.5)
        self._program.setUniformValue(self._loc_intensity, float(intensity))

        # Bind position VBO (attribute 0)
        self._vbo.bind()
        self._program.enableAttributeArray(0)
        self._program.setAttributeBuffer(
            0, GL_FLOAT, 0, 2, 2 * 4  # attribute, type, offset, tupleSize, stride
        )

        # Bind texcoord VBO (attribute 1)
        self._vbo_tex.bind()
        self._program.enableAttributeArray(1)
        self._program.setAttributeBuffer(
            1, GL_FLOAT, 0, 2, 2 * 4
        )

        gl.glDrawArrays(GL_TRIANGLES, 0, self._vbo_count)

        self._program.disableAttributeArray(0)
        self._program.disableAttributeArray(1)
        self._vbo.release()
        self._vbo_tex.release()
        self._program.release()

    def resizeGL(self, w, h):
        pass  # Shader handles resolution via uniform

    # ── Internal ──────────────────────────────────────────────

    def _tick(self):
        if self._visible and self._enabled:
            self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._visible = True
        if self._enabled and not self._timer.isActive():
            self._timer.start(self._interval)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._visible = False
        # Stop updating when hidden — save GPU
        if self._timer.isActive():
            self._timer.stop()

    def _cleanup_gl(self):
        """Release OpenGL resources.  Safe to call multiple times."""
        try:
            if self._vbo is not None:
                self._vbo.destroy()
                self._vbo = None
        except Exception:
            pass
        try:
            if self._vbo_tex is not None:
                self._vbo_tex.destroy()
                self._vbo_tex = None
        except Exception:
            pass
        try:
            if self._program is not None:
                self._program.removeAllShaders()
                self._program = None
        except Exception:
            pass

    def __del__(self):
        try:
            self._timer.stop()
        except Exception:
            pass
