"""Enumerate and snapshot the CPA adapter together with its shared core."""

from pathlib import Path
import shutil


def source_files(root):
    root = Path(root).resolve()
    files = {path.name: path for path in sorted(root.glob("*.go"))}
    files.update({name: root / name for name in ("go.mod", "go.sum")})
    module = (root / "go.mod").read_text(encoding="utf-8")
    if "replace github.com/chatwithgod/reflow => ../.." not in module:
        return files  # Historical standalone-module fixtures.
    repository = root.parents[1]
    if (root != repository / "adapters" / "cpa" or
            "module github.com/chatwithgod/reflow\n" not in (repository / "go.mod").read_text(encoding="utf-8")):
        raise ValueError("shared Reflow module must be the repository root")
    files = {"adapters/cpa/" + name: path for name, path in files.items()}
    for name in ("go.mod", "go.sum"):
        files[name] = repository / name
    core = sorted((repository / "core").glob("*.go"))
    if not core:
        raise ValueError("shared core source is missing")
    files.update({"core/" + path.name: path for path in core})
    return files


def snapshot_source(root, destination):
    destination = Path(destination).resolve()
    files = source_files(root)
    for name, path in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output, path.open("rb") as source:
            shutil.copyfileobj(source, output)
    return destination / "adapters/cpa" if "adapters/cpa/go.mod" in files else destination
