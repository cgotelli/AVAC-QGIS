"""Replot authenticated archived ISeeSnow scalars, without rerunning native gates.

Default rendering uses the portable scalar record and the tracked Table C1 CSV.
For renewed identity checks, additionally supply the original archived JSON and
the released runtime archive. No raw state, reporting threshold, or metric is
recomputed. This deliberately does not modify the normal publication gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import tarfile

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / 'validation'),
               str(REPO / 'validation/ISeeSnow/paper_figures')]

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np

from make_iseesnow_figures import (
    CASES, EXPECTED_PEER_COUNTS, coulomb_pfv_offscale_metadata,
    peer_statistics, validated_peer_table,
)
from avac4qgis_validation.plot_style import (
    MODEL_COLORS, apply_paper_style, figure_size,
)
from avac_qgis.core.runtime import runtime_manifest_sha256


METRICS = (
    ('runout_length_km', 'runout_length_m', 0.001, 'Runout length (km)\n(PFT > 0.5 m)'),
    ('pft_peak_m', 'pft_peak_m', 1.0, 'Peak flow thickness (m)'),
    ('pfv_peak_mps', 'pfv_peak_mps', 1.0, r'Peak flow velocity (m s$^{-1}$)'),
)


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def verify_archived_source(data: dict, path: Path) -> dict:
    content = path.read_bytes()
    assert sha(content) == data['source_record']['sha256'], 'Archived source JSON changed'
    source = json.loads(content)
    gate = source['publication_gate']
    assert gate['solver_sha256'] == data['source_record']['solver_sha256']
    assert gate['setrun_backend_sha256'] == data['source_record']['setrun_backend_sha256']
    assert source['peer_scalar_sha256'] == data['peer_table']['sha256']
    for case, _label in CASES:
        for metric, _field, _scale, _title in METRICS:
            assert source['cases'][case][metric]['avac'] == data['cases'][case][metric]
        for kind in ('pft', 'pfv'):
            assert gate['cases'][case][kind]['sha256'] == data['cases'][case][kind + '_sha256']
    return {'filename': path.name, 'sha256': sha(content), 'all_nine_scalars_exact': True,
            'archived_field_hashes_exact': True, 'no_prior_overlay_values_used': True}


def verify_release_runtime(data: dict, path: Path) -> dict:
    content = path.read_bytes()
    assert sha(content) == data['release_runtime']['archive_sha256'], 'Release archive changed'
    with tarfile.open(path, 'r:gz') as archive:
        manifest_bytes = archive.extractfile('windows-amd64/runtime-manifest.json').read()
        manifest = json.loads(manifest_bytes)
        assert manifest['runtime_version'] == data['release_version'] == '1.0.0'
        canonical_sha = runtime_manifest_sha256(manifest)
        assert canonical_sha == data['release_runtime']['runtime_manifest_sha256']
        solver = manifest['solver']
        native_bytes = archive.extractfile('windows-amd64/' + solver['path']).read()
        solver_sha = sha(native_bytes)
        assert solver_sha == solver['sha256'] == data['release_runtime']['solver_sha256']
        assert solver_sha == data['source_record']['solver_sha256']
        setrun = next(r for r in manifest['backend'] if r['path'] == 'backend/AVAC/setrun.py')
        setrun_sha = sha(archive.extractfile('windows-amd64/' + setrun['path']).read())
        assert setrun_sha == setrun['sha256'] == data['source_record']['setrun_backend_sha256']
    return {'filename': path.name, 'archive_sha256': sha(content),
            'runtime_version': manifest['runtime_version'], 'runtime_manifest_sha256': canonical_sha,
            'actual_solver_bytes_sha256': solver_sha, 'actual_setrun_bytes_sha256': setrun_sha,
            'archived_solver_identity_matches_release': True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path(__file__).with_name('iseesnow_intercomparison_v1_0_data.json'))
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('figures'))
    parser.add_argument('--archived-source', type=Path)
    parser.add_argument('--runtime-archive', type=Path)
    args = parser.parse_args()
    data_bytes = args.data.read_bytes()
    data = json.loads(data_bytes)
    assert data['release_version'] == '1.0.0'
    assert set(data['cases']) == set(EXPECTED_PEER_COUNTS)
    archived_check = verify_archived_source(data, args.archived_source) if args.archived_source else None
    runtime_check = verify_release_runtime(data, args.runtime_archive) if args.runtime_archive else None
    table_path = REPO / data['peer_table']['path_from_repo']
    peers, table_record = validated_peer_table(table_path)
    assert table_record['sha256'] == data['peer_table']['sha256'], 'Tracked peer table changed'
    for case, expected in EXPECTED_PEER_COUNTS.items():
        assert data['cases'][case]['peer_count'] == expected
        for metric, _field, _scale, _title in METRICS:
            assert math.isfinite(data['cases'][case][metric]) and data['cases'][case][metric] >= 0

    apply_paper_style()
    fig, axes = plt.subplots(3, 3, figsize=figure_size(2, aspect=0.91), squeeze=False)
    rng = np.random.default_rng(4127)
    plotted = {}
    for row, (case, _old_label) in enumerate(CASES):
        case_data = data['cases'][case]
        group = peers[peers['case'] == case]
        plotted[case] = {}
        for col, (metric, field, scale, title) in enumerate(METRICS):
            ax = axes[row, col]
            values = group[field].to_numpy(float) * scale
            models = group['model'].astype(str).to_numpy()
            current = case_data[metric]
            stats = peer_statistics(values)
            assert stats['peer_count'] == EXPECTED_PEER_COUNTS[case]
            offscale = (coulomb_pfv_offscale_metadata(models, values, [current])
                        if case == 'CoulombOnly' and metric == 'pfv_peak_mps' else None)
            jitter = rng.uniform(-0.075, 0.075, values.size)
            ax.fill_between([-0.18, 0.18], stats['peer_q1'], stats['peer_q3'],
                            color=MODEL_COLORS['wave'], alpha=0.25, zorder=1)
            ax.hlines(stats['peer_median'], -0.18, 0.18, color=MODEL_COLORS['wave'], linewidth=2.2, zorder=2)
            visible = np.ones(values.size, dtype=bool)
            if offscale is not None:
                visible[offscale['peer_index']] = False
            ax.scatter(jitter[visible], values[visible], color=MODEL_COLORS['wave'],
                       edgecolor='white', linewidth=0.6, zorder=3)
            ax.scatter([1.0], [current], color=MODEL_COLORS['avac'], marker='D', s=44,
                       edgecolor='white', linewidth=0.7, zorder=4)
            ax.set_xlim(-0.4, 1.4)
            ax.set_xticks([0, 1], [f"Peers (n={stats['peer_count']})", 'AVAC'])
            if offscale is not None:
                index = offscale['peer_index']
                ymax = offscale['axis_max']
                ax.set_ylim(offscale['axis_min'], ymax)
                ax.scatter([jitter[index]], [ymax], marker='^', s=48, color=MODEL_COLORS['wave'],
                           edgecolor='white', linewidth=0.6, clip_on=False, zorder=5)
                ax.annotate(f"r.avaflow {offscale['value']:.2f}\n(off scale)",
                            (jitter[index], ymax), xytext=(0.96, 0.96), textcoords='axes fraction',
                            ha='right', va='top', fontsize=6.7)
            if row == 0:
                ax.set_title(title)
            if col == 0:
                ax.set_ylabel(case_data['label'])
            ax.text(0.02, 0.96, '(' + chr(ord('a') + row * 3 + col) + ')',
                    transform=ax.transAxes, ha='left', va='top', fontweight='bold')
            plotted[case][metric] = {'source_field': field, 'display_scale': scale,
                                     'avac': current, **stats,
                                     'peers': [{'model': str(model), 'value': float(value)}
                                               for model, value in zip(models, values)],
                                     'off_scale_peer': offscale}
    legend = [
        Line2D([], [], marker='o', linestyle='None', color=MODEL_COLORS['wave'], label='ISeeSnow Table C1 models'),
        Patch(facecolor=MODEL_COLORS['wave'], alpha=0.25, edgecolor='none', label='Peer interquartile range'),
        Line2D([], [], color=MODEL_COLORS['wave'], linewidth=2.2, label='Peer median'),
        Line2D([], [], marker='D', linestyle='None', color=MODEL_COLORS['avac'], label='AVAC4QGIS 1.0.0'),
    ]
    fig.legend(handles=legend, loc='lower center', bbox_to_anchor=(0.5, 0.015), ncol=2,
               columnspacing=2.0, handletextpad=0.7)
    fig.subplots_adjust(left=0.10, right=0.98, top=0.92, bottom=0.15, hspace=0.34, wspace=0.36)
    args.output.mkdir(parents=True, exist_ok=True)
    stem = 'iseesnow_intercomparison_v1_0'
    for suffix in ('pdf', 'png'):
        fig.savefig(args.output / (stem + '.' + suffix))
    plt.close(fig)
    report = {
        'scope': data['scope'], 'avac_label': 'AVAC4QGIS 1.0.0', 'comparison_overlay': None,
        'source_record': data['source_record'], 'release_runtime': data['release_runtime'],
        'archived_source_verified_this_build': archived_check,
        'release_solver_bytes_verified_this_build': runtime_check,
        'portable_data': {'filename': args.data.name, 'sha256': sha(data_bytes)},
        'builder': {'filename': Path(__file__).name, 'sha256': sha(Path(__file__).read_bytes())},
        'shared_plot_style_sha256': sha((REPO / 'validation/avac4qgis_validation/plot_style.py').read_bytes()),
        'shared_peer_helpers_sha256': sha((REPO / 'validation/ISeeSnow/paper_figures/make_iseesnow_figures.py').read_bytes()),
        'peer_table': data['peer_table'], 'protocol': data['protocol'], 'cases': plotted,
        'notes': [
            'No solver or native publication gate was rerun. This is an explicitly archived scalar replot.',
            'All 11/10/11 Table C1 peers contribute to every statistic; Coulomb r.avaflow PFV322.59m/s is shown off scale.',
            'PFV is the original thresholded/desingularized diagnostic, not the all-wet raw velocity audit.',
            'PFT/runout scalar comparison does not establish spatial or temporal convergence.',
        ],
        'output_sha256': {suffix: sha((args.output / (stem + '.' + suffix)).read_bytes()) for suffix in ('pdf', 'png')},
    }
    (args.output / (stem + '.json')).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'figure': str(args.output / (stem + '.pdf')),
                      'current_scalars': {case: {metric: entry[metric] for metric, *_ in METRICS}
                                          for case, entry in data['cases'].items()},
                      'source_identity_verified': archived_check is not None,
                      'runtime_identity_verified': runtime_check is not None}, indent=2))


if __name__ == '__main__':
    main()
