[CmdletBinding()]
param(
    [string]$MingwBin = $env:AVAC_MINGW_BIN,
    [string]$Python = "python",
    [string]$Dist = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
Set-Location $root

if (-not $MingwBin) {
    $MingwBin = "C:\Strawberry\c\bin"
}
$MingwBin = (Resolve-Path $MingwBin).Path

$required = @(
    "mingw32-make.exe",
    "gfortran.exe",
    "strip.exe",
    "libgcc_s_seh-1.dll",
    "libgfortran-5.dll",
    "libwinpthread-1.dll",
    "libgomp-1.dll",
    "libquadmath-0.dll",
    "libdl.dll"
)
foreach ($name in $required) {
    $path = Join-Path $MingwBin $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "MinGW runtime file not found: $path"
    }
}

$version = (& $Python -c "from pathlib import Path; fields = dict(line.split('=', 1) for line in (Path('avac_qgis/metadata.txt').read_text(encoding='utf-8').splitlines()) if '=' in line); print(fields['version'].strip())").Trim()
if (-not $version) {
    throw "Could not read the plugin version from avac_qgis/metadata.txt"
}
if (-not $Dist) {
    $Dist = Join-Path $root "dist\windows-amd64"
}
$Dist = [System.IO.Path]::GetFullPath($Dist)
New-Item -ItemType Directory -Force -Path $Dist | Out-Null

$solverArgs = @("-u", "tools/build_windows_solvers.py", "--python", $Python)
& $Python @solverArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$libraries = $required | Where-Object { $_.ToLowerInvariant().EndsWith(".dll") } | ForEach-Object { Join-Path $MingwBin $_ }
$clawpack = "avac-main/clawpack-v5.14.0"
$clawpackLicense = Join-Path $root "$clawpack\LICENSE"
$strawberryLicense = Join-Path $MingwBin "..\..\licenses\License.rtf"

function Build-Runtime([string]$Solver, [string]$Backend, [string]$BackendName, [string]$ArchiveName) {
    $arguments = @(
        "-u", "tools/build_windows_runtime.py",
        "--solver", $Solver,
        "--backend", $Backend,
        "--backend-name", $BackendName,
        "--clawpack", $clawpack,
        "--runtime-version", $version,
        "--output", (Join-Path $Dist $ArchiveName),
        "--license", $clawpackLicense
    )
    if (Test-Path -LiteralPath $strawberryLicense -PathType Leaf) {
        $arguments += @("--license", $strawberryLicense)
    }
    foreach ($library in $libraries) {
        $arguments += @("--library", $library)
    }
    & $Python @arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Build-Runtime "avac-main/src/AVAC/xgeoclaw.exe" "avac-main/src/AVAC" "AVAC" "avac-runtime-windows-amd64-$version.tar.gz"
Build-Runtime "avac-main/src/WAVE/xgeoclaw.exe" "avac-main/src/WAVE" "Wave" "wave-runtime-windows-amd64-$version.tar.gz"

& $Python -u tools/build_windows_plugin_package.py `
    --runtime-archive (Join-Path $Dist "avac-runtime-windows-amd64-$version.tar.gz") `
    --runtime-version $version `
    --wave-runtime-archive (Join-Path $Dist "wave-runtime-windows-amd64-$version.tar.gz") `
    --wave-runtime-version $version `
    --dist $Dist
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Python -u tools/validate_release.py --dist $Dist --platform windows-amd64
exit $LASTEXITCODE
