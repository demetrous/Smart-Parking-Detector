param(
    [string]$LocalDir = (Join-Path $env:LOCALAPPDATA 'ParkingSpotter\frontend')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir      = $PSScriptRoot
$modulesDir     = Join-Path $LocalDir 'node_modules'
$binDir         = Join-Path $modulesDir '.bin'
$viteBin        = Join-Path $binDir 'vite.cmd'
$launcherSrc    = Join-Path $scriptDir 'vite.launcher.config.ts'
$launcherDst    = Join-Path $LocalDir 'vite.launcher.config.ts'
$pkgJson        = Join-Path $scriptDir 'package.json'

# Install packages on first run
if (-not (Test-Path $modulesDir)) {
    Write-Host "dev.ps1: First run - installing packages to $LocalDir" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null
    Copy-Item $pkgJson $LocalDir
    Push-Location $LocalDir
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    } finally {
        Pop-Location
    }
    Write-Host "dev.ps1: Packages ready." -ForegroundColor Green
} else {
    Write-Host "dev.ps1: node_modules found at $modulesDir" -ForegroundColor DarkGreen
}

# Keep @types/react and @types/react-dom in the project-local node_modules so
# Cursor's tsserver can resolve types without requiring a full local install.
# Junctions are not viable on Google Drive (requires local NTFS), so we copy.
$localTypes  = Join-Path $scriptDir 'node_modules\@types'
$sourceTypes = Join-Path $modulesDir '@types'
New-Item -ItemType Directory -Force -Path $localTypes | Out-Null
foreach ($pkg in @('react', 'react-dom')) {
    $pkgSrc = Join-Path $sourceTypes $pkg
    if (Test-Path $pkgSrc) {
        Copy-Item $pkgSrc $localTypes -Recurse -Force
    }
}

# Copy launcher config to AppData (always refresh so edits take effect)
Copy-Item $launcherSrc $launcherDst -Force

# Set env for this session
$env:VITE_PROJECT_ROOT  = $scriptDir
$env:NODE_PATH          = $modulesDir
$env:PATH               = "$binDir;$env:PATH"

Write-Host "dev.ps1: Starting dev server  root=$scriptDir" -ForegroundColor Cyan

Push-Location $LocalDir
try {
    & $viteBin --config $launcherDst
} finally {
    Pop-Location
}
