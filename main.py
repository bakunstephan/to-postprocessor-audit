"""
Main pipeline. Callable as a function with a runtime config object.
"""

import os
from data_loader import load_all_data
from region_detector import detect_removal_regions
from pattern_classifier import classify_all_regions
from filters import apply_all_filters, load_functional_zones
from complexity_filter import compute_complexity_field
from reporter import generate_text_report, generate_json_report
from viewer_3d import launch_viewer, save_screenshots
from auto_calibrate import auto_calibrate


def run_pipeline(config):
    print("\n" + "=" * 70)
    print("TO POST-PROCESSOR — CONSERVATIVE AUDIT MODE")
    print("=" * 70)
    print("This tool flags removals to REJECT. 'Not flagged' is NOT an approval.")
    print("=" * 70)

    elements = load_all_data(config)

    auto_calibrate(elements, config)

    elements, cplx_baseline_mean, cplx_threshold = compute_complexity_field(elements, config)

    elements, regions = detect_removal_regions(elements, config)

    if len(regions) == 0:
        print("\nNo removal regions detected.")
        return

    regions = classify_all_regions(regions, elements, config)

    functional_zones = load_functional_zones(config.FUNCTIONAL_ZONES_FILE)
    print(f"=== Loaded {len(functional_zones)} manual functional zones ===")

    regions = apply_all_filters(
        regions, functional_zones, config,
        elements_df=elements,
        complexity_threshold=cplx_threshold,
    )

    print("\n=== Generating reports ===")
    generate_text_report(regions, config, config.REPORT_TEXT_FILE)
    generate_json_report(regions, config, config.REPORT_JSON_FILE)

    flagged = sum(1 for r in regions if not r['accepted'])
    not_flagged = len(regions) - flagged

    print("\n" + "=" * 70)
    print(f"AUDIT RESULT")
    print(f"  {flagged} of {len(regions)} regions FLAGGED for rejection")
    print(f"  {not_flagged} of {len(regions)} regions NOT FLAGGED")
    print(f"")
    print(f"  IMPORTANT: 'Not flagged' is NOT 'approved'. It means the tool's")
    print(f"  filters did not catch a problem. Engineering verification of each")
    print(f"  not-flagged region is still required.")
    print("=" * 70)

    print("\n=== Saving screenshots ===")
    save_screenshots(
        config.BUMPER_STL_FILE, regions,
        os.path.join(config.OUTPUT_DIR, "screenshots"),
        config, elements_df=elements,
    )

    print("\n=== Launching interactive viewer ===")
    launch_viewer(config.BUMPER_STL_FILE, regions, elements, config)


def main():
    import config
    run_pipeline(config)


if __name__ == "__main__":
    main()