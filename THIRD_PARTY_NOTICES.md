# Third-Party Notices

This project includes code derived from the following open-source projects.

## CPA CodexReflow extraction

- **Project**: https://github.com/chatwithgod/cpa-plugin-codexreflow
- **Baseline**: commit 9b261194c416f8affab23c9bf02448cc022f2cf2
- **License**: MIT
- **Usage**: Extracted folding helpers, stream decoder and decoder regression tests;
  adapted the event folding state machine into a transport-independent package.
  The standalone program does not depend on the CPA SDK or load a CPA plugin.

## CPA CodexComp plugin

- **Project**: https://github.com/uf-hy/cpa-plugin-codexcomp
- **Baseline**: v0.1.7, commit 25c139b49984e91fcc26896a7caf64b806b4deee
- **License**: MIT
- **Copyright**: Copyright (c) 2026 uf-hy
- **Usage**: Ancestor of the extracted fold logic and inherited tests through
  CPA CodexReflow. The upstream copyright and permission notice remain in LICENSE.

## CodexCont

- **Project**: https://github.com/neteroster/CodexCont
- **License**: MIT
- **Copyright**: Copyright (c) 2025 neteroster
- **Usage**: Original continuation mechanism that identified the `518n−2` truncation pattern and pioneered the `encrypted_content` replay approach.

## codexcomp

- **Project**: https://github.com/dzshzx/codexcomp
- **License**: MIT
- **Copyright**: Copyright (c) 2025 dzshzx
- **Usage**: The fold algorithm in `fold.go` is a direct Go port of `codexcomp/fold.py`. The truncation detection (`518n−2`), continuation round construction, output buffering, and usage synthesis logic are derived from this project.

## MIT License (CodexCont and codexcomp)

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Build/runtime dependencies

- github.com/coder/websocket v1.8.15: ISC; its notice is retained in THIRD_PARTY_LICENSES.txt.
- github.com/klauspost/compress v1.20.3: upstream notices retained in THIRD_PARTY_LICENSES.txt.
- github.com/pelletier/go-toml/v2 v2.4.3: MIT; used to preserve unrelated Codex TOML while changing only its routing URL.
- Go runtime and standard library: BSD-3-Clause, full notice retained in THIRD_PARTY_LICENSES.txt.
- Historical CPA SDK and YAML notices are retained for provenance; neither is a dependency of this standalone module.
- Portable Go/LLVM-MinGW toolchains are development-only and are not included in release ZIPs.
