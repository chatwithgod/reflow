"""Fetch checksum-verified portable build tools into this checkout only."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
PACKAGES = (
    (
        "https://go.dev/dl/go1.26.8.windows-amd64.zip",
        "b92c3b2adae85a11ba71fe7216daf0d84e82af4c8ab6c5625807f28622043a59",
        "go/bin/go.exe",
    ),
    (
        "https://github.com/mstorsjo/llvm-mingw/releases/download/20260922/"
        "llvm-mingw-20260922-ucrt-x86_64.zip",
        "e3ad77d117a4bea19a7a3b333341824d79a5a371004a10e25b8504e7b3047666",
        "llvm-mingw-20260922-ucrt-x86_64/bin/x86_64-w64-mingw32-clang.exe",
    ),
)


def install(package):
    url, expected, executable = package
    name = url.rsplit("/", 1)[1]
    archive = TOOLS / name
    if not archive.exists():
        print(f"Downloading {name}", flush=True)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(url, headers={"User-Agent": "CodexReflow-build"})
        part = archive.with_suffix(".zip.part")
        with opener.open(request, timeout=60) as response, part.open("wb") as out:
            while block := response.read(1024 * 1024):
                out.write(block)
        part.replace(archive)
    with archive.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != expected:
        raise RuntimeError(f"SHA256 mismatch for {name}; will not extract or execute")
    print(f"Verified SHA256: {name}", flush=True)
    if not (TOOLS / executable).exists():
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                target = (TOOLS / member.filename).resolve()
                if not target.is_relative_to(TOOLS.resolve()):
                    raise RuntimeError("Archive path escapes the project tool directory")
            z.extractall(TOOLS)
    print(f"Ready: {TOOLS / executable}", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    TOOLS.mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(install, PACKAGES))
