# Third-party dependencies & licenses

This repository contains the project code and documentation **only**. It does not
bundle third-party source code, compiled wheels, or native DLLs. The packages
listed below are obtained separately by Python's package installer.

| Dependency | Role | Upstream license | Source / license |
| --- | --- | --- | --- |
| NumPy | Vector/matrix math | BSD-3-Clause (project license; wheels can contain additional licensed binaries) | [NumPy LICENSE](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| PyOpenGL | OpenGL API binding | BSD-style | [PyOpenGL](https://github.com/mcfletch/pyopengl) |
| glfw (pyGLFW) | Python bindings for GLFW | MIT | [pyGLFW](https://github.com/FlorianRhiem/pyGLFW) |
| GLFW (native library) | Window, GL context, input | zlib/libpng | [GLFW license](https://www.glfw.org/license.html) |
| Dear ImGui Bundle (default) | Dear ImGui Python UI backend | MIT (top-level; contains additional independently licensed components) | [ImGui Bundle](https://github.com/pthom/imgui_bundle) |
| pyimgui (optional alternative) | Dear ImGui Python UI backend | BSD-3-Clause | [pyimgui](https://github.com/pyimgui/pyimgui) |
| Dear ImGui | Underlying immediate-mode UI library | MIT | [Dear ImGui license](https://github.com/ocornut/imgui/blob/master/LICENSE.txt) |

Package distributions may contain further dependencies, binary components,
font data, or their own notices. If you redistribute wheel files or compiled
executable bundles, also include the applicable license notices from those
distributions. The dependency licenses **do not change** the MIT license of
the code authored in this repository.

No Counter-Strike, Valve, or other proprietary game assets are included or
affiliated with this project. The arena is procedural cube geometry.
