"""Actual terrain writers must not introduce binary64 rounding or curvature.

The native probe reads the generated ASCII directly into Fortran real(kind=8)
and calls the production affine/non-affine classifier. It is deliberately not
a replacement for full GeoClaw topography ingestion or a solver regression.
No source tolerances or physical parameters are changed by these checks.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from avac_qgis.core.preprocessing import (
    AvacRaster,
    read_avac_topography,
    write_init_xyz,
    write_topography,
)


ROOT = Path(__file__).resolve().parents[2]
# Load the sibling runtime rather than an editable installation in another
# checkout: these tests must exercise the writer that will be shipped here.
SPEC = importlib.util.spec_from_file_location(
    "terrain_serialization_runtime", ROOT / "validation/avac4qgis_validation/runtime.py"
)
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def raster(values, *, xmin=-10.0, ymin=0.0, cellsize=.03, nodata=-9999.0):
    values = np.asarray(values, dtype=np.float64)
    ny, nx = values.shape
    return AvacRaster(
        xmin + (np.arange(nx) + .5) * cellsize,
        ymin + (np.arange(ny) + .5) * cellsize,
        values,
        {"xmin": xmin, "xmax": xmin + nx * cellsize,
         "ymin": ymin, "ymax": ymin + ny * cellsize,
         "ncols": nx, "nrows": ny, "cellsize": cellsize, "nodata_value": nodata},
        "EPSG:2056", 1,
    )


@pytest.fixture(params=["plugin", "validation"])
def terrain_writer(request):
    def write(path, terrain):
        if request.param == "plugin":
            write_topography(path, terrain)
        else:
            m = terrain.metadata
            RUNTIME._arc_ascii(path, m["xmin"], m["ymin"], m["cellsize"], terrain.z[::-1])
        return path
    write.name = request.param
    return write


@pytest.fixture(scope="module")
def native_terrain_reader(tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran required for native terrain roundtrip/classifier checks")
    build = tmp_path_factory.mktemp("terrain_ascii_native")
    driver = build / "driver.f90"
    driver.write_text("""program terrain_ascii_reader
  use iso_fortran_env, only: int64
  use rheology_module, only: locally_nonplanar_bed
  implicit none
  integer :: unit,nx,ny,i,j,ii,jj,flag
  real(kind=8) :: xmin,ymin,dx,nodata
  real(kind=8), allocatable :: bed(:,:)
  character(len=4096) :: filename
  character(len=32) :: label
  call get_command_argument(1,filename)
  open(newunit=unit,file=trim(filename),status='old',action='read')
  read(unit,*) label,nx
  read(unit,*) label,ny
  read(unit,*) label,xmin
  read(unit,*) label,ymin
  read(unit,*) label,dx
  read(unit,*) label,nodata
  allocate(bed(nx,ny))
  do j=ny,1,-1
    read(unit,*) bed(:,j)
  enddo
  close(unit)
  write(*,'(4(z16.16,1x))') transfer(xmin,0_int64),transfer(ymin,0_int64), &
                          transfer(dx,0_int64),transfer(nodata,0_int64)
  do j=1,ny
    do i=1,nx
      flag=-1
      if(nx>=3.and.ny>=3) then
        ii=max(2,min(nx-1,i))
        jj=max(2,min(ny-1,j))
        if(all(bed(ii-1:ii+1,jj-1:jj+1)/=nodata)) then
          flag=0
          if(locally_nonplanar_bed(bed(ii,jj),bed(ii-1,jj),bed(ii+1,jj), &
              bed(ii,jj-1),bed(ii,jj+1),bed(ii-1,jj-1),bed(ii+1,jj-1), &
              bed(ii-1,jj+1),bed(ii+1,jj+1))) flag=1
        endif
      endif
      write(*,'(z16.16,1x,i2)') transfer(bed(i,j),0_int64),flag
    enddo
  enddo
end program terrain_ascii_reader
""", encoding="utf-8")
    exe = build / "terrain_ascii_reader.exe"
    compiled = subprocess.run(
        [compiler, "-O2", "-fcheck=all", "-J", str(build),
         str(ROOT / "avac-main/src/AVAC/rheology_module.f90"), str(driver), "-o", str(exe)],
        cwd=build, capture_output=True, text=True, timeout=60,
    )
    assert compiled.returncode == 0, compiled.stderr

    def read(path, shape):
        result = subprocess.run([str(exe), str(path)], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        lines = result.stdout.splitlines()
        header = np.array([int(word, 16) for word in lines[0].split()], dtype=np.uint64)
        samples = [line.split() for line in lines[1:]]
        bits = np.array([int(words[0], 16) for words in samples], dtype=np.uint64).reshape(shape)
        flags = np.array([int(words[1]) for words in samples]).reshape(shape)
        return header.view(np.float64), bits.view(np.float64), flags
    return read


def assert_same_bits(actual, expected):
    np.testing.assert_array_equal(
        np.asarray(actual, dtype=np.float64).view(np.uint64),
        np.asarray(expected, dtype=np.float64).view(np.uint64),
    )


def test_actual_writers_preserve_coordinates_values_and_north_south_order(
    tmp_path, terrain_writer, native_terrain_reader,
):
    values = np.nextafter(np.arange(1., 21.).reshape(4, 5) / 7, np.inf)
    values[0, 0] = -0.0
    values[0, 1] = np.nextafter(1e-20, np.inf)
    values[-1, -1] = np.nextafter(-1e8, -np.inf)
    terrain = raster(values, xmin=2_649_955.987654321, ymin=-1_207_681.123456789,
                     cellsize=np.nextafter(.03, np.inf))
    path = terrain_writer(tmp_path / "terrain.asc", terrain)
    restored = read_avac_topography(path)
    assert_same_bits(restored.z, terrain.z)
    assert_same_bits(restored.x, terrain.x)
    assert_same_bits(restored.y, terrain.y)
    native_header, native_values, _ = native_terrain_reader(path, values.shape)
    m = terrain.metadata
    assert_same_bits(native_header, [m["xmin"], m["ymin"], m["cellsize"], m["nodata_value"]])
    assert_same_bits(native_values, values)
    # ASCII starts at the north edge, unlike the internal south-up arrays.
    ascii_values = np.loadtxt(path, skiprows=6)
    assert_same_bits(ascii_values, values[::-1])


@pytest.mark.parametrize("plane", ["slope", "oblique", "large_positive_datum", "large_negative_datum"])
def test_serialized_planes_remain_affine_in_actual_native_classifier(
    tmp_path, terrain_writer, native_terrain_reader, plane,
):
    x, y = np.meshgrid(-10 + (np.arange(1000) + .5) * .03, (np.arange(5) + .5) * .03)
    values = -np.tan(np.deg2rad(5.)) * x
    if plane != "slope":
        values += .12345678901234567 * y
    if plane == "large_positive_datum":
        values += 1e8
    if plane == "large_negative_datum":
        values -= 1e9
    path = terrain_writer(tmp_path / "plane.asc", raster(values))
    _, native_values, flags = native_terrain_reader(path, values.shape)
    assert_same_bits(native_values, values)
    np.testing.assert_array_equal(flags, np.zeros(values.shape, dtype=int))


def test_resolved_curvature_remains_detectable(tmp_path, terrain_writer, native_terrain_reader):
    x, y = np.meshgrid((np.arange(17) + .5) * .03, (np.arange(9) + .5) * .03)
    values = 1200 + .7 * x - .13 * y + .025 * x**2 + .015 * x * y - .017 * y**2
    path = terrain_writer(tmp_path / "curved.asc", raster(values, xmin=0.))
    _, native_values, flags = native_terrain_reader(path, values.shape)
    assert_same_bits(native_values, values)
    np.testing.assert_array_equal(flags, np.ones(values.shape, dtype=int))


def test_legacy_decimal_precision_reproduces_false_curvature(
    tmp_path, terrain_writer, native_terrain_reader,
):
    x, _ = np.meshgrid(-10 + (np.arange(1000) + .5) * .03, np.arange(5))
    terrain = raster(-np.tan(np.deg2rad(5.)) * x)
    path = terrain_writer(tmp_path / "plane.asc", terrain)
    _, _, full_precision_flags = native_terrain_reader(path, terrain.z.shape)
    assert not np.any(full_precision_flags)
    digits = 10 if terrain_writer.name == "plugin" else 12
    lines = path.read_text(encoding="utf-8").splitlines()[:6]
    lines.extend(" ".join(format(float(value), f".{digits}g") for value in row)
                 for row in terrain.z[::-1])
    legacy = tmp_path / "legacy-rounded.asc"
    legacy.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _, _, legacy_flags = native_terrain_reader(legacy, terrain.z.shape)
    assert np.count_nonzero(legacy_flags) > 0


def test_explicit_nodata_sentinel_and_orientation_are_preserved(
    tmp_path, terrain_writer, native_terrain_reader,
):
    values = np.nextafter(np.arange(20.).reshape(4, 5), np.inf)
    values[0, 1] = -9999.
    values[-1, -2] = -9999.
    path = terrain_writer(tmp_path / "nodata.asc", raster(values))
    _, native_values, _ = native_terrain_reader(path, values.shape)
    assert_same_bits(native_values, values)
    restored = read_avac_topography(path)
    np.testing.assert_array_equal(np.isnan(restored.z), values == -9999.)
    assert_same_bits(restored.z[values != -9999.], values[values != -9999.])


def test_plugin_nonfinite_cells_keep_existing_nodata_conversion(tmp_path, native_terrain_reader):
    values = np.arange(20.).reshape(4, 5)
    values[0, 0], values[1, 2], values[-1, -1] = np.nan, np.inf, -np.inf
    nodata = -9999.1234567890123
    terrain = raster(values, nodata=nodata)
    path = tmp_path / "nodata.asc"
    write_topography(path, terrain)
    header, native_values, _ = native_terrain_reader(path, values.shape)
    assert_same_bits(header[-1], nodata)
    assert_same_bits(native_values, np.where(np.isfinite(values), values, nodata))
    np.testing.assert_array_equal(np.isnan(read_avac_topography(path).z), ~np.isfinite(values))


def test_validation_topography_preparation_uses_full_precision_writer(tmp_path, native_terrain_reader):
    (tmp_path / "Topo").mkdir()
    x, y, values = RUNTIME.write_topography(
        tmp_path, -10., 20., 0., .15, .03,
        lambda xx, yy: -np.tan(np.deg2rad(5.)) * xx + .12345678901234567 * yy,
        ghost_cells=5,
    )
    shape = (len(y), len(x))
    _, native_values, flags = native_terrain_reader(tmp_path / "Topo/topography.asc", shape)
    assert_same_bits(native_values, values)
    assert not np.any(flags)
    _, native_mask, _ = native_terrain_reader(tmp_path / "Topo/mask.asc", shape)
    assert_same_bits(native_mask, np.zeros(shape))


def test_release_xyz_writers_retain_their_existing_precision_and_order(tmp_path):
    terrain = raster(np.zeros((3, 4)), xmin=np.nextafter(1., np.inf), ymin=.12345678901234567)
    depth = np.nextafter(np.arange(1., 13.).reshape(3, 4) / 7, np.inf)
    plugin_path, validation_path = tmp_path / "plugin.xyz", tmp_path / "validation.xyz"
    write_init_xyz(plugin_path, terrain, depth)
    RUNTIME.write_depth_xyz(validation_path, terrain.x, terrain.y, lambda xx, yy: depth)
    expected = "".join(
        f"{terrain.x[i]:.12g} {terrain.y[j]:.12g} {depth[j, i]:.12g}\n"
        for j in range(2, -1, -1) for i in range(4)
    )
    assert plugin_path.read_text() == expected
    assert validation_path.read_text() == expected


def test_coulomb_publication_driver_uses_shared_full_precision_terrain(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "coulomb_precision_driver",
        ROOT / "validation/AVAC/Coulomb_sloping_bed/run_avac_validation.py",
    )
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    x, y = driver.write_inputs(tmp_path, .03)
    expected_bed = np.tan(driver.SLOPE) * np.meshgrid(x, y)[0]
    actual = np.loadtxt(tmp_path / "Topo/topography.asc", skiprows=6)[::-1]
    assert_same_bits(actual, expected_bed)
    # Terrain precision must not silently change this driver's 15g qinit protocol.
    expected_release = "".join(
        f"{xx:.15g} {yy:.15g} {driver.H0 if driver.XLOWER <= xx <= 0. else 0.:.15g}\n"
        for yy in y[::-1] for xx in x
    )
    assert (tmp_path / "AVAC/init.xyz").read_text() == expected_release
