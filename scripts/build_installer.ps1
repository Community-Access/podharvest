<#
.SYNOPSIS
    Builds a standalone, portable podharvest distribution with PyInstaller.

.DESCRIPTION
    - Creates/reuses a build virtual environment (.buildenv) so this never
      touches your regular Python install.
    - Installs runtime + build requirements.
    - Runs PyInstaller against packaging/podharvest.spec (one-folder build).
    - Marks the output as "portable" (podharvest/appspace.py auto-detects
      this file and keeps all models/cache/config next to the exe).
    - Copies README.md / LICENSE into the distribution.
    - Zips the result as podharvest-<version>-win64-portable.zip.

.PARAMETER Clean
    Remove any previous build/ and dist/ output before building.

.PARAMETER Inno
    Also compile installer/podharvest.iss into a conventional Windows
    installer (podharvest-<version>-setup.exe) using Inno Setup's ISCC.exe.
    Requires Inno Setup 6 (https://jrsoftware.org/isinfo.php) to be installed.

.EXAMPLE
    ./scripts/build_installer.ps1
    ./scripts/build_installer.ps1 -Clean
    ./scripts/build_installer.ps1 -Inno
#>
param(
    [switch]$Clean,
    [switch]$Inno
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root

try {
    if ($Clean) {
        Write-Host "[podharvest] Cleaning previous build/dist output..." -ForegroundColor Cyan
        Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
    }

    $venvPython = Join-Path $root ".buildenv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "[podharvest] Creating build virtual environment (.buildenv)..." -ForegroundColor Cyan
        python -m venv "$root\.buildenv"
    }

    Write-Host "[podharvest] Installing requirements..." -ForegroundColor Cyan
    & $venvPython -m pip install --disable-pip-version-check --quiet --upgrade pip
    & $venvPython -m pip install --disable-pip-version-check --quiet -r "$root\requirements.txt"
    & $venvPython -m pip install --disable-pip-version-check --quiet -r "$root\requirements-build.txt"

    Write-Host "[podharvest] Running PyInstaller..." -ForegroundColor Cyan
    & $venvPython -m PyInstaller "$root\packaging\podharvest.spec" --noconfirm --distpath "$root\dist" --workpath "$root\build"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

    $distDir = Join-Path $root "dist\podharvest"
    New-Item -ItemType File -Path (Join-Path $distDir "portable.flag") -Force | Out-Null
    Copy-Item -Path (Join-Path $root "README.md") -Destination $distDir -ErrorAction SilentlyContinue
    Copy-Item -Path (Join-Path $root "LICENSE") -Destination $distDir -ErrorAction SilentlyContinue

    $version = (& $venvPython -c "import sys; sys.path.insert(0, '.'); from podharvest import __version__; print(__version__)").Trim()
    $zipName = "podharvest-$version-win64-portable.zip"
    $zipPath = Join-Path $root "dist\$zipName"
    Remove-Item -Force $zipPath -ErrorAction SilentlyContinue
    Compress-Archive -Path "$distDir\*" -DestinationPath $zipPath

    Write-Host ""
    Write-Host "[podharvest] Build complete:" -ForegroundColor Green
    Write-Host "  Folder : $distDir"
    Write-Host "  Zip    : $zipPath"

    if ($Inno) {
        Write-Host ""
        Write-Host "[podharvest] Compiling Inno Setup installer..." -ForegroundColor Cyan
        $iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if (-not $iscc) {
            # winget installs Inno Setup per-user under LOCALAPPDATA by default,
            # and version 7 exists alongside 6, so checking only the Program
            # Files path for version 6 misses the common case. Newest first.
            $candidates = @(
                "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
                "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
                "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
                "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
                "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
            )
            $hit = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
            if ($hit) { $iscc = Get-Item $hit }
        }
        if (-not $iscc) {
            Write-Warning "ISCC.exe (Inno Setup) not found. Install it from https://jrsoftware.org/isinfo.php or with 'winget install JRSoftware.InnoSetup', then re-run with -Inno."
        }
        else {
            & $iscc.Path "$root\installer\podharvest.iss" "/DMyAppVersion=$version"
            if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed with exit code $LASTEXITCODE" }
            Write-Host "  Setup  : $root\dist\installer\podharvest-$version-setup.exe" -ForegroundColor Green
        }
    }

    Write-Host ""
    Write-Host "Run it with: $distDir\podharvest.exe gui   (or 'hardware', 'fetch <url>', etc.)"
}
finally {
    Pop-Location
}
