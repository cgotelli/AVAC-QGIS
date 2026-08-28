#!/usr/bin/env python3
"""Convert a legacy AVAC ``init.xyz`` raster to ``init.avacbin``."""

from __future__ import annotations

import argparse
import struct
import time
from pathlib import Path

import numpy as np


MAGIC = b"AVACQIN1"
HEADER = struct.Struct("<8sqqii4d")


def convert(source: Path, destination: Path) -> tuple[int, int]:
    data = np.loadtxt(source, dtype=np.float64)
    if data.ndim != 2 or data.shape[1] < 3 or data.shape[0] < 4:
        raise ValueError(f"Legacy qinit file has no valid x/y/value table: {source}")
    first_change = np.flatnonzero(data[:, 1] != data[0, 1])
    if first_change.size == 0:
        raise ValueError("Legacy qinit file contains only one row.")
    mx = int(first_change[0])
    total = int(data.shape[0])
    if mx < 2 or total % mx:
        raise ValueError(f"Legacy qinit rows do not form a rectangular raster: rows={total}, columns={mx}")
    my = total // mx
    dx = float((data[mx - 1, 0] - data[0, 0]) / (mx - 1))
    dy = float((data[0, 1] - data[-1, 1]) / (my - 1))
    if dx <= 0.0 or dy <= 0.0:
        raise ValueError(f"Legacy qinit coordinates are not NW-to-SE ordered: dx={dx}, dy={dy}")
    header = HEADER.pack(MAGIC, mx, my, 1, 0, float(data[0, 0]), float(data[0, 1]), dx, dy)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        handle.write(header)
        np.asarray(data[:, 2], dtype="<f8").tofile(handle)
    return mx, my


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", nargs="?", type=Path)
    parser.add_argument("--force", action="store_true", help="replace an existing destination")
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    destination = (args.destination or source.with_suffix(".avacbin")).expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Source file does not exist: {source}")
    if destination.exists() and not args.force:
        raise SystemExit(f"Destination already exists (pass --force to replace it): {destination}")
    started = time.perf_counter()
    mx, my = convert(source, destination)
    elapsed = time.perf_counter() - started
    print(
        f"Converted {mx} x {my} qinit cells in {elapsed:.2f} s: "
        f"{source.stat().st_size / 1048576:.1f} MiB -> {destination.stat().st_size / 1048576:.1f} MiB"
    )


if __name__ == "__main__":
    main()
