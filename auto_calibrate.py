"""
Auto-calibration: derive spatial parameters from input data.

These values were previously hardcoded in config.py. Now they're computed
from the part's actual mesh and geometry, so the tool adapts to different
parts without manual tuning.
"""

import numpy as np
from scipy.spatial import cKDTree


def auto_calibrate(elements_df, config):
    """
    Derive spatial parameters from input data and store on config object.

    Modifies config in place. Returns nothing.
    """
    print("\n=== Auto-calibrating spatial parameters ===")

    # 1. Mesh element spacing: median distance to nearest neighbor
    points = elements_df[['x_mm', 'y_mm', 'z_mm']].values
    tree = cKDTree(points)
    dists, _ = tree.query(points, k=2)  # k=2 because k=1 is self
    nearest_neighbor_dist = dists[:, 1]
    median_spacing = float(np.median(nearest_neighbor_dist))
    print(f"  Median element nearest-neighbor distance: {median_spacing:.3f} mm")

    # 2. Adjacency radius for region detection (connect adjacent low-density elements)
    config.ADJACENCY_RADIUS_MM = max(1.5 * median_spacing, 0.5)
    print(f"  ADJACENCY_RADIUS_MM = {config.ADJACENCY_RADIUS_MM:.2f} (1.5x spacing)")

    # 3. Structural adjacency radius (region-to-critical-element proximity)
    config.STRUCTURAL_ADJACENCY_RADIUS_MM = max(15 * median_spacing, 5.0)
    print(f"  STRUCTURAL_ADJACENCY_RADIUS_MM = {config.STRUCTURAL_ADJACENCY_RADIUS_MM:.2f} (15x spacing)")

    # 4. Part bounding box (for complexity spread radius scaling)
    bbox_min = points.min(axis=0)
    bbox_max = points.max(axis=0)
    bbox_dims = bbox_max - bbox_min
    longest_dim = float(bbox_dims.max())
    print(f"  Part bounding box: {bbox_dims[0]:.0f} x {bbox_dims[1]:.0f} x {bbox_dims[2]:.0f} mm")
    print(f"  Longest dimension: {longest_dim:.1f} mm")

    # 5. Complexity spread radius: how far feature complexity propagates outward.
    #    Scaled to part size but bounded for sanity.
    spread_raw = max(0.02 * longest_dim, 5 * median_spacing)
    config.COMPLEXITY_SPREAD_RADIUS_MM = min(spread_raw, 0.05 * longest_dim)
    print(f"  COMPLEXITY_SPREAD_RADIUS_MM = {config.COMPLEXITY_SPREAD_RADIUS_MM:.2f}")

    # 6. Complexity neighborhood radius for Layer-2 adjacency-support check
    config.COMPLEXITY_NEIGHBORHOOD_RADIUS_MM = (
            config.COMPLEXITY_NEIGHBORHOOD_RADIUS_FACTOR * config.COMPLEXITY_SPREAD_RADIUS_MM
    )
    print(f"  COMPLEXITY_NEIGHBORHOOD_RADIUS_MM = {config.COMPLEXITY_NEIGHBORHOOD_RADIUS_MM:.2f} "
          f"({config.COMPLEXITY_NEIGHBORHOOD_RADIUS_FACTOR}x spread radius)")

    # 7. Minimum neighbor count for Layer-2 trigger — scales with mesh density
    n_elements = len(elements_df)
    config.COMPLEXITY_MIN_NEIGHBOR_COUNT = max(
        int(config.COMPLEXITY_MIN_NEIGHBOR_COUNT_FACTOR * n_elements),
        20
    )
    print(f"  COMPLEXITY_MIN_NEIGHBOR_COUNT = {config.COMPLEXITY_MIN_NEIGHBOR_COUNT} "
          f"({100 * config.COMPLEXITY_MIN_NEIGHBOR_COUNT_FACTOR:.2f}% of {n_elements} elements)")

    # 8. Minimum region size to consider (ignore noise from a few stray elements)
    config.PATTERN_MIN_REGION_SIZE = max(int(0.00005 * n_elements), 5)
    print(f"  PATTERN_MIN_REGION_SIZE = {config.PATTERN_MIN_REGION_SIZE} "
          f"(0.005% of {n_elements} elements, min 5)")

    print(f"\n=== Auto-calibration complete ===\n")