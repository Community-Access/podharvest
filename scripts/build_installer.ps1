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

.PARAMETER Sign
    Authenticode-sign the release through Azure Trusted Signing. Every
    executable image in the bundle is signed before the zip is made, and the
    Inno Setup installer is signed after it is compiled. Needs an Azure
    credential ("az login") and the Windows SDK's signtool; check with
    "python scripts/code_signing.py doctor".

    Windows SmartScreen warns on unsigned installers, and that warning is at
    its least helpful read aloud, so a public release is always signed.
    Without this switch the build is unsigned and says so.

.PARAMETER Inno
    Also compile installer/podharvest.iss into a conventional Windows
    installer (podharvest-<version>-setup.exe) using Inno Setup's ISCC.exe.
    Requires Inno Setup 7 (https://jrsoftware.org/isinfo.php), found on PATH
    or in the usual per-user and Program Files locations. Version 7 rather
    than 6 because installer\podharvest.iss uses SetupArchitecture=x64 for a
    64-bit installer and relies on 7's extended-length path support.

.EXAMPLE
    ./scripts/build_installer.ps1
    ./scripts/build_installer.ps1 -Clean
    ./scripts/build_installer.ps1 -Inno
#>
param(
    [switch]$Clean,
    [switch]$Inno,
    [switch]$Sign
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root

function Invoke-Signer {
    <#
        Run scripts/code_signing.py, which does the actual Trusted Signing
        work, and turn any failure into a stopped build. Signing that fails
        quietly is worse than not signing at all: the release looks finished
        and every user still meets SmartScreen.
    #>
    param(
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string]$ScriptRoot,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    & $Python (Join-Path $ScriptRoot "scripts\code_signing.py") @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Code signing failed (exit $LASTEXITCODE)." }
}

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
    # A released binary is only as trustworthy as what went into it. The lock
    # file pins every package, direct and transitive, to one version and one
    # set of SHA-256 hashes, so a build either installs exactly what was
    # reviewed or fails outright -- a tampered or swapped wheel cannot enter
    # a release quietly. Regenerate it deliberately, never as a side effect:
    #   uv pip compile requirements.txt requirements-build.txt \
    #     --generate-hashes --python .buildenv\Scripts\python.exe \
    #     -o requirements-build.lock
    $lock = Join-Path $root "requirements-build.lock"
    if (Test-Path $lock) {
        & $venvPython -m pip install --disable-pip-version-check --quiet `
            --require-hashes --no-deps -r $lock
        if ($LASTEXITCODE -ne 0) { throw "Locked requirements failed to install. Regenerate requirements-build.lock if a pin changed on purpose." }
    }
    else {
        Write-Warning "requirements-build.lock is missing; falling back to unpinned requirements. This build is not reproducible."
        & $venvPython -m pip install --disable-pip-version-check --quiet -r "$root\requirements.txt"
        & $venvPython -m pip install --disable-pip-version-check --quiet -r "$root\requirements-build.txt"
    }

    Write-Host "[podharvest] Running PyInstaller..." -ForegroundColor Cyan
    & $venvPython -m PyInstaller "$root\packaging\podharvest.spec" --noconfirm --distpath "$root\dist" --workpath "$root\build"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

    $distDir = Join-Path $root "dist\podharvest"
    New-Item -ItemType File -Path (Join-Path $distDir "portable.flag") -Force | Out-Null

    # The documentation travels with the app, both ways it ships. The
    # installer used to name these files itself, so the *portable* download
    # arrived with a README and nothing else -- no changelog, no reference,
    # no accessibility statement, and REFERENCE.md linking to a SHARED.md
    # that was not there. Putting them in the build folder fixes both at
    # once, because the installer copies that folder wholesale.
    foreach ($file in @("README.md", "LICENSE", "CHANGELOG.md", "SECURITY.md")) {
        Copy-Item -Path (Join-Path $root $file) -Destination $distDir -ErrorAction SilentlyContinue
    }
    $docsOut = Join-Path $distDir "docs"
    New-Item -ItemType Directory -Force -Path $docsOut | Out-Null
    foreach ($doc in @("GETTING_STARTED.md", "REFERENCE.md", "MODELS.md",
                       "ACCESSIBILITY.md", "SHARED.md", "CODE-REVIEW-2026-09.md")) {
        $source = Join-Path $root "docs\$doc"
        if (Test-Path $source) {
            Copy-Item -Path $source -Destination $docsOut
        }
        else {
            Write-Warning "docs\$doc is named by the build but is not there."
        }
    }
    Write-Host "  Docs   : $((Get-ChildItem $docsOut -Filter *.md).Count) documents bundled"

    # Signed before zipping, so the portable download carries signatures too.
    # Every executable image is signed, not just the launcher: a bundle where
    # only the .exe is signed still loads unsigned code beside it.
    if ($Sign) {
        Write-Host "[podharvest] Signing the application (Azure Trusted Signing)..." -ForegroundColor Cyan
        Invoke-Signer -Python $venvPython -ScriptRoot $root -Arguments @("sign-tree", $distDir)
        Invoke-Signer -Python $venvPython -ScriptRoot $root -Arguments @("verify-tree", $distDir)
    }
    else {
        Write-Warning "No -Sign given: this build is UNSIGNED. Windows SmartScreen will warn users who run it."
    }

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
        # Keep this a plain path string. Get-Command yields a CommandInfo with
        # a .Path, Get-Item yields a FileInfo with a .FullName, and mixing the
        # two means "& $iscc.Path" silently resolves to null for one of them.
        $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Path
        if (-not $iscc) {
            # winget installs Inno Setup per-user under LOCALAPPDATA by
            # default, and 7 installs alongside 6 rather than replacing it, so
            # checking only the Program Files path for 6 misses the common
            # case. Newest first: the script needs 7.
            $candidates = @(
                "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
                "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
                "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
                "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
                "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
            )
            $iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        }
        if (-not $iscc) {
            Write-Warning "ISCC.exe (Inno Setup) not found. Install it from https://jrsoftware.org/isinfo.php or with 'winget install JRSoftware.InnoSetup', then re-run with -Inno."
        }
        else {
            # --version is an Inno Setup 7 option, so a 6 install fails it and
            # the message can say what is actually wrong. The script needs 7
            # for SetupArchitecture=x64 and extended-length path support; 6
            # would fail later with a confusing "unknown directive" instead.
            $isVersion = (& $iscc --version 2>$null) | Select-Object -First 1
            if ($LASTEXITCODE -ne 0 -or -not $isVersion) {
                throw "Found $iscc, but it is not Inno Setup 7. installer\podharvest.iss uses SetupArchitecture, which 6 does not have. Install Inno Setup 7 from https://jrsoftware.org/isinfo.php."
            }
            Write-Host "  Using  : $iscc (Inno Setup $isVersion)"
            # --messages-jsonl (Inno Setup 7) puts errors and warnings on
            # stderr as JSON Lines, so a CI job can read them without parsing
            # prose. Warnings survive --quiet when it is on, which is what you
            # want from a build log.
            & $iscc --quiet --messages-jsonl "/DMyAppVersion=$version" "$root\installer\podharvest.iss"
            if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed with exit code $LASTEXITCODE" }
            $setupPath = Join-Path $root "dist\installer\podharvest-$version-setup.exe"
            # Signed after compiling, not before: the compiler writes the
            # finished .exe, so anything signed earlier would be discarded.
            if ($Sign) {
                Invoke-Signer -Python $venvPython -ScriptRoot $root -Arguments @("sign", $setupPath)
                Invoke-Signer -Python $venvPython -ScriptRoot $root -Arguments @("verify", $setupPath)
            }
            Write-Host "  Setup  : $setupPath" -ForegroundColor Green
        }
    }

    # Checksums for whatever was produced. A signature proves who built it;
    # a checksum lets somebody confirm the download arrived intact, which is
    # the one check that works without any trust in a certificate chain.
    $artifacts = @($zipPath)
    if ($Inno) {
        $setup = Join-Path $root "dist\installer\podharvest-$version-setup.exe"
        if (Test-Path $setup) { $artifacts += $setup }
    }
    $sumsPath = Join-Path $root "dist\SHA256SUMS.txt"
    $artifacts | Where-Object { Test-Path $_ } | ForEach-Object {
        $hash = (Get-FileHash -Algorithm SHA256 $_).Hash.ToLower()
        "$hash  $(Split-Path -Leaf $_)"
    } | Set-Content -Path $sumsPath -Encoding ascii
    Write-Host "  Hashes : $sumsPath" -ForegroundColor Green

    Write-Host ""
    Write-Host "Run it with: $distDir\podharvest.exe gui   (or 'hardware', 'fetch <url>', etc.)"
}
finally {
    Pop-Location
}
