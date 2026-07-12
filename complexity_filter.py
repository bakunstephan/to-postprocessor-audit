"""
Complexity-based functional region detection.

Two-signal complexity (mesh density + density variation).
NOTE: an earlier version included an SVD-based curvature signal, but
diagnostic testing on the bumper case study showed it produced ~uniform
scores across flat and curved regions (volumetric mesh neighborhoods
do not distinguish curvature the same way surface meshes do). That
signal has been removed pending a better curvature metric in future work.

Two filter stages:
  A. Self-complexity: region's mean complexity vs statistical baseline
  B. Adjacency-support: region surrounded by high-complexity elements
"""

import numpy as np
from scipy.spatial import cKDTree


def compute_raw_complexity(elements_df, k_neighbors=8):
    """Per-element raw complexity = mesh density + density variation."""
    points = elements_df[['x_mm', 'y_mm', 'z_mm']].values
    densities = elements_df['density'].values

    tree = cKDTree(points)
    distances, indices = tree.query(points, k=k_neighbors + 1)
    distances = distances[:, 1:]
    indices = indices[:, 1:]

    mean_dist = distances.mean(axis=1)
    mesh_density_raw = 1.0 / (mean_dist + 0.01)

    neighbor_densities = densities[indices]
    density_var_raw = neighbor_densities.std(axis=1)

    def norm01(arr):
        a_min, a_max = arr.min(), arr.max()
        if a_max - a_min < 1e-9:
            return np.zeros_like(arr)
        return (arr - a_min) / (a_max - a_min)

    return norm01(mesh_density_raw) + norm01(density_var_raw)


def spread_complexity_fast(elements_df, raw_complexity, spread_radius_mm=8.0):
    points = elements_df[['x_mm', 'y_mm', 'z_mm']].values
    n = len(points)
    tree = cKDTree(points)

    spread = raw_complexity.copy()

    batch_size = 5000
    for start in range(0, n, batch_size):
        end = min(start + batch_size, n)
        batch_pts = points[start:end]
        idx_lists = tree.query_ball_point(batch_pts, r=spread_radius_mm)

        for local_i, idx in enumerate(idx_lists):
            i = start + local_i
            if len(idx) == 0:
                continue
            dists = np.linalg.norm(points[idx] - points[i], axis=1)
            weights = 1.0 - (dists / spread_radius_mm)
            weights = np.clip(weights, 0, 1)
            contributions = raw_complexity[idx] * weights
            best = contributions.max()
            if best > spread[i]:
                spread[i] = best

    return spread


def compute_complexity_field(elements_df, config):
    print("\n=== Computing complexity field ===")

    n_neighbors = getattr(config, 'COMPLEXITY_K_NEIGHBORS', 8)
    spread_radius = getattr(config, 'COMPLEXITY_SPREAD_RADIUS_MM', 8.0)
    n_sigma = getattr(config, 'COMPLEXITY_N_SIGMA', 1.0)
    density_thresh = getattr(config, 'DENSITY_REMOVAL_THRESHOLD', 0.5)

    print(f"  Computing raw complexity (k={n_neighbors}, 2-signal)...")
    raw = compute_raw_complexity(elements_df, k_neighbors=n_neighbors)

    print(f"  Spreading complexity (radius={spread_radius:.2f} mm)...")
    spread = spread_complexity_fast(elements_df, raw, spread_radius_mm=spread_radius)

    elements_df = elements_df.copy()
    elements_df['complexity_raw'] = raw
    elements_df['complexity'] = spread

    low_density_mask = elements_df['density'] < density_thresh
    low_density_complexity = spread[low_density_mask]

    if len(low_density_complexity) == 0:
        print("  No low-density elements; skipping complexity filter.")
        elements_df['complexity_above_baseline'] = False
        return elements_df, 0.0, np.inf

    mean = float(low_density_complexity.mean())
    std = float(low_density_complexity.std())
    threshold = mean + n_sigma * std

    elements_df['complexity_above_baseline'] = spread > threshold

    n_low = int(low_density_mask.sum())
    n_above = int(((spread > threshold) & low_density_mask).sum())
    print(f"  Baseline (low-density only, n={n_low}):")
    print(f"    mean={mean:.3f}, std={std:.3f}, threshold (mean + {n_sigma}*std)={threshold:.3f}")
    print(f"  Low-density elements above threshold: {n_above} ({100*n_above/n_low:.1f}%)")

    return elements_df, mean, threshold


def _classify_adjacent_complex_features(region, elements_df, config, neighborhood_radius_mm):
    """
    When adjacency-support rejection fires, classify WHAT'S adjacent.
    Is the nearby complex material near critical-FoS zones? Functional zones?
    Returns a descriptive string to include in the rationale.
    """
    centroid = np.array([region['centroid_x'], region['centroid_y'], region['centroid_z']])
    elem_pts = elements_df[['x_mm', 'y_mm', 'z_mm']].values
    dists = np.linalg.norm(elem_pts - centroid, axis=1)

    in_neighborhood = dists <= neighborhood_radius_mm
    high_complex = elements_df['complexity_above_baseline'].values & in_neighborhood

    if high_complex.sum() == 0:
        return "adjacent complex geometry"

    # Of those nearby high-complex elements, how many are near critical stress?
    fos_threshold = getattr(config, 'FOS_CRITICAL_THRESHOLD', 1.5)
    critical_mask = elements_df['min_fos'] < fos_threshold * 2.0  # within 2x of critical
    near_critical = (high_complex & critical_mask).sum()

    near_critical_frac = near_critical / max(high_complex.sum(), 1)

    if near_critical_frac > 0.4:
        return "adjacent complex geometry sitting in or near elevated-stress zones (likely a structural feature: rib, gusset junction, or stress-routing member)"
    elif near_critical_frac > 0.1:
        return "adjacent complex geometry with some elevated-stress elements (mixed structural/functional feature)"
    else:
        return "adjacent complex geometry in low-stress regions (likely a functional feature: sensor pocket, mounting interface, or other geometric registration surface)"


def complexity_filter(region, elements_df, threshold, config=None,
                     neighborhood_radius_mm=12.0, min_neighbor_complex_count=60):
    """
    Two-stage complexity filter with improved adjacency-support labeling.
    """
    member_indices = region['element_indices']
    members = elements_df.iloc[member_indices]

    region_mean = float(members['complexity'].mean())
    region_max = float(members['complexity'].max())
    n_above = int(members['complexity_above_baseline'].sum())
    pct_above = 100.0 * n_above / len(members)

    region['complexity_mean'] = region_mean
    region['complexity_max'] = region_max
    region['complexity_pct_above_baseline'] = pct_above

    # Stage A: self-complexity
    if region_mean > threshold:
        return False, (
            f"Self-complexity rejection: region mean complexity {region_mean:.3f} > "
            f"baseline threshold {threshold:.3f}. The region IS a geometrically "
            f"distinguished feature (mesh refinement and density transitions indicate "
            f"functional importance)."
        )

    if pct_above > 30.0:
        return False, (
            f"Self-complexity rejection: {pct_above:.0f}% of region elements above "
            f"baseline. Region partially overlaps a geometrically refined zone."
        )

    # Stage B: adjacency-support
    centroid = np.array([region['centroid_x'], region['centroid_y'], region['centroid_z']])
    elem_pts = elements_df[['x_mm', 'y_mm', 'z_mm']].values
    dists_to_centroid = np.linalg.norm(elem_pts - centroid, axis=1)

    in_neighborhood = dists_to_centroid <= neighborhood_radius_mm
    above_baseline = elements_df['complexity_above_baseline'].values
    high_complex_neighbors = int((in_neighborhood & above_baseline).sum())

    region['complexity_neighborhood_high_count'] = high_complex_neighbors

    if high_complex_neighbors >= min_neighbor_complex_count:
        # Classify what kind of feature it's adjacent to
        feature_desc = (
            _classify_adjacent_complex_features(region, elements_df, config, neighborhood_radius_mm)
            if config is not None else "adjacent complex geometry"
        )
        return False, (
            f"Adjacency-support rejection: region itself is flat (mean complexity "
            f"{region_mean:.3f} <= threshold {threshold:.3f}), but "
            f"{high_complex_neighbors} high-complexity elements within "
            f"{neighborhood_radius_mm:.0f} mm. Material here directly supports "
            f"{feature_desc}. Removal would compromise the supported feature."
        )

    return True, (
        f"Region complexity within baseline (mean {region_mean:.3f}, "
        f"{pct_above:.0f}% above baseline, {high_complex_neighbors} high-complexity "
        f"elements within {neighborhood_radius_mm:.0f} mm)."
    )