"""
Geometric pattern detectors for the TO post-processor.

These operate on detected removal regions (already-clustered low-density
elements) and on the surrounding high-density mesh, looking for geometric
patterns that simpler statistical filters miss.

Two detectors:
  - tunnel_detector: long thin paths from surface to interior cavity
  - rib_junction_detector: regions at intersection of structural members
"""

import numpy as np
from scipy.spatial import cKDTree


def _count_high_density_neighbors(point, elements_df, radius_mm, tree, density_thresh=0.7):
    """Count high-density elements within radius of point."""
    idx = tree.query_ball_point(point, r=radius_mm)
    if len(idx) == 0:
        return 0
    densities = elements_df['density'].values[idx]
    return int((densities >= density_thresh).sum())


def tunnel_detector(region, elements_df, config):
    """
    Detects regions that look like tunnels: long, thin connected components
    where one end is buried in high-density material and the other end
    opens to a cavity (few high-density neighbors).

    Returns (is_tunnel: bool, rationale: str)
    """
    member_indices = region['element_indices']
    members = elements_df.iloc[member_indices]
    member_pts = members[['x_mm', 'y_mm', 'z_mm']].values

    if len(member_pts) < 8:
        return False, ""

    # 1. Check if region is elongated (high aspect ratio)
    bbox_min = np.array(region['bbox_min'])
    bbox_max = np.array(region['bbox_max'])
    extent = bbox_max - bbox_min
    sorted_extent = np.sort(extent)[::-1]
    longest = sorted_extent[0]
    shortest = max(sorted_extent[2], 0.5)
    aspect_ratio = longest / shortest

    if aspect_ratio < 2.5:
        # Not elongated enough to be a tunnel
        return False, ""

    # 2. Find the two endpoints of the region (most distant pair of member elements)
    # Use the principal axis: SVD on centered member points
    centroid = member_pts.mean(axis=0)
    centered = member_pts - centroid
    try:
        _, _, vh = np.linalg.svd(centered, full_matrices=False)
        principal_axis = vh[0]
    except np.linalg.LinAlgError:
        return False, ""

    # Project members onto principal axis to find extremes
    projections = centered @ principal_axis
    endpoint_a_idx = int(np.argmin(projections))
    endpoint_b_idx = int(np.argmax(projections))
    endpoint_a = member_pts[endpoint_a_idx]
    endpoint_b = member_pts[endpoint_b_idx]

    # 3. Count high-density neighbors near each endpoint
    elem_pts = elements_df[['x_mm', 'y_mm', 'z_mm']].values
    tree = cKDTree(elem_pts)

    # Probe radius scales with mesh
    probe_radius = max(getattr(config, 'STRUCTURAL_ADJACENCY_RADIUS_MM', 15.0) * 0.5, 5.0)

    neighbors_a = _count_high_density_neighbors(endpoint_a, elements_df, probe_radius, tree)
    neighbors_b = _count_high_density_neighbors(endpoint_b, elements_df, probe_radius, tree)

    # Tunnel signature: one end has MANY high-density neighbors (buried in
    # material), the other has FEW (exits into a cavity / outside)
    if neighbors_a == 0 and neighbors_b == 0:
        return False, ""

    max_n = max(neighbors_a, neighbors_b)
    min_n = min(neighbors_a, neighbors_b)
    asymmetry = max_n / max(min_n, 1)

    # Strong asymmetry + elongated shape = tunnel
    if asymmetry >= 3.0:
        if neighbors_a > neighbors_b:
            buried_pt = endpoint_a
            open_pt = endpoint_b
            buried_n = neighbors_a
            open_n = neighbors_b
        else:
            buried_pt = endpoint_b
            open_pt = endpoint_a
            buried_n = neighbors_b
            open_n = neighbors_a

        return True, (
            f"Tunnel detected: elongated region (aspect ratio {aspect_ratio:.1f}:1) "
            f"with strongly asymmetric surroundings. One end at "
            f"({buried_pt[0]:.0f}, {buried_pt[1]:.0f}, {buried_pt[2]:.0f}) is buried in "
            f"high-density material ({buried_n} dense neighbors within {probe_radius:.1f} mm), "
            f"the other end at ({open_pt[0]:.0f}, {open_pt[1]:.0f}, {open_pt[2]:.0f}) "
            f"opens to a cavity ({open_n} dense neighbors). The solver is attempting to "
            f"tunnel through structural material to reach an interior space — manufacturing "
            f"this would require undercut tooling and structurally compromises the wall "
            f"the tunnel passes through."
        )

    return False, ""


def rib_junction_detector(region, elements_df, config):
    """
    Detects regions sitting at junctions of multiple structural members
    (ribs, gussets). Tests whether the high-density material surrounding
    the region's centroid extends in multiple distinct directions.

    Uses PCA on positions of nearby high-density elements: if the three
    principal singular values are relatively similar, the surroundings
    extend in multiple directions (junction). If one is much larger than
    the others, the surroundings extend along a single direction (wall
    or simple beam).

    Returns (is_junction: bool, rationale: str)
    """
    centroid = np.array([region['centroid_x'], region['centroid_y'], region['centroid_z']])

    elem_pts = elements_df[['x_mm', 'y_mm', 'z_mm']].values
    densities = elements_df['density'].values
    tree = cKDTree(elem_pts)

    # Probe a sphere of ~15-20 mm around the centroid
    probe_radius = max(getattr(config, 'STRUCTURAL_ADJACENCY_RADIUS_MM', 15.0), 10.0)
    nearby_idx = tree.query_ball_point(centroid, r=probe_radius)
    if len(nearby_idx) < 20:
        return False, ""

    # Of those, take only high-density elements
    nearby_idx = np.array(nearby_idx)
    nearby_densities = densities[nearby_idx]
    high_density_mask = nearby_densities >= 0.7
    if high_density_mask.sum() < 20:
        return False, ""

    high_density_pts = elem_pts[nearby_idx[high_density_mask]]

    # PCA: how does the high-density material extend around this point?
    centered = high_density_pts - centroid
    try:
        _, s, _ = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError:
        return False, ""

    if s[0] < 1e-6:
        return False, ""

    # Normalized singular values
    s_norm = s / s[0]
    # s_norm[0] = 1.0, s_norm[1] in [0,1], s_norm[2] in [0,1]

    # Junction signature: high-density material extends substantially in
    # multiple directions. We measure this by s_norm[1] (second axis
    # strength relative to first). If s_norm[1] > 0.5, the surroundings
    # extend almost equally in two directions = T or X or L junction.
    # If s_norm[2] is also high (>0.3), it's a 3D junction (corner where
    # three planes meet).

    if s_norm[1] >= 0.5:
        if s_norm[2] >= 0.3:
            junction_type = "3D corner (three or more structural members meet)"
        else:
            junction_type = "T or L junction (two structural members meet)"
        return True, (
            f"Structural junction detected: removal region sits at a {junction_type}. "
            f"Surrounding high-density material extends in multiple directions "
            f"(principal singular values: {s_norm[0]:.2f} / {s_norm[1]:.2f} / "
            f"{s_norm[2]:.2f}). Material at structural junctions routes loads between "
            f"the joined members; removing it weakens the entire load path even if the "
            f"region's current FoS appears acceptable."
        )

    return False, ""