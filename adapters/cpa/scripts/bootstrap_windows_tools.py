"""Fetch checksum-verified portable build tools into this checkout only."""

import hashlib
from pathlib import Path
import sys
import sysconfig
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
TOOLCHAINS = {
    "amd64": ("x86_64", "b92c3b2adae85a11ba71fe7216daf0d84e82af4c8ab6c5625807f28622043a59",
              "e3ad77d117a4bea19a7a3b333341824d79a5a371004a10e25b8504e7b3047666"),
    "arm64": ("aarch64", "4bc560ed3ccb64eec0be6180b8c29185c07f5215276820adb4303d7bf3365435",
              "a317514a7a63badd692032c0c2b8e165f630bbaebbe7a3254348051f43a64949"),
}


def packages_for(arch):
    triple, go_sha, llvm_sha = TOOLCHAINS[arch]
    llvm = f"llvm-mingw-20260922-ucrt-{triple}"
    return (
        (f"https://go.dev/dl/go1.26.8.windows-{arch}.zip", go_sha, "go/bin/go.exe"),
        (f"https://github.com/mstorsjo/llvm-mingw/releases/download/20260922/{llvm}.zip",
         llvm_sha, f"{llvm}/bin/{triple}-w64-mingw32-clang.exe"),
    )


def install(package, tools):
    url, expected, executable = package
    name = url.rsplit("/", 1)[1]
    archive = tools / name
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
    if not (tools / executable).exists():
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                target = (tools / member.filename).resolve()
                if not target.is_relative_to(tools.resolve()):
                    raise RuntimeError("Archive path escapes the project tool directory")
            z.extractall(tools)
    print(f"Ready: {tools / executable}", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    arch = {"win-amd64": "amd64", "win-arm64": "arm64"}.get(sysconfig.get_platform())
    if arch is None:
        raise SystemExit("Use 64-bit Windows Python on the native build host.")
    tools = TOOLS if arch == "amd64" else TOOLS / "windows-arm64"
    tools.mkdir(parents=True, exist_ok=True)
    for package in packages_for(arch):
        install(package, tools)
