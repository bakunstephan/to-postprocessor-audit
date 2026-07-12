"""
Surface-colored 3D visualization. Paints bumper STL faces by audit category.

Categories reframed: tool flags regions for rejection. "Not flagged" is NOT
an approval — it means the tool's filters did not catch a problem with
that region. Engineering verification is still required.
"""

import pyvista as pv
import numpy as np
from scipy.spatial import cKDTree


CAT_KEEP = 0           # solver wanted to keep
CAT_NOT_FLAGGED = 1    # solver wanted to remove, audit didn't catch a problem
CAT_DFM = 2            # flagged: manufacturing
CAT_STRUCT = 3         # flagged: structural
CAT_FUNC = 4           # flagged: functional (manual zones)
CAT_CPLX = 5           # flagged: complexity
CAT_MULTI = 6          # flagged on multiple grounds

CATEGORY_COLORS = {
    CAT_KEEP:        [0.75, 0.75, 0.75],
    CAT_NOT_FLAGGED: [0.95, 0.95, 0.40],  # pale yellow — not green, not approved
    CAT_DFM:         [0.90, 0.10, 0.10],
    CAT_STRUCT:      [1.00, 0.55, 0.00],
    CAT_FUNC:        [0.50, 0.30, 0.80],
    CAT_CPLX:        [0.00, 0.75, 0.75],
    CAT_MULTI:       [0.60, 0.00, 0.60],
}

CATEGORY_LABELS = {
    CAT_KEEP:        'Keep (solver high density)',
    CAT_NOT_FLAGGED: 'Not flagged (verify independently)',
    CAT_DFM:         'Flagged: Manufacturing',
    CAT_STRUCT:      'Flagged: Structural',
    CAT_FUNC:        'Flagged: Functional zone',
    CAT_CPLX:        'Flagged: Complexity',
    CAT_MULTI:       'Flagged: Multiple grounds',
}


def region_category(region):
    if region['accepted']:
        return CAT_NOT_FLAGGED
    cats = region['rejection_categories']
    if len(cats) > 1:
        return CAT_MULTI
    return {
        'manufacturing': CAT_DFM,
        'structural':    CAT_STRUCT,
        'functional':    CAT_FUNC,
        'complexity':    CAT_CPLX,
    }.get(cats[0], CAT_KEEP)


def build_face_categories(stl_mesh, elements_df, regions, max_distance_mm=10.0):
    face_centers = stl_mesh.cell_centers().points

    elem_pts = elements_df[['x_mm', 'y_mm', 'z_mm']].values
    elem_tree = cKDTree(elem_pts)
    distances, indices = elem_tree.query(face_centers, k=1)

    elem_idx_to_cat = {}
    for r in regions:
        cat = region_category(r)
        for idx in r['element_indices']:
            elem_idx_to_cat[idx] = cat

    n_faces = len(face_centers)
    face_cats = np.full(n_faces, CAT_KEEP, dtype=np.int32)
    densities = elements_df['density'].values

    for fi in range(n_faces):
        if distances[fi] > max_distance_mm:
            face_cats[fi] = CAT_KEEP
            continue
        elem_idx = int(indices[fi])
        if elem_idx in elem_idx_to_cat:
            face_cats[fi] = elem_idx_to_cat[elem_idx]
        else:
            face_cats[fi] = CAT_KEEP

    return face_cats


def make_colored_mesh(stl_mesh, face_cats):
    rgb = np.zeros((len(face_cats), 3), dtype=np.float32)
    for cat, color in CATEGORY_COLORS.items():
        mask = face_cats == cat
        rgb[mask] = color
    mesh = stl_mesh.copy()
    mesh.cell_data['rgb'] = rgb
    return mesh


def launch_viewer(stl_path, regions, elements_df, config):
    print("\n=== Launching 3D viewer ===")
    print("Controls: Left-drag rotate | Middle-drag pan | Wheel zoom | q to quit")

    try:
        bumper = pv.read(stl_path)
    except Exception as e:
        print(f"  ERROR loading STL: {e}")
        return

    print(f"  STL: {bumper.n_cells} faces, {bumper.n_points} vertices")
    face_cats = build_face_categories(bumper, elements_df, regions)

    print(f"  Face category distribution:")
    for cat, label in CATEGORY_LABELS.items():
        n = int((face_cats == cat).sum())
        if n > 0:
            print(f"    {label}: {n} faces")

    colored = make_colored_mesh(bumper, face_cats)

    plotter = pv.Plotter(window_size=(1400, 900))
    plotter.add_mesh(colored, scalars='rgb', rgb=True, show_edges=False, smooth_shading=True)

    legend_entries = [[CATEGORY_LABELS[c], CATEGORY_COLORS[c]] for c in CATEGORY_COLORS]
    plotter.add_legend(legend_entries, bcolor='white', size=(0.30, 0.22))

    flagged_count = sum(1 for r in regions if not r['accepted'])
    not_flagged_count = len(regions) - flagged_count
    title = (
        f"TO Audit — Surface Color = Audit Decision\n"
        f"{flagged_count} regions flagged for rejection | {not_flagged_count} not flagged "
        f"(NOT an approval — engineering verification required)"
    )
    plotter.add_text(title, position='upper_left', font_size=10, color='black')

    plotter.add_axes()
    plotter.camera_position = 'iso'
    plotter.reset_camera()
    plotter.show()


def save_screenshots(stl_path, regions, output_dir, config, elements_df=None):
    import os
    os.makedirs(output_dir, exist_ok=True)

    if elements_df is None:
        print("  Skipping screenshots (elements_df not provided)")
        return

    try:
        bumper = pv.read(stl_path)
    except Exception as e:
        print(f"  ERROR loading STL: {e}")
        return

    face_cats = build_face_categories(bumper, elements_df, regions)
    colored = make_colored_mesh(bumper, face_cats)

    angles = {
        'isometric': 'iso',
        'top': 'xy',
        'front': 'yz',
        'side': 'xz',
    }

    for view_name, camera_pos in angles.items():
        plotter = pv.Plotter(off_screen=True, window_size=(1400, 900))
        plotter.add_mesh(colored, scalars='rgb', rgb=True, show_edges=False, smooth_shading=True)
        legend_entries = [[CATEGORY_LABELS[c], CATEGORY_COLORS[c]] for c in CATEGORY_COLORS]
        plotter.add_legend(legend_entries, bcolor='white', size=(0.30, 0.22))
        plotter.camera_position = camera_pos
        plotter.reset_camera()
        screenshot_path = os.path.join(output_dir, f'view_{view_name}.png')
        plotter.screenshot(screenshot_path)
        plotter.close()
        print(f"  Saved: {screenshot_path}")

    print(f"\nScreenshots saved to {output_dir}/")