param([string]$GoExe = 'go', [switch]$AllPlatforms)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$version = (Get-Content -LiteralPath (Join-Path $projectRoot 'VERSION') -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+[-.a-zA-Z0-9]*$') { throw 'Invalid version' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$outputDir = Join-Path $projectRoot "dist/$version/$stamp"
if (Test-Path -LiteralPath $outputDir) { throw 'Build directory already exists; refusing to overwrite' }
New-Item -ItemType Directory -Path $outputDir | Out-Null
$env:GOPATH = Join-Path $projectRoot '.tools/gopath'
$env:GOCACHE = Join-Path $projectRoot '.tools/gocache'
$env:GOTOOLCHAIN = 'local'; $env:CGO_ENABLED = '0'
$platforms = @('windows/amd64')
if ($AllPlatforms) { $platforms += @('linux/amd64','linux/arm64','darwin/amd64','darwin/arm64') }
$manifest = @()
foreach ($platform in $platforms) {
    $parts = $platform.Split('/')
    $env:GOOS = $parts[0]; $env:GOARCH = $parts[1]
    $name = "reflow_${version}_$($parts[0])_$($parts[1])"
    $packageDir = Join-Path $outputDir $name
    New-Item -ItemType Directory -Path $packageDir | Out-Null
    $binaryName = if ($parts[0] -eq 'windows') { 'reflow.exe' } else { 'reflow' }
    $binary = Join-Path $packageDir $binaryName
    & $GoExe build -trimpath -o $binary ./cmd/reflow
    if ($LASTEXITCODE -ne 0) { throw "Build failed: $platform" }
    foreach ($file in @('LICENSE','THIRD_PARTY_LICENSES.txt','THIRD_PARTY_NOTICES.md','VERSION','README.md')) {
        if (Test-Path -LiteralPath (Join-Path $projectRoot $file)) { Copy-Item -LiteralPath (Join-Path $projectRoot $file) -Destination $packageDir }
    }
    $archive = Join-Path $outputDir "$name.zip"
    Compress-Archive -Path (Join-Path $packageDir '*') -DestinationPath $archive -CompressionLevel Optimal
    $manifest += [ordered]@{ platform=$platform; archive=[IO.Path]::GetFileName($archive); sha256=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant(); binary_sha256=(Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant(); runtime_tested=$false }
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $outputDir 'manifest.json') -Encoding utf8
$manifest | ForEach-Object { "$($_.sha256)  $($_.archive)" } | Set-Content -LiteralPath (Join-Path $outputDir 'checksums.txt') -Encoding ascii
Write-Output "Build saved: $outputDir"
