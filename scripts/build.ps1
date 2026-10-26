param([string]$GoExe = 'go', [string]$PythonExe = 'python', [switch]$AllPlatforms, [switch]$WithCodexPlugin)
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
    & $GoExe build -trimpath -ldflags "-X github.com/chatwithgod/reflow/internal/version.String=$version" -o $binary ./cmd/reflow
    if ($LASTEXITCODE -ne 0) { throw "Build failed: $platform" }
    foreach ($file in @('LICENSE','THIRD_PARTY_LICENSES.txt','THIRD_PARTY_NOTICES.md','VERSION','README.md','PLAN.md')) {
        if (Test-Path -LiteralPath (Join-Path $projectRoot $file)) { Copy-Item -LiteralPath (Join-Path $projectRoot $file) -Destination $packageDir }
    }
    Copy-Item -LiteralPath (Join-Path $projectRoot 'adapters') -Destination $packageDir -Recurse
    Copy-Item -LiteralPath (Join-Path $projectRoot 'docs') -Destination $packageDir -Recurse
    Copy-Item -LiteralPath (Join-Path $projectRoot 'contrib') -Destination $packageDir -Recurse
    $pluginDocs = Join-Path $packageDir 'plugins/codex'
    New-Item -ItemType Directory -Path $pluginDocs | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot 'plugins/codex/README.md') -Destination $pluginDocs
    $archive = Join-Path $outputDir "$name.zip"
    & $PythonExe (Join-Path $PSScriptRoot 'archive.py') $packageDir $archive --executable $binaryName
    if ($LASTEXITCODE -ne 0) { throw 'Standalone packaging failed' }
    $binaryHash = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifest += [ordered]@{ kind='standalone'; platform=$platform; archive=[IO.Path]::GetFileName($archive); sha256=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant(); binary_sha256=$binaryHash; binary_path=$binaryName; runtime_tested=$false }
    if ($WithCodexPlugin) {
        $pluginName = "reflow_plugin_${version}_$($parts[0])_$($parts[1])"
        $marketRoot = Join-Path $outputDir $pluginName
        $pluginRoot = Join-Path $marketRoot 'plugins/reflow'
        $catalogDir = Join-Path $marketRoot '.agents/plugins'
        New-Item -ItemType Directory -Path (Join-Path $pluginRoot 'bin'),$catalogDir | Out-Null
        Copy-Item -LiteralPath $binary -Destination (Join-Path $pluginRoot "bin/$binaryName")
        $pluginManifest = Get-Content -LiteralPath (Join-Path $projectRoot 'plugins/codex/plugin.json') -Raw | ConvertFrom-Json
        $pluginManifest.version = $version
        $pluginManifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $pluginRoot 'plugin.json') -Encoding utf8NoBOM
        $mcp = Get-Content -LiteralPath (Join-Path $projectRoot 'plugins/codex/mcp.json') -Raw | ConvertFrom-Json
        $mcp.mcpServers.reflow.command = './bin/' + $binaryName
        $mcp | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $pluginRoot 'mcp.json') -Encoding utf8NoBOM
        foreach ($file in @('LICENSE','THIRD_PARTY_LICENSES.txt','THIRD_PARTY_NOTICES.md')) { Copy-Item -LiteralPath (Join-Path $projectRoot $file) -Destination $pluginRoot }
        if (Test-Path -LiteralPath (Join-Path $projectRoot 'plugins/codex/README.md')) { Copy-Item -LiteralPath (Join-Path $projectRoot 'plugins/codex/README.md') -Destination $pluginRoot }
        $catalog = @{ name='reflow-local'; interface=@{displayName='Reflow Local'}; plugins=@(@{name='reflow';source=@{source='local';path='./plugins/reflow'};policy=@{installation='AVAILABLE';authentication='ON_INSTALL'};category='Productivity'}) }
        $catalog | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $catalogDir 'marketplace.json') -Encoding utf8NoBOM
        $pluginZip = Join-Path $outputDir "$pluginName.zip"
        & $PythonExe (Join-Path $PSScriptRoot 'archive.py') $marketRoot $pluginZip --executable "plugins/reflow/bin/$binaryName"
        if ($LASTEXITCODE -ne 0) { throw 'Plugin packaging failed' }
        $manifest += [ordered]@{kind='codex-plugin';platform=$platform;archive=[IO.Path]::GetFileName($pluginZip);sha256=(Get-FileHash -LiteralPath $pluginZip -Algorithm SHA256).Hash.ToLowerInvariant();binary_sha256=$binaryHash;binary_path="plugins/reflow/bin/$binaryName";runtime_tested=$false}
    }
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $outputDir 'manifest.json') -Encoding utf8
$manifest | ForEach-Object { "$($_.sha256)  $($_.archive)" } | Set-Content -LiteralPath (Join-Path $outputDir 'checksums.txt') -Encoding ascii
Write-Output "Build saved: $outputDir"
