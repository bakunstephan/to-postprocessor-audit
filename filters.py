"""
Filter pipeline with tunnel and rib-junction detectors integrated into
the manufacturing and structural filters respectively.
"""

import json
import numpy as np
from scipy.spatial import cKDTree
from complexity_filter import complexity_filter
from geometric_detectors import tunnel_detector, rib_junction_detector


DFM_REJECTION_PATTERNS = {
    "isolated_island": "Mesa-and-depression pattern requires multi-action injection moulding tooling with sliding cores; not economically viable for typical consumer-product components.",
    "through_hole": "Through-hole tunnel requires undercut tooling; incompatible with single-action injection moulding."
}


def manufacturing_filter(region, elements_df=None, config=None):
    """Manufacturing filter with integrated tunnel detection."""
    # Standard pattern-based rejection
    pattern = region['pattern']
    if pattern in DFM_REJECTION_PATTERNS:
        return False, DFM_REJECTION_PATTERNS[pattern]

    # Tunnel detector (new)
    if elements_df is not None and config is not None:
        is_tunnel, tunnel_rationale = tunnel_detector(region, elements_df, config)
        if is_tunnel:
            return False, tunnel_rationale

    return True, "Geometry compatible with single-action injection moulding (continuous walls, no detected undercuts or tunnels)."


def structural_filter(region, fos_threshold, all_elements_df=None,
                     adjacency_radius_mm=15.0, config=None):
    """Structural filter with FoS adjacency AND rib-junction detection."""
    min_fos = region['min_overall_fos']

    fos_by_case = {}
    for k, v in region.items():
        if k.startswith('min_') and k.endswith('_fos') and k != 'min_overall_fos':
            case_name = k[4:-4]
            fos_by_case[case_name] = v

    if fos_by_case:
        governing_case = min(fos_by_case, key=fos_by_case.get)
        fos_summary = ", ".join(f"{c} {v:.2f}" for c, v in fos_by_case.items())
    else:
        governing_case = "unknown"
        fos_summary = f"min_overall {min_fos:.2f}"

    # Check 1: region is itself in critical zone
    if min_fos < fos_threshold:
        return False, (
            f"Region in critical load path: min FoS {min_fos:.2f} < threshold {fos_threshold} "
            f"under {governing_case} load case (FoS: {fos_summary}). Material removal would "
            f"worsen an already-stressed region."
        )

    # Check 2: region is adjacent to critical zone
    if all_elements_df is not None:
        critical_mask = all_elements_df['min_fos'] < fos_threshold
        if critical_mask.any():
            critical_points = all_elements_df.loc[critical_mask, ['x_mm', 'y_mm', 'z_mm']].values
            critical_load_cases = all_elements_df.loc[critical_mask, 'governing_load_case'].values

            centroid = np.array([[region['centroid_x'], region['centroid_y'], region['centroid_z']]])
            tree = cKDTree(critical_points)
            distance, idx = tree.query(centroid, k=1)
            distance = float(distance[0])

            if distance < adjacency_radius_mm:
                critical_loc = critical_points[idx[0]]
                critical_case = critical_load_cases[idx[0]]
                return False, (
                    f"Region adjacent to critical-load zone (distance {distance:.1f} mm to nearest "
                    f"critical element at ({critical_loc[0]:.1f}, {critical_loc[1]:.1f}, "
                    f"{critical_loc[2]:.1f}) governed by {critical_case} load case). "
                    f"Material removal would weaken the load path serving the critical region."
                )

    # Check 3: region at a structural junction (new)
    if all_elements_df is not None and config is not None:
        is_junction, junction_rationale = rib_junction_detector(region, all_elements_df, config)
        if is_junction:
            return False, junction_rationale

    return True, (
        f"Region not in critical load path (FoS: {fos_summary}); "
        f"not adjacent to any critical-load element; not at a structural junction."
    )


def load_functional_zones(filepath):
    try:
        with open(filepath) as f:
            return json.load(f)['functional_zones']
    except FileNotFoundError:
        print(f"  Note: {filepath} not found, no manual functional zones (complexity filter handles this)")
        return []


def functional_filter(region, functional_zones):
    if len(functional_zones) == 0:
        return True, "No manual functional zones defined (complexity filter provides primary functional protection)."

    centroid = [region['centroid_x'], region['centroid_y'], region['centroid_z']]
    for zone in functional_zones:
        bbox = zone['bounding_box']
        if (bbox['x_min'] <= centroid[0] <= bbox['x_max'] and
                bbox['y_min'] <= centroid[1] <= bbox['y_max'] and
                bbox['z_min'] <= centroid[2] <= bbox['z_max']):
            return False, (
                f"Region overlaps manually-annotated functional zone '{zone['name']}' "
                f"(type: {zone['type']}). {zone.get('rationale', 'Functional integrity required.')}"
            )
    return True, "Region does not overlap any manually-annotated functional zone."


def apply_all_filters(regions, functional_zones, config, elements_df=None, complexity_threshold=None):
    print("\n=== Applying filters ===")

    for region in regions:
        # 1. Manufacturing (with tunnel detector)
        mfg_pass, mfg_rationale = manufacturing_filter(region, elements_df=elements_df, config=config)
        region['mfg_filter'] = {'passed': mfg_pass, 'rationale': mfg_rationale}

        # 2. Structural (with rib-junction detector)
        struct_pass, struct_rationale = structural_filter(
            region,
            config.FOS_CRITICAL_THRESHOLD,
            all_elements_df=elements_df,
            adjacency_radius_mm=config.STRUCTURAL_ADJACENCY_RADIUS_MM,
            config=config,
        )
        region['struct_filter'] = {'passed': struct_pass, 'rationale': struct_rationale}

        # 3. Functional (manual zones)
        func_pass, func_rationale = functional_filter(region, functional_zones)
        region['func_filter'] = {'passed': func_pass, 'rationale': func_rationale}

        # 4. Complexity (with improved adjacency-support labeling)
        if complexity_threshold is not None and elements_df is not None:
            cplx_pass, cplx_rationale = complexity_filter(
                region, elements_df, complexity_threshold,
                config=config,
                neighborhood_radius_mm=getattr(config, 'COMPLEXITY_NEIGHBORHOOD_RADIUS_MM', 18.0),
                min_neighbor_complex_count=getattr(config, 'COMPLEXITY_MIN_NEIGHBOR_COUNT', 20)
            )
            region['cplx_filter'] = {'passed': cplx_pass, 'rationale': cplx_rationale}
        else:
            region['cplx_filter'] = {'passed': True, 'rationale': 'Complexity filter not run.'}

        region['accepted'] = mfg_pass and struct_pass and func_pass and region['cplx_filter']['passed']

        if not region['accepted']:
            reasons = []
            if not mfg_pass:
                reasons.append('manufacturing')
            if not struct_pass:
                reasons.append('structural')
            if not func_pass:
                reasons.append('functional')
            if not region['cplx_filter']['passed']:
                reasons.append('complexity')
            region['rejection_categories'] = reasons
        else:
            region['rejection_categories'] = []

    accepted = sum(1 for r in regions if r['accepted'])
    rejected = len(regions) - accepted
    print(f"  Not flagged: {accepted} regions")
    print(f"  Flagged: {rejected} regions")

    return regions