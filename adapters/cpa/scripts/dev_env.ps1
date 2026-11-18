param([ValidateSet('amd64','arm64')][string]$GoArch)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $GoArch) {
    $GoArch = switch ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()) {
        'X64' { 'amd64' }
        'Arm64' { 'arm64' }
        default { throw 'Unsupported Windows build architecture.' }
    }
}
$ToolRoot = Join-Path $ProjectRoot '.tools'
$Triple = 'x86_64'
if ($GoArch -eq 'arm64') {
    $ToolRoot = Join-Path $ToolRoot 'windows-arm64'
    $Triple = 'aarch64'
}
$GoBin = Join-Path $ToolRoot 'go/bin'
$ClangBin = Join-Path $ToolRoot "llvm-mingw-20260922-ucrt-$Triple/bin"
$CompilerPath = Join-Path $ClangBin "$Triple-w64-mingw32-clang.exe"
if ((Test-Path -LiteralPath (Join-Path $GoBin 'go.exe')) -and
    (Test-Path -LiteralPath $CompilerPath)) {
    $env:PATH = "$GoBin;$ClangBin;$env:PATH"
    $env:CC = $CompilerPath
} elseif (-not (Get-Command go -ErrorAction SilentlyContinue)) {
    throw 'Run python scripts/bootstrap_windows_tools.py, or supply Go and a MinGW C compiler.'
}
$env:CGO_ENABLED = '1'
$env:GOTOOLCHAIN = 'local'
$env:GOWORK = 'off'
$env:GOTELEMETRY = 'off'
$env:GOPATH = Join-Path $ProjectRoot '.tools\gopath'
$env:GOCACHE = Join-Path $ProjectRoot '.tools\gocache'
