"""
Data loading: stress CSVs (variable number, with optional symmetry mirroring)
+ topology density CSV.
"""

import pandas as pd
import numpy as np
from scipy.spatial import cKDTree


def load_stress_csv(filepath):
    df = pd.read_csv(filepath, skiprows=7, encoding='latin-1', skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns={
        'Node': 'node_id',
        'Value (N/m^2)': 'stress_pa',
        'X (mm)': 'x_mm',
        'Y (mm)': 'y_mm',
        'Z (mm)': 'z_mm'
    })
    df = df.dropna(subset=['node_id'])
    df['stress_mpa'] = df['stress_pa'] / 1e6
    print(f"Loaded {len(df)} stress nodes from {filepath}")
    print(f"  Stress range: {df['stress_mpa'].min():.3f} - {df['stress_mpa'].max():.3f} MPa")
    return df


def load_density_csv(filepath):
    df = pd.read_csv(filepath, skiprows=7, encoding='latin-1', skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns={
        'Element': 'element_id',
        'Value': 'density',
        'X (mm)': 'x_mm',
        'Y (mm)': 'y_mm',
        'Z (mm)': 'z_mm'
    })
    df = df.dropna(subset=['element_id'])
    print(f"Loaded {len(df)} topology elements from {filepath}")
    print(f"  Density range: {df['density'].min():.3f} - {df['density'].max():.3f}")
    print(f"  Elements with density < 0.5: {(df['density'] < 0.5).sum()}")
    return df


def interpolate_stress_to_elements(elements_df, stress_df, k=4):
    stress_points = stress_df[['x_mm', 'y_mm', 'z_mm']].values
    tree = cKDTree(stress_points)
    element_points = elements_df[['x_mm', 'y_mm', 'z_mm']].values
    distances, indices = tree.query(element_points, k=k)
    stress_values = stress_df['stress_mpa'].values
    interpolated = stress_values[indices].mean(axis=1)
    elements_df = elements_df.copy()
    elements_df['stress_mpa'] = interpolated
    return elements_df


def compute_fos(stress_mpa, yield_mpa):
    return np.where(stress_mpa > 0.001, yield_mpa / stress_mpa, 999.0)


def _safe_name(name):
    """Sanitize a name for use as a column/identifier."""
    result = name.lower().replace(' ', '_').replace('-', '_')
    result = result.replace('(', '').replace(')', '').replace('/', '_')
    return result


def _mirror_stress_df(stress_df, axis, plane_coord):
    """Reflect stress dataframe coordinates across a symmetry plane."""
    mirrored = stress_df.copy()
    axis_col = {'X': 'x_mm', 'Y': 'y_mm', 'Z': 'z_mm'}[axis]
    mirrored[axis_col] = 2 * plane_coord - mirrored[axis_col]
    return mirrored


def load_all_data(config):
    """
    Load all CSVs (variable load cases, optional symmetry mirroring).
    Returns elements_df with per-case stress/FoS columns plus min_fos.
    """
    print("\n=== Loading data ===")

    topology = load_density_csv(config.TOPOLOGY_DENSITY_FILE)

    load_cases = config.LOAD_CASES
    if not load_cases:
        raise ValueError("No load cases specified")

    # Expand: each mirror-flagged case produces original + synthetic mirror
    expanded = []
    for lc in load_cases:
        expanded.append({
            'name': lc['name'],
            'safe_name': _safe_name(lc['name']),
            'path': lc['path'],
            'is_mirrored': False,
        })
        if lc.get('mirror'):
            expanded.append({
                'name': f"{lc['name']} (mirrored)",
                'safe_name': _safe_name(lc['name']) + "_mirror",
                'path': lc['path'],
                'is_mirrored': True,
                'mirror_axis': lc['mirror_axis'],
                'mirror_plane': lc['mirror_plane'],
            })

    print(f"\n=== Interpolating stress to elements ({len(expanded)} load cases including mirrors) ===")

    case_names = []
    for spec in expanded:
        stress_df = load_stress_csv(spec['path'])

        if spec['is_mirrored']:
            stress_df = _mirror_stress_df(stress_df, spec['mirror_axis'], spec['mirror_plane'])
            print(f"  Mirrored '{spec['name']}' across {spec['mirror_axis']}={spec['mirror_plane']:.1f}")

        topology = interpolate_stress_to_elements(topology, stress_df, k=config.STRESS_INTERPOLATION_K)
        col_stress = f"{spec['safe_name']}_stress_mpa"
        topology = topology.rename(columns={'stress_mpa': col_stress})
        case_names.append(spec['safe_name'])
        print(f"  {spec['safe_name']}: max element stress {topology[col_stress].max():.2f} MPa")

    fos_cols = []
    for safe_name in case_names:
        topology[f'{safe_name}_fos'] = compute_fos(
            topology[f'{safe_name}_stress_mpa'], config.PP_YIELD_STRESS_MPA
        )
        fos_cols.append(f'{safe_name}_fos')

    topology['min_fos'] = topology[fos_cols].min(axis=1)

    fos_array = topology[fos_cols].values
    governing_idx = fos_array.argmin(axis=1)
    topology['governing_load_case'] = [case_names[i] for i in governing_idx]

    config.CASE_NAMES = case_names

    print(f"\nElement-level data ready: {len(topology)} elements with density + {len(case_names)}-way FoS")
    print(f"Min FoS distribution by governing case:")
    for case in case_names:
        n = (topology['governing_load_case'] == case).sum()
        print(f"  {case}: {n} elements ({100*n/len(topology):.1f}%)")

    return topology