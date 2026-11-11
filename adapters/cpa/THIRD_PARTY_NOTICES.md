# Third-Party Notices

This project includes code derived from the following open-source projects.

## CPA CodexComp plugin

- **Project**: https://github.com/uf-hy/cpa-plugin-codexcomp
- **Baseline**: v0.1.7, commit 25c139b49984e91fcc26896a7caf64b806b4deee
- **License**: MIT
- **Copyright**: Copyright (c) 2026 uf-hy
- **Usage**: This is an independently maintained fork. The C ABI bridge, routing,
  configuration, fold logic, and inherited unit tests originate in this project.
  The upstream copyright and permission notice remain in LICENSE.

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

- CLIProxyAPI v8.0.13 SDK (sdk/pluginapi, sdk/pluginabi): MIT, copyrights retained in THIRD_PARTY_LICENSES.txt.
- gopkg.in/yaml.v3 v3.0.1: upstream MIT/Apache-2.0 notices retained in THIRD_PARTY_LICENSES.txt.
- Go runtime and standard library: BSD-3-Clause, full notice retained in THIRD_PARTY_LICENSES.txt.
- Portable Go/LLVM-MinGW toolchains are development-only and are not included in plugin release ZIPs.
