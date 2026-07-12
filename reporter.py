"""
Generate text and JSON reports. Handles variable load cases.

Reframed language: tool flags removals to reject. "Not flagged" is NOT
the same as "approved" — it means the tool's filters didn't catch a
problem, but the engineer must still verify the removal independently.
"""

import json
import os


def generate_text_report(regions, config, output_path):
    flagged = [r for r in regions if not r['accepted']]
    not_flagged = [r for r in regions if r['accepted']]

    rejection_counts = {'manufacturing': 0, 'structural': 0, 'functional': 0, 'complexity': 0}
    for r in flagged:
        for cat in r['rejection_categories']:
            rejection_counts[cat] = rejection_counts.get(cat, 0) + 1

    lines = []
    lines.append("=" * 70)
    lines.append("TOPOLOGY OPTIMIZATION AUDIT REPORT")
    lines.append("Conservative audit of solver-suggested material removals")
    lines.append("=" * 70)
    lines.append("")
    lines.append("AUDIT PHILOSOPHY")
    lines.append("-" * 70)
    lines.append("This tool is a NEGATIVE FILTER. It identifies removals that should be")
    lines.append("REJECTED. It does not approve removals.")
    lines.append("")
    lines.append("'Not flagged' means: the tool's four filters did not catch a problem")
    lines.append("with this region. It does NOT mean the region is safe to remove.")
    lines.append("Engineering verification of each not-flagged region is still required.")
    lines.append("")
    lines.append(f"Material yield stress:     {config.PP_YIELD_STRESS_MPA} MPa")
    lines.append(f"FoS critical threshold:    {config.FOS_CRITICAL_THRESHOLD}")
    lines.append(f"Density removal threshold: {config.DENSITY_REMOVAL_THRESHOLD}")
    lines.append("")
    lines.append("=" * 70)
    lines.append("SUMMARY")
    lines.append("=" * 70)
    lines.append(f"Total removal regions detected by solver: {len(regions)}")
    lines.append(f"Flagged for rejection:                    {len(flagged)}")
    lines.append(f"  - on Manufacturing (DFM) grounds:       {rejection_counts['manufacturing']}")
    lines.append(f"  - on Structural grounds:                {rejection_counts['structural']}")
    lines.append(f"  - on Functional zone grounds:           {rejection_counts['functional']}")
    lines.append(f"  - on Complexity grounds:                {rejection_counts['complexity']}")
    lines.append(f"Not flagged (verify independently):       {len(not_flagged)}")
    lines.append("")

    total_elements = sum(r['n_elements'] for r in regions)
    not_flagged_elements = sum(r['n_elements'] for r in not_flagged)
    flagged_elements = total_elements - not_flagged_elements

    lines.append("ELEMENT COUNT")
    lines.append("-" * 70)
    lines.append(f"Solver-flagged removable elements:            {total_elements}")
    lines.append(f"Flagged for rejection by audit:               {flagged_elements}")
    lines.append(f"Not flagged by audit (verify independently):  {not_flagged_elements}")
    lines.append("")
    lines.append("=" * 70)
    lines.append("CALIBRATION CAVEATS")
    lines.append("=" * 70)
    lines.append("")
    lines.append("The structural-junction detector uses an absolute threshold of 20 high-")
    lines.append("density elements within the probe radius to identify load-routing")
    lines.append("junctions. This threshold was calibrated against the bumper case study")
    lines.append("(mesh spacing ~3 mm). On parts with substantially coarser meshes (spacing")
    lines.append("> 6 mm), this threshold may not be reached even at genuine junctions,")
    lines.append("causing the detector to miss them.")
    lines.append("")
    lines.append("If your part has a coarser mesh than ~3 mm spacing: the structural")
    lines.append("filter's OTHER checks (FoS adjacency, critical-zone proximity) still fire")
    lines.append("correctly, but specifically the junction detector may under-trigger.")
    lines.append("Manually verify removal regions at visually identifiable rib/wall")
    lines.append("intersections before trusting any 'not flagged' verdict in those areas.")
    lines.append("")
    lines.append("Similarly: the tunnel detector uses an absolute aspect ratio of 2.5:1 and")
    lines.append("asymmetry of 3.0x. These are calibrated to typical automotive-component")
    lines.append("scales. Substantially different scales may need re-calibration.")
    lines.append("")
    lines.append("Statistical-floor calibration (max of absolute_floor and per-part")
    lines.append("statistic) was investigated but requires further validation; this is")
    lines.append("articulated as concrete future work.")
    lines.append("")
    lines.append("=" * 70)
    lines.append("PER-REGION DETAIL")
    lines.append("=" * 70)

    for r in regions:
        lines.append("")
        decision = "FLAGGED FOR REJECTION" if not r['accepted'] else "NOT FLAGGED (verify independently)"
        lines.append(f"[Region {r['region_id']:02d}] {decision}")
        lines.append(f"  Elements:        {r['n_elements']}")
        lines.append(f"  Centroid (mm):   ({r['centroid_x']:.1f}, {r['centroid_y']:.1f}, {r['centroid_z']:.1f})")
        lines.append(f"  Pattern:         {r['pattern']}")
        lines.append(f"  Min FoS overall: {r['min_overall_fos']:.2f}")

        per_case = []
        for k, v in r.items():
            if k.startswith('min_') and k.endswith('_fos') and k != 'min_overall_fos':
                case_name = k[4:-4]
                per_case.append(f"{case_name}: {v:.2f}")
        if per_case:
            lines.append(f"    {', '.join(per_case)}")

        if 'complexity_mean' in r:
            lines.append(f"  Complexity:      mean {r['complexity_mean']:.3f}, max {r['complexity_max']:.3f}, "
                        f"{r['complexity_pct_above_baseline']:.0f}% elements above baseline")
        lines.append("")
        lines.append(f"  Manufacturing filter: {'PASS' if r['mfg_filter']['passed'] else 'FAIL (flag)'}")
        lines.append(f"    {r['mfg_filter']['rationale']}")
        lines.append(f"  Structural filter:    {'PASS' if r['struct_filter']['passed'] else 'FAIL (flag)'}")
        lines.append(f"    {r['struct_filter']['rationale']}")
        lines.append(f"  Functional filter:    {'PASS' if r['func_filter']['passed'] else 'FAIL (flag)'}")
        lines.append(f"    {r['func_filter']['rationale']}")
        lines.append(f"  Complexity filter:    {'PASS' if r['cplx_filter']['passed'] else 'FAIL (flag)'}")
        lines.append(f"    {r['cplx_filter']['rationale']}")

    lines.append("")
    lines.append("=" * 70)
    lines.append("END OF REPORT")
    lines.append("=" * 70)

    text = "\n".join(lines)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(text)

    print(f"\nText report written to {output_path}")
    return text


def generate_json_report(regions, config, output_path):
    serializable_regions = []
    for r in regions:
        r_copy = {k: v for k, v in r.items() if k != 'element_indices'}
        for k, v in r_copy.items():
            if hasattr(v, 'item'):
                r_copy[k] = v.item()
        serializable_regions.append(r_copy)

    output = {
        'audit_philosophy': (
            "Negative filter — flags removals to reject. "
            "'Not flagged' does NOT mean approved; engineering verification required."
        ),
        'calibration_caveats': (
            "Junction detector threshold (20 high-density elements) and tunnel "
            "detector thresholds (2.5:1 aspect ratio, 3.0x asymmetry) are absolute, "
            "calibrated to ~3 mm mesh spacing. Coarser meshes may cause junction "
            "detector to under-trigger; verify rib/wall intersections manually. "
            "Statistical-floor calibration is articulated as future work."
        ),
        'config': {
            'pp_yield_stress_mpa': config.PP_YIELD_STRESS_MPA,
            'fos_critical_threshold': config.FOS_CRITICAL_THRESHOLD,
            'density_removal_threshold': config.DENSITY_REMOVAL_THRESHOLD,
        },
        'summary': {
            'total_regions': len(regions),
            'flagged_for_rejection': sum(1 for r in regions if not r['accepted']),
            'not_flagged': sum(1 for r in regions if r['accepted']),
        },
        'regions': serializable_regions,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"JSON report written to {output_path}")