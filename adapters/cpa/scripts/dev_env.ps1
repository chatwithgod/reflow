$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$GoBin = Join-Path $ProjectRoot '.tools\go\bin'
$ClangBin = Join-Path $ProjectRoot '.tools\llvm-mingw-20260922-ucrt-x86_64\bin'
if ((Test-Path -LiteralPath (Join-Path $GoBin 'go.exe')) -and
    (Test-Path -LiteralPath (Join-Path $ClangBin 'x86_64-w64-mingw32-clang.exe'))) {
    $env:PATH = "$GoBin;$ClangBin;$env:PATH"
    $env:CC = Join-Path $ClangBin 'x86_64-w64-mingw32-clang.exe'
} elseif (-not (Get-Command go -ErrorAction SilentlyContinue)) {
    throw 'Run python scripts/bootstrap_windows_tools.py, or supply Go and a MinGW C compiler.'
}
$env:CGO_ENABLED = '1'
$env:GOTOOLCHAIN = 'local'
$env:GOWORK = 'off'
$env:GOTELEMETRY = 'off'
$env:GOPATH = Join-Path $ProjectRoot '.tools\gopath'
$env:GOCACHE = Join-Path $ProjectRoot '.tools\gocache'
