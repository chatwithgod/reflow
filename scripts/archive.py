"""Build a ZIP with explicit Unix modes, including hidden marketplace files."""
import argparse
from pathlib import Path
import stat
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument("root", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--executable", required=True)
args = parser.parse_args()
root = args.root.resolve(strict=True)
if args.output.exists():
    raise SystemExit("Archive exists; refusing to overwrite")
executable = args.executable.replace("\\", "/")
if not (root / executable).is_file():
    raise SystemExit("Executable missing from package")
with zipfile.ZipFile(args.output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=7) as archive:
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise SystemExit("Package contains a symlink or an escaped path")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        entry = zipfile.ZipInfo(relative)
        entry.create_system = 3
        entry.external_attr = (stat.S_IFREG | (0o755 if relative == executable else 0o644)) << 16
        entry.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(entry, path.read_bytes(), compresslevel=7)
