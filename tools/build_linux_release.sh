#!/usr/bin/env bash
# Build a complete Linux x86_64 QGIS-plugin release on a Linux build host.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python_bin=python3
dist=""
tested_qgis=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --python) python_bin=$2; shift 2 ;;
        --dist) dist=$2; shift 2 ;;
        --tested-qgis) tested_qgis=$2; shift 2 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
done

if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
    printf 'This release builder must run on Linux x86_64.\n' >&2
    exit 1
fi
for program in "$python_bin" make gfortran patchelf strip readelf; do
    command -v "$program" >/dev/null || { printf 'Required build tool is missing: %s\n' "$program" >&2; exit 1; }
done
if [[ -z $tested_qgis ]]; then
    printf 'Pass --tested-qgis with the exact QGIS version used for release testing.\n' >&2
    exit 1
fi

cd "$root"
version=$($python_bin -c "from pathlib import Path; print(dict(line.split('=', 1) for line in Path('avac_qgis/metadata.txt').read_text(encoding='utf-8').splitlines() if '=' in line)['version'].strip())")
if [[ -z $dist ]]; then
    dist="$root/dist/linux-x86_64"
fi
mkdir -p "$dist"

export CLAW="$root/avac-main/clawpack-v5.14.0"
export CLAW_PYTHON="$python_bin"
export FC=gfortran
export CLAW_FC=gfortran

for solver in AVAC WAVE; do
    make -B .exe -C "$root/avac-main/src/$solver"
    strip --strip-all "$root/avac-main/src/$solver/xgeoclaw"
done

licenses=("$CLAW/LICENSE")
for candidate in /usr/share/common-licenses/GPL-3 /usr/share/doc/liblapack3/copyright /usr/share/doc/libblas3/copyright; do
    [[ -f $candidate ]] && licenses+=("$candidate")
done

build_runtime() {
    local solver=$1 backend=$2 prefix=$3
    local arguments=(
        "$python_bin" -u tools/build_linux_runtime.py
        --solver "avac-main/src/$solver/xgeoclaw"
        --backend "avac-main/src/$backend" --backend-name "$backend"
        --clawpack "$CLAW" --runtime-version "$version"
        --output "$dist/$prefix-runtime-linux-x86_64-$version.tar.gz"
    )
    local license
    for license in "${licenses[@]}"; do arguments+=(--license "$license"); done
    "${arguments[@]}"
}

build_runtime AVAC AVAC avac
build_runtime WAVE WAVE wave
"$python_bin" -u tools/build_linux_plugin_package.py \
    --runtime-archive "$dist/avac-runtime-linux-x86_64-$version.tar.gz" --runtime-version "$version" \
    --wave-runtime-archive "$dist/wave-runtime-linux-x86_64-$version.tar.gz" --wave-runtime-version "$version" \
    --tested-qgis "$tested_qgis" --dist "$dist"
"$python_bin" -u tools/validate_release.py --dist "$dist" --platform linux-x86_64
