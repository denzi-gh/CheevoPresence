<#
.SYNOPSIS
    Build a CheevoPresence Flatpak bundle using Docker.

.DESCRIPTION
    Orchestrates the full Flatpak build pipeline inside Docker:
      1. Build (or pull from cache) the build-environment image
      2. Convert the .ico app icon to PNG (ImageMagick in Docker)
      3. Generate pip-sources.json + locked requirements (pip-compile +
         flatpak-pip-generator in Docker)
      4. Build the Flatpak and export a .flatpak bundle
         (flatpak-builder in a privileged Docker container)

    The output bundle is written to .\dist\io.github.denzi_gh.CheevoPresence.flatpak

.PARAMETER SkipImageBuild
    Skip rebuilding the Docker image (use the cached image).

.EXAMPLE
    .\build_flatpak.ps1
    .\build_flatpak.ps1 -SkipImageBuild
#>

param(
    [switch]$SkipImageBuild
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ImageName    = "cheevopresence-flatpak-builder"
$CacheVolume  = "cheevopresence-flatpak-state"   # persists runtimes across runs
$AppId        = "io.github.denzi_gh.CheevoPresence"
$BundleDest   = Join-Path $PSScriptRoot "dist\$AppId.flatpak"

function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host "====================================================" -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host "====================================================" -ForegroundColor Cyan
}

# ── Docker sanity check ────────────────────────────────────────────────────────
Write-Step "Checking Docker"
docker info | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker is not running. Start Docker Desktop and try again."
    exit 1
}
Write-Host "Docker OK." -ForegroundColor Green

# ── 1. Build the image ─────────────────────────────────────────────────────────
if (-not $SkipImageBuild) {
    Write-Step "Building Docker build-environment image"
    docker build `
        --file flatpak\Dockerfile.build `
        --tag  $ImageName `
        --progress plain `
        .
    if ($LASTEXITCODE -ne 0) { Write-Error "Image build failed."; exit 1 }
} else {
    Write-Host "Skipping image build (-SkipImageBuild)." -ForegroundColor Yellow
}

# Ensure the cache volume exists (first-run download of ~2 GB Flatpak runtimes)
docker volume create $CacheVolume | Out-Null

# ── 2-5. Full build (privileged, volume-cached runtimes) ──────────────────────
Write-Step "Running full Flatpak build (privileged container)"
Write-Host "On the first run this downloads ~2 GB of Flatpak runtimes." -ForegroundColor Yellow
Write-Host "Subsequent runs reuse the '$CacheVolume' Docker volume." -ForegroundColor Yellow

docker run `
    --rm `
    --privileged `
    --volume "${PWD}:/src" `
    --volume "${CacheVolume}:/var/lib/flatpak" `
    --workdir /src `
    $ImageName `
    bash flatpak/build_inside_docker.sh

if ($LASTEXITCODE -ne 0) { Write-Error "Flatpak build failed."; exit 1 }

# ── Done ───────────────────────────────────────────────────────────────────────
Write-Step "Build successful"
if (Test-Path $BundleDest) {
    $size = (Get-Item $BundleDest).Length / 1MB
    Write-Host ("Bundle: {0} ({1:N1} MB)" -f $BundleDest, $size) -ForegroundColor Green
} else {
    Write-Host "Bundle: $BundleDest" -ForegroundColor Green
}

Write-Host ""
Write-Host "Install on a Linux machine with:" -ForegroundColor Cyan
Write-Host "  flatpak install $AppId.flatpak" -ForegroundColor White
Write-Host "Run with:"
Write-Host "  flatpak run $AppId" -ForegroundColor White
