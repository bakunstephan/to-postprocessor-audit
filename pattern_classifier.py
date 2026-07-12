"""
Classify each detected removal region by geometric pattern.
"""

import numpy as np


def classify_region(region, elements_df, config):
    member_indices = region['element_indices']
    members = elements_df.iloc[member_indices]

    bbox_min = np.array(region['bbox_min'])
    bbox_max = np.array(region['bbox_max'])
    extent = bbox_max - bbox_min

    sorted_extent = np.sort(extent)[::-1]
    longest = sorted_extent[0]
    shortest = sorted_extent[2] if sorted_extent[2] > 0.01 else 0.01
    aspect_ratio = longest / shortest

    expand = 3.0
    search_min = bbox_min - expand
    search_max = bbox_max + expand

    in_search_zone = (
        (elements_df['x_mm'] >= search_min[0]) & (elements_df['x_mm'] <= search_max[0]) &
        (elements_df['y_mm'] >= search_min[1]) & (elements_df['y_mm'] <= search_max[1]) &
        (elements_df['z_mm'] >= search_min[2]) & (elements_df['z_mm'] <= search_max[2])
    )

    surrounding = elements_df[in_search_zone & ~elements_df.index.isin(member_indices)]

    if len(surrounding) > 0:
        high_density_neighbors = (surrounding['density'] > config.PATTERN_MESA_HIGH_DENSITY_THRESHOLD).sum()
        neighbor_high_density_ratio = high_density_neighbors / len(surrounding)
    else:
        neighbor_high_density_ratio = 0.0

    if neighbor_high_density_ratio > config.PATTERN_ISOLATED_NEIGHBOR_RATIO and len(member_indices) < 50:
        pattern = "isolated_island"
        rationale = (
            f"Region surrounded by {neighbor_high_density_ratio:.0%} high-density "
            f"elements (mesa-and-depression pattern requiring multi-action tooling)"
        )
    elif aspect_ratio > 4.0 and len(member_indices) < 200:
        pattern = "through_hole"
        rationale = (
            f"Elongated region (aspect ratio {aspect_ratio:.1f}:1) suggests "
            f"through-hole or tunnel through structural member"
        )
    elif neighbor_high_density_ratio < 0.4:
        pattern = "excavation"
        rationale = (
            f"Region on free surface ({neighbor_high_density_ratio:.0%} high-density "
            f"surroundings); standard pocket-like removal"
        )
    else:
        pattern = "standard_removal"
        rationale = (
            f"Mixed neighborhood ({neighbor_high_density_ratio:.0%} high-density), "
            f"aspect {aspect_ratio:.1f}:1; standard removal pattern"
        )

    return pattern, rationale


def classify_all_regions(regions, elements_df, config):
    print("\n=== Classifying region patterns ===")

    for region in regions:
        pattern, rationale = classify_region(region, elements_df, config)
        region['pattern'] = pattern
        region['pattern_rationale'] = rationale

    pattern_counts = {}
    for r in regions:
        pattern_counts[r['pattern']] = pattern_counts.get(r['pattern'], 0) + 1
    print(f"  Pattern distribution: {pattern_counts}")

    return regions