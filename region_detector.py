"""
Connected-component analysis on low-density elements.
Records per-load-case FoS dynamically based on what columns are present.
"""

import numpy as np
from scipy.spatial import cKDTree
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components


def detect_removal_regions(elements_df, config):
    print("\n=== Detecting removal regions ===")

    low_density_mask = elements_df['density'] < config.DENSITY_REMOVAL_THRESHOLD
    low_density_idx = np.where(low_density_mask)[0]

    if len(low_density_idx) == 0:
        print("  No low-density elements found.")
        elements_df = elements_df.copy()
        elements_df['region_id'] = -1
        return elements_df, []

    print(f"  Low-density elements (density < {config.DENSITY_REMOVAL_THRESHOLD}): {len(low_density_idx)}")

    low_density_points = elements_df.loc[low_density_mask, ['x_mm', 'y_mm', 'z_mm']].values
    tree = cKDTree(low_density_points)
    pairs = tree.query_pairs(r=config.ADJACENCY_RADIUS_MM, output_type='ndarray')

    n = len(low_density_idx)
    if len(pairs) > 0:
        rows = np.concatenate([pairs[:, 0], pairs[:, 1]])
        cols = np.concatenate([pairs[:, 1], pairs[:, 0]])
        data = np.ones(len(rows))
        adj = csr_matrix((data, (rows, cols)), shape=(n, n))
    else:
        adj = csr_matrix((n, n))

    n_components, labels = connected_components(adj, directed=False)
    print(f"  Detected {n_components} connected removal regions")

    region_sizes = np.bincount(labels)
    valid_regions = np.where(region_sizes >= config.PATTERN_MIN_REGION_SIZE)[0]
    print(f"  Regions with >= {config.PATTERN_MIN_REGION_SIZE} elements: {len(valid_regions)}")

    elements_df = elements_df.copy()
    elements_df['region_id'] = -1

    region_id_map = {old: new for new, old in enumerate(valid_regions)}

    for i, low_idx in enumerate(low_density_idx):
        old_region = labels[i]
        if old_region in region_id_map:
            elements_df.iloc[low_idx, elements_df.columns.get_loc('region_id')] = region_id_map[old_region]

    regions_summary = []
    for new_id, old_id in enumerate(valid_regions):
        member_indices = low_density_idx[labels == old_id]
        members = elements_df.iloc[member_indices]

        # Per-case FoS (dynamic from columns)
        per_case_fos = {}
        for col in members.columns:
            if col.endswith('_fos') and col != 'min_fos':
                case_name = col[:-4]
                per_case_fos[f'min_{case_name}_fos'] = float(members[col].min())
                per_case_fos[f'mean_{case_name}_fos'] = float(members[col].mean())

        region_record = {
            'region_id': int(new_id),
            'n_elements': int(len(members)),
            'centroid_x': float(members['x_mm'].mean()),
            'centroid_y': float(members['y_mm'].mean()),
            'centroid_z': float(members['z_mm'].mean()),
            'bbox_min': [float(members['x_mm'].min()),
                         float(members['y_mm'].min()),
                         float(members['z_mm'].min())],
            'bbox_max': [float(members['x_mm'].max()),
                         float(members['y_mm'].max()),
                         float(members['z_mm'].max())],
            'mean_density': float(members['density'].mean()),
            'min_overall_fos': float(members['min_fos'].min()),
            'element_indices': member_indices.tolist(),
        }
        region_record.update(per_case_fos)
        regions_summary.append(region_record)

    return elements_df, regions_summary