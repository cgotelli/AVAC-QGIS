"""WAVE edge fitting must agree with AVAC and every prepared artifact."""
from copy import deepcopy
import json

import numpy as np
import pytest
import yaml

from avac_qgis.core.preprocessing import AvacRaster, trim_raster_to_computational_grid
from avac_qgis.core.wave_project import (
    WAVE_MARKER, fit_wave_domain, prepare_wave_lake, prepare_wave_scenario,
    terrain_for_wave_domain,
)


def _raster(nx=43, ny=45, cell=1., xmin=0., ymin=0.):
    return AvacRaster(
        xmin + (np.arange(nx) + .5)*cell,
        ymin + (np.arange(ny) + .5)*cell,
        np.ones((ny, nx)),
        dict(xmin=xmin, xmax=xmin+nx*cell, ymin=ymin, ymax=ymin+ny*cell,
             ncols=nx, nrows=ny, cellsize=cell, nodata_value=-9999.),
        'EPSG:2056', 1,
    )


def _domain(raster):
    return {key: raster.metadata[key] for key in ('xmin', 'xmax', 'ymin', 'ymax')}


@pytest.mark.parametrize('factor', [1, 2, 3, 4, 10])
@pytest.mark.parametrize('nx,ny', [(40, 40), (43, 45), (47, 49)])
@pytest.mark.parametrize('cell,xmin,ymin', [(1., 0., 0.), (.1, 2667311., 1169558.)])
def test_wave_uses_avac_minimal_symmetric_trim(factor, nx, ny, cell, xmin, ymin):
    raster = _raster(nx, ny, cell, xmin, ymin)
    domain = _domain(raster)
    before = deepcopy(raster.metadata), dict(domain), raster.z.copy()
    fitted = fit_wave_domain(domain, raster.metadata, factor*cell)
    expected = trim_raster_to_computational_grid(raster, factor*cell)
    assert fitted == _domain(expected)
    assert fit_wave_domain(fitted, raster.metadata, factor*cell) == fitted
    for axis in ('x', 'y'):
        assert fitted[f'{axis}min'] >= domain[f'{axis}min']
        assert fitted[f'{axis}max'] <= domain[f'{axis}max']
        count = (fitted[f'{axis}max']-fitted[f'{axis}min'])/(factor*cell)
        assert count == pytest.approx(round(count), abs=1e-8, rel=0.)
    assert raster.metadata == before[0] and domain == before[1]
    assert np.array_equal(raster.z, before[2])


def test_wave_trims_requested_avac_window_not_the_entire_dem():
    raster = _raster(60, 70, xmin=100., ymin=200.)
    requested = dict(xmin=103., xmax=146., ymin=205., ymax=250.)
    assert fit_wave_domain(requested, raster.metadata, 4.) == {
        'xmin': 104., 'xmax': 144., 'ymin': 205., 'ymax': 249.,
    }


def test_fitted_wave_terrain_uses_exact_retained_blocks_and_one_cell_halo():
    raster = _raster(43, 45)
    raster.z[:] = np.arange(43*45).reshape(45, 43)
    fitted = fit_wave_domain(_domain(raster), raster.metadata, 4.)
    terrain = terrain_for_wave_domain(raster, fitted, 4.)
    # Retain columns 1:41 and rows 0:44, then average exactly 4x4 samples.
    expected = raster.z[:44, 1:41].reshape(11, 4, 10, 4).mean(axis=(1, 3))
    assert np.array_equal(terrain.z[1:-1, 1:-1], expected)
    assert terrain.z.shape == (13, 12)
    assert np.array_equal(terrain.x[1:-1], 1. + (np.arange(10)+.5)*4.)
    assert np.array_equal(terrain.y[1:-1], (np.arange(11)+.5)*4.)
    assert _domain(terrain) == dict(xmin=-3., xmax=45., ymin=-4., ymax=48.)


@pytest.mark.parametrize('cell', [0., -1., float('nan'), float('inf'), .5, 1.5, 30.])
def test_invalid_mesh_sizes_still_fail_before_preparation(cell):
    raster = _raster()
    with pytest.raises(ValueError):
        fit_wave_domain(_domain(raster), raster.metadata, cell)


@pytest.mark.parametrize('key,value', [('xmin', -.5), ('xmax', 44.), ('ymin', float('nan')),
                                      ('ymax', float('inf')), ('xmin', .5), ('xmax', 42.5)])
def test_uncovered_nonfinite_or_native_misaligned_domains_are_not_resampled(key, value):
    raster = _raster()
    requested = {**_domain(raster), key: value}
    with pytest.raises(ValueError):
        fit_wave_domain(requested, raster.metadata, 4.)


def _source(tmp_path):
    workspace = tmp_path/'workspace'
    avac = workspace/'runs/completed'
    output = avac/'AVAC/_output'
    output.mkdir(parents=True)
    (output/'fort.q0000').write_text('source frame', encoding='utf-8')
    (avac/'.avac_qgis_run.json').write_text(json.dumps({'format': 1, 'status': 'completed'}), encoding='utf-8')
    (avac/'AVAC/AVAC_configuration.yaml').write_text(yaml.safe_dump({
        'dem_extent': dict(xmin=0., xmax=43., ymin=0., ymax=45.),
        'computation': dict(t_max=10., nb_simul=2),
    }), encoding='utf-8')
    return workspace, avac


def _rings():
    return [(np.array([[8., 8.], [32., 8.], [32., 32.], [8., 32.], [8., 8.]]), [])]


@pytest.mark.parametrize('reuse_preview_raster', [False, True])
def test_trimmed_preview_config_mask_and_shoreline_share_one_domain(tmp_path, monkeypatch, reuse_preview_raster):
    workspace, avac = _source(tmp_path)
    original_files = {p: p.read_bytes() for p in avac.rglob('*') if p.is_file()}
    raster = _raster()
    requested = _domain(raster)
    prepared = prepare_wave_lake(raster, _rings(), water_level=1.5, cell_size=4., domain=requested)
    fitted = dict(xmin=1., xmax=41., ymin=0., ymax=44.)
    assert prepared.domain == fitted
    import avac_qgis.core.wave_project as wave_project
    monkeypatch.setattr(wave_project, 'prepare_wave_lake', lambda *_a, **_k: pytest.fail('preview recomputed'))
    # The GUI passes the cached, coarsened terrain and fitted rectangle;
    # direct callers may still pass the original native terrain and bounds.
    input_raster = prepared.raster if reuse_preview_raster else raster
    input_domain = fitted if reuse_preview_raster else requested
    root = prepare_wave_scenario(
        workspace, avac, input_raster, _rings(), water_level=1.5, cell_size=4., domain=input_domain,
        prepared_lake=prepared, gauges=[dict(x=20., y=20.)],
    )
    configuration = yaml.safe_load((root/'impulse_configuration.yaml').read_text())
    assert {key: configuration['lake'][key] for key in fitted} == fitted
    assert configuration['computation']['cell_size'] == 4.
    assert json.loads((root/WAVE_MARKER).read_text())['wave_domain'] == fitted
    header = (root/'Topo/topography_lake.asc').read_text().splitlines()[:6]
    assert [float(line.split()[1]) for line in header[:5]] == [12., 13., -3., -4., 4.]
    mask_lines = (root/'Topo/mask.asc').read_text().splitlines()
    assert [float(line.split()[0]) for line in mask_lines[:5]] == [10., 11., -1., 2., 4.]
    mask = np.loadtxt(root/'Topo/mask.asc', skiprows=6)
    assert np.array_equal(np.flipud(mask) == 0, prepared.solver_wet)
    faces = np.loadtxt(root/'CL/shoreline_faces.txt', ndmin=2)
    assert np.array_equal(faces, prepared.shoreline_faces)
    for axis, column in [('x', 0), ('y', 1)]:
        positions = (faces[:, column] - fitted[f'{axis}min']) / 4. - .5
        assert np.array_equal(positions, np.round(positions))
        assert np.all(faces[:, column] > fitted[f'{axis}min'])
        assert np.all(faces[:, column] < fitted[f'{axis}max'])
    assert all(path.read_bytes() == content for path, content in original_files.items())


def test_gauge_removed_by_edge_trimming_is_rejected(tmp_path):
    workspace, avac = _source(tmp_path)
    raster = _raster()
    with pytest.raises(ValueError, match='gauge 1 is outside'):
        prepare_wave_scenario(workspace, avac, raster, _rings(), water_level=1.5, cell_size=4.,
                              domain=_domain(raster), gauges=[dict(x=.5, y=20.)])
    assert not (workspace/'wave_runs').exists()
