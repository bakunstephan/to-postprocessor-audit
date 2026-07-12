"""
TO Post-Processor — Graphical interface.

Audits a SolidWorks topology optimization study by replaying the solver's
suggestions against engineering constraint categories.

The tool operates as a NEGATIVE FILTER: it identifies removals to REJECT.
It does not approve removals — anything not flagged is the engineer's
responsibility to verify independently.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import traceback
import sys
import os


# Strict parameters — baked in, not user-tunable.
# These reflect the most conservative defensible criteria for catching
# unsafe TO removals. The tool is an audit, not a permissiveness dial.
STRICT_PARAMS = {
    "n_sigma": 1.3,
    "neighborhood_radius_factor": 2.0,
    "min_neighbor_count_factor": 0.005,
}


def resource_path(relative_path):
    """Get path to resource, works for dev and PyInstaller bundle."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


class TOPostProcessorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TO Post-Processor")
        self.root.geometry("900x1050")
        try:
            self.root.iconbitmap(resource_path("Icon.ico"))
        except Exception:
            pass  # icon optional; don't crash if missing

        self.yield_stress = tk.DoubleVar(value=27.6)
        self.fos_threshold = tk.DoubleVar(value=1.5)
        self.density_path = tk.StringVar()
        self.stl_path = tk.StringVar()
        self.output_dir = tk.StringVar(value="output")

        self.load_cases = []

        self._build_ui()
        self._add_load_case()

    def _build_ui(self):
        outer = ttk.Frame(self.root)
        outer.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollable = ttk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=scrollable, anchor='nw')

        def on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", on_configure)

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)

        main = ttk.Frame(scrollable, padding=15)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="TO Post-Processor", font=('Arial', 14, 'bold')).pack(anchor='w')
        ttk.Label(
            main,
            text="Conservative audit of SolidWorks topology optimization output",
            font=('Arial', 9, 'italic'), foreground='#555'
        ).pack(anchor='w', pady=(0, 12))

        # PHILOSOPHY BLOCK — explain what the tool does and doesn't do
        philosophy = ttk.LabelFrame(main, text="What this tool does", padding=10)
        philosophy.pack(fill=tk.X, pady=5)

        ttk.Label(
            philosophy,
            text=(
                "This tool is a NEGATIVE FILTER. It identifies TO solver suggestions to REJECT — "
                "removals that would compromise manufacturing, structural integrity, or functional "
                "interfaces. It applies the strictest defensible criteria.\n\n"
                "What this tool DOES:\n"
                "  • Flags removals that should NOT be made\n"
                "  • Provides per-region rationale for each rejection\n"
                "  • Applies four orthogonal filters (manufacturing, structural, functional, complexity)\n\n"
                "What this tool DOES NOT do:\n"
                "  • Approve removals — anything 'not flagged' is the engineer's responsibility\n"
                "  • Replace engineering judgment — the tool can only catch what its filters recognize\n"
                "  • Provide a tunable permissiveness setting — that would defeat the audit purpose"
            ),
            font=('Arial', 9), foreground='#333',
            wraplength=820, justify='left'
        ).pack(anchor='w')

        # Material & engineering
        sec1 = ttk.LabelFrame(main, text="Material & Engineering Parameters", padding=10)
        sec1.pack(fill=tk.X, pady=5)

        r1 = ttk.Frame(sec1)
        r1.pack(fill=tk.X, pady=3)
        ttk.Label(r1, text="Material yield stress (MPa):", width=32).pack(side=tk.LEFT)
        ttk.Entry(r1, textvariable=self.yield_stress, width=12).pack(side=tk.LEFT)
        ttk.Label(
            r1, text="(e.g. PP=27.6, ABS=41, PA66=75, Al-6061=276)",
            font=('Arial', 8, 'italic'), foreground='#666'
        ).pack(side=tk.LEFT, padx=10)

        r2 = ttk.Frame(sec1)
        r2.pack(fill=tk.X, pady=3)
        ttk.Label(r2, text="FoS critical threshold:", width=32).pack(side=tk.LEFT)
        ttk.Entry(r2, textvariable=self.fos_threshold, width=12).pack(side=tk.LEFT)
        ttk.Label(
            r2, text="(regions below this FoS are rejected; std engineering = 1.5)",
            font=('Arial', 8, 'italic'), foreground='#666'
        ).pack(side=tk.LEFT, padx=10)

        # Input files overview
        intro = ttk.LabelFrame(main, text="Input Files — Overview", padding=10)
        intro.pack(fill=tk.X, pady=5)

        ttk.Label(
            intro,
            text="What the tool needs from you (and why):",
            font=('Arial', 10, 'bold'),
            foreground='#a04000'
        ).pack(anchor='w')

        ttk.Label(
            intro,
            text=(
                "This tool audits a SolidWorks topology optimization (TO) study. "
                "To check the solver's suggestions properly, the tool needs to see the same "
                "situation the solver saw — your part, your loads, and the TO result.\n\n"
                "Files are organized into two groups below:\n"
                "  • PART FILES (one set per analysis): the part STL and the topology result CSV.\n"
                "  • LOAD CASE STRESS CSVs (one per load case used in the TO study).\n\n"
                "The good news: all of this comes from the same TO study you already ran. "
                "Nothing extra needs to be computed."
            ),
            font=('Arial', 9), foreground='#333',
            wraplength=820, justify='left'
        ).pack(anchor='w', pady=(2, 6))

        warning_frame = ttk.Frame(intro, relief='solid', borderwidth=2, padding=8)
        warning_frame.pack(fill=tk.X, pady=(4, 6))

        ttk.Label(
            warning_frame,
            text="⚠  CRITICAL: All files MUST come from the EXACT SAME part and mesh",
            font=('Arial', 10, 'bold'),
            foreground='#a02020'
        ).pack(anchor='w', pady=(0, 4))

        ttk.Label(
            warning_frame,
            text=(
                "Every CSV (stress results AND topology result) and the STL must be exported "
                "from the same SolidWorks part file (.sldprt) with the IDENTICAL mesh.\n\n"
                "If you re-meshed between exporting different files, OR exported the STL from "
                "a slightly different version of the part, OR used different mesh densities for "
                "different load cases — the node coordinates will not line up, the tool's "
                "spatial correlations will be wrong, and the audit will produce nonsense.\n\n"
                "Practical advice: complete ALL your SolidWorks Simulation studies first (every "
                "static study for every load case + the topology study), THEN export every "
                "CSV and the STL in one sitting without modifying the part or mesh in between. "
                "If you change anything in the part after exporting, re-export everything."
            ),
            font=('Arial', 9),
            foreground='#333',
            wraplength=800,
            justify='left'
        ).pack(anchor='w')

        help_btn = ttk.Button(
            intro, text="How to export each file from SolidWorks →",
            command=self._show_export_instructions
        )
        help_btn.pack(anchor='w', pady=(4, 0))

        # TOP BOX: Part files
        sec_part = ttk.LabelFrame(main, text="Part files (one set per analysis)", padding=10)
        sec_part.pack(fill=tk.X, pady=(8, 5))

        ttk.Label(
            sec_part,
            text=(
                "These files describe the part itself. There is only ONE of each per analysis, "
                "regardless of how many load cases are involved."
            ),
            font=('Arial', 9, 'italic'), foreground='#555',
            wraplength=820, justify='left'
        ).pack(anchor='w', pady=(0, 6))

        self._add_file_picker(sec_part, "Topology result CSV:", self.density_path, 'csv')
        self._add_file_picker(sec_part, "Part STL:", self.stl_path, 'stl')
        self._add_dir_picker(sec_part, "Output directory:", self.output_dir)

        ttk.Frame(main, height=10).pack()

        # BOTTOM BOX: Load case stress CSVs
        sec_loads = ttk.LabelFrame(main, text="Load case stress CSVs", padding=10)
        sec_loads.pack(fill=tk.X, pady=(8, 5))

        loads_warning = ttk.Frame(sec_loads, relief='solid', borderwidth=1, padding=6)
        loads_warning.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(
            loads_warning,
            text=(
                "⚠  You must provide the EXACT SAME load cases used in your original TO study"
            ),
            font=('Arial', 9, 'bold'),
            foreground='#a02020'
        ).pack(anchor='w')

        ttk.Label(
            loads_warning,
            text=(
                "The TO solver in SolidWorks produced its removal suggestions by considering "
                "every load case you defined in the topology study. To audit those suggestions, "
                "this tool needs to evaluate them against the same load cases.\n\n"
                "If your TO study used 3 load cases, you MUST provide all 3 stress CSVs here — "
                "one per load case. Providing fewer is not 'a partial audit' — it audits a "
                "different study than the one you ran.\n\n"
                "Providing extra load cases (ones not in the original TO study) is equally "
                "wrong: the tool would be checking the suggestions against scenarios the solver "
                "never saw.\n\n"
                "The audit only makes sense when the load cases here match the load cases the "
                "TO study used — exactly the same set, no more, no less."
            ),
            font=('Arial', 9),
            foreground='#333',
            wraplength=800,
            justify='left'
        ).pack(anchor='w', pady=(2, 0))

        lc_header = ttk.Frame(sec_loads)
        lc_header.pack(fill=tk.X, pady=(4, 4))
        ttk.Label(lc_header, text="Add one row per load case:", font=('Arial', 9, 'italic'),
                  foreground='#555').pack(side=tk.LEFT)
        ttk.Button(lc_header, text="+ Add load case", command=self._add_load_case).pack(side=tk.RIGHT)

        self.load_cases_container = ttk.Frame(sec_loads)
        self.load_cases_container.pack(fill=tk.X, pady=(4, 4))

        # Buttons
        sec4 = ttk.Frame(main)
        sec4.pack(fill=tk.X, pady=10)
        ttk.Button(sec4, text="Run Audit", command=self.run_analysis).pack(side=tk.RIGHT, padx=5)
        ttk.Button(sec4, text="Quit", command=self.root.quit).pack(side=tk.RIGHT)

        # Log
        sec5 = ttk.LabelFrame(main, text="Status / Log", padding=8)
        sec5.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_text = scrolledtext.ScrolledText(
            sec5, height=10, font=('Consolas', 9), wrap=tk.WORD
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.insert(tk.END, "Ready. Provide part files, then add one load case CSV per TO load case.\n")
        self.log_text.config(state=tk.DISABLED)

    def _add_file_picker(self, parent, label, var, ext):
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=label, width=24).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=var, width=60).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(row, text="Browse...", command=lambda: self._browse_file(var, ext)).pack(side=tk.LEFT)

    def _add_dir_picker(self, parent, label, var):
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=label, width=24).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=var, width=60).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(row, text="Browse...", command=lambda: self._browse_dir(var)).pack(side=tk.LEFT)

    def _add_load_case(self):
        idx = len(self.load_cases) + 1
        path_var = tk.StringVar()
        name_var = tk.StringVar(value=f"Load case {idx}")

        container = ttk.Frame(self.load_cases_container, relief='groove', borderwidth=1, padding=6)
        container.pack(fill=tk.X, pady=3)

        top = ttk.Frame(container)
        top.pack(fill=tk.X)
        ttk.Entry(top, textvariable=name_var, width=18).pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=path_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(top, text="Browse...", command=lambda: self._browse_file(path_var, 'csv')).pack(side=tk.LEFT)
        remove_btn = ttk.Button(top, text="X", width=3)
        remove_btn.pack(side=tk.LEFT, padx=(4, 0))

        lc_record = {
            'name': name_var,
            'path': path_var,
            'container': container,
        }
        self.load_cases.append(lc_record)
        remove_btn.config(command=lambda r=lc_record: self._remove_load_case(r))

    def _remove_load_case(self, lc_record):
        if len(self.load_cases) <= 1:
            messagebox.showinfo("Cannot remove", "At least one load case is required.")
            return
        lc_record['container'].destroy()
        self.load_cases.remove(lc_record)

    def _browse_file(self, var, ext):
        if ext == 'csv':
            filetypes = [("CSV files", "*.csv"), ("All files", "*.*")]
        else:
            filetypes = [("STL files", "*.stl *.STL"), ("All files", "*.*")]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            var.set(path)

    def _browse_dir(self, var):
        path = filedialog.askdirectory()
        if path:
            var.set(path)

    def _show_export_instructions(self):
        win = tk.Toplevel(self.root)
        win.title("How to export files from SolidWorks")
        win.geometry("760x720")
        win.transient(self.root)
        win.grab_set()

        text_frame = ttk.Frame(win, padding=15)
        text_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            text_frame, text="How to prepare files for the TO Post-Processor",
            font=('Arial', 12, 'bold')
        ).pack(anchor='w', pady=(0, 10))

        text = scrolledtext.ScrolledText(
            text_frame, wrap=tk.WORD, font=('Arial', 10),
            background='#fafafa', relief='flat', padx=10, pady=10
        )
        text.pack(fill=tk.BOTH, expand=True)

        content = """WHY THIS TOOL NEEDS THESE FILES

The tool audits a topology optimization study to filter the solver's suggestions through engineering constraints (manufacturing, structural, functional via complexity). To do that honestly, the tool must see the same data the solver saw — your part, your forces, and what the solver produced.

If you are missing any of these, the audit cannot be performed correctly.

══════════════════════════════════════════════════════════════════

BEFORE YOU EXPORT — MESH CONSISTENCY (CRITICAL)

Every file you export must come from the same part with the IDENTICAL mesh. The tool correlates stress, topology, and geometry by spatial coordinates of nodes/elements. If coordinates do not match across files, the tool associates the wrong stress with the wrong location, and the entire audit becomes garbage.

To avoid this:

  1. Finish ALL your SolidWorks Simulation studies first:
     - Static study for every load case
     - The Topology Study
     Verify they all completed successfully.

  2. Do NOT change anything in the part after the studies have run.
     No editing dimensions. No moving features. No re-meshing.
     No "let me just adjust this one thing."

  3. Export every file in one sitting:
     - All stress CSVs (one per load case)
     - The topology result CSV
     - The part STL

  4. If you need to change anything later, you must re-run the studies AND
     re-export every file. Mixing files from different versions of the part
     will produce wrong results.

══════════════════════════════════════════════════════════════════

FILE 1 — PART STL  (goes in the TOP "Part files" box)

What it is:
The geometry of the part being analysed, as a triangulated surface mesh.

How to export:
  1. Open the part (.sldprt) in SolidWorks
  2. File → Save As
  3. Change "Save as type" to STL (*.stl)
  4. Click Options → set resolution to "Fine" → OK
  5. Save with a sensible name (e.g., my_part.stl)

The tool uses the STL for 3D visualization only. The analysis itself runs on the CSVs.

══════════════════════════════════════════════════════════════════

FILE 2 — STRESS CSV (ONE PER LOAD CASE)  (goes in the BOTTOM "Load case stress CSVs" box)

What it is:
The von Mises stress at every node of the FEA mesh, for ONE load case.

You need ONE of these per load case used in your topology study. If your TO study had 3 load cases, you need 3 CSVs — add a row for each.

How to export each one — IMPORTANT TIP TO AVOID SLOW PROBES:

  1. Open the static study for that load case in SolidWorks Simulation.

  2. Right-click the "Stress1" result → Probe.

  3. >>> IMPORTANT <
     Do NOT try to click the part body itself or use a generic "Select All"
     on the geometry — that can take ages and may never complete on large
     meshes.

     Instead: in the FeatureManager design tree on the left side of the
     SolidWorks window, find the "Solid Bodies" folder (sometimes shown as
     just "Body" or "Solid Body" depending on the version), and click on
     the solid body item there. Drag it into (or select it from) the Probe
     panel's selection field.

     This tells SolidWorks to probe the entire body in one operation, which
     is far faster and far more reliable than picking faces or trying to
     select-all over the geometry.

  4. In the Probe panel, click "List Selected".

  5. In the dialog that opens, click "Save As..." and save as CSV format
     with a clear name (e.g., load_case_1_stress.csv).

  6. Repeat for every load case used in your TO study.

══════════════════════════════════════════════════════════════════

FILE 3 — TOPOLOGY RESULT CSV  (goes in the TOP "Part files" box)

What it is:
The density value (0.0 to 1.0) the solver assigned to each element. Density near 0 means "remove this material"; near 1 means "keep this material."

How to export:
  1. Open your Topology Study in SolidWorks Simulation.
  2. Right-click the "Material Mass1" result → Probe.
  3. As with the stress probe, use the Solid Body from the design tree
     (drag it into the Probe panel) rather than trying to select the
     geometry directly. Faster and more reliable.
  4. Click "List Selected".
  5. Save As... → CSV format. Use a clear name (e.g., topology_result.csv).

══════════════════════════════════════════════════════════════════

ABOUT LOAD CASES — IMPORTANT

The tool computes minimum Factor of Safety (FoS) across ALL load cases you provide.

There is no way for the tool to invent load cases that weren't analysed. The audit reflects exactly the load cases you provide — no more, no less.

══════════════════════════════════════════════════════════════════

QUICK CHECKLIST BEFORE CLICKING "RUN AUDIT"

  ☐ Part STL exported and selected (top box)
  ☐ Topology result CSV exported and selected (top box)
  ☐ One stress CSV per load case in the BOTTOM box (add rows with
    "+ Add load case" until you have one row per TO study load case)
  ☐ Output directory chosen (default "output" is fine)
  ☐ Material yield stress set correctly (check material in SolidWorks if
    unsure — PP=27.6 MPa, ABS=41, PA66=75, Al-6061=276)
  ☐ FoS threshold set (default 1.5 is standard engineering)

══════════════════════════════════════════════════════════════════

YES, IT IS A FEW STEPS

The exporting takes some time. It is the price of doing the audit honestly: the tool cannot invent data, and the engineer who ran the FEA is the only person who has all the inputs. The exports come from work you already did — nothing new needs to be computed.

If anything goes wrong during analysis, the log box at the bottom of the main window will show what failed.
"""

        text.insert(tk.END, content)
        text.config(state=tk.DISABLED)

        btn_frame = ttk.Frame(win, padding=(15, 0, 15, 15))
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Close", command=win.destroy).pack(side=tk.RIGHT)

    def _log(self, msg):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def run_analysis(self):
        load_case_specs = []
        for lc in self.load_cases:
            path = lc['path'].get().strip()
            name = lc['name'].get().strip() or f"load_case_{len(load_case_specs)+1}"
            if path:
                spec = {'name': name, 'path': path, 'mirror': False}
                load_case_specs.append(spec)

        if not load_case_specs:
            messagebox.showerror("Missing input", "Add at least one load case CSV.")
            return

        if not self.density_path.get():
            messagebox.showerror("Missing input", "Topology result CSV is required.")
            return

        if not self.stl_path.get():
            messagebox.showerror("Missing input", "Part STL is required.")
            return

        try:
            yield_val = float(self.yield_stress.get())
            fos_val = float(self.fos_threshold.get())
        except (ValueError, tk.TclError):
            messagebox.showerror("Invalid input", "Yield stress and FoS threshold must be numbers.")
            return

        if yield_val <= 0 or fos_val <= 0:
            messagebox.showerror("Invalid input", "Yield stress and FoS threshold must be positive.")
            return

        runtime_config = RuntimeConfig(
            PP_YIELD_STRESS_MPA=yield_val,
            FOS_CRITICAL_THRESHOLD=fos_val,
            COMPLEXITY_N_SIGMA=STRICT_PARAMS['n_sigma'],
            COMPLEXITY_NEIGHBORHOOD_RADIUS_FACTOR=STRICT_PARAMS['neighborhood_radius_factor'],
            COMPLEXITY_MIN_NEIGHBOR_COUNT_FACTOR=STRICT_PARAMS['min_neighbor_count_factor'],
            LOAD_CASES=load_case_specs,
            TOPOLOGY_DENSITY_FILE=self.density_path.get(),
            BUMPER_STL_FILE=self.stl_path.get(),
            OUTPUT_DIR=self.output_dir.get() or "output",
        )

        self._log("=" * 60)
        self._log(f"Audit running with strict parameters (only mode)")
        self._log(f"Yield: {yield_val} MPa | FoS threshold: {fos_val}")
        self._log(f"Load cases: {len(load_case_specs)}")
        for lc in load_case_specs:
            self._log(f"  - {lc['name']}: {lc['path']}")
        self._log("Spatial parameters will be auto-derived from input data.")
        self._log("=" * 60)

        thread = threading.Thread(target=self._run_analysis_thread, args=(runtime_config,))
        thread.daemon = True
        thread.start()

    def _run_analysis_thread(self, runtime_config):
        try:
            old_stdout = sys.stdout
            sys.stdout = LogRedirector(self._log)
            try:
                from main import run_pipeline
                run_pipeline(runtime_config)
            finally:
                sys.stdout = old_stdout

            self._log("=" * 60)
            self._log("AUDIT COMPLETE. See output folder for report and screenshots.")
            self._log("")
            self._log("Remember: regions NOT flagged are not approved — they are simply")
            self._log("not caught by the tool's filters. Engineering verification still required.")
            self._log("")
            self._log("-" * 60)
            self._log("CALIBRATION CAVEAT — please read")
            self._log("-" * 60)
            self._log("The structural-junction detector uses an absolute threshold of 20")
            self._log("high-density elements within the probe radius to identify load-routing")
            self._log("junctions. This threshold was calibrated against the bumper case study")
            self._log("(mesh spacing ~3 mm). On parts with substantially coarser meshes")
            self._log("(spacing > 6 mm), this threshold may not be reached even at genuine")
            self._log("junctions, causing the detector to miss them.")
            self._log("")
            self._log("If your part has a coarser mesh than ~3 mm spacing: the structural")
            self._log("filter's OTHER checks (FoS adjacency, critical-zone proximity) still")
            self._log("fire correctly, but specifically the junction detector may under-")
            self._log("trigger. Manually verify removal regions at visually identifiable")
            self._log("rib/wall intersections before trusting any 'not flagged' verdict in")
            self._log("those areas.")
            self._log("")
            self._log("Similarly: the tunnel detector uses an absolute aspect ratio of 2.5:1")
            self._log("and asymmetry of 3.0x. These are calibrated to typical automotive-")
            self._log("component scales. Substantially different scales may need")
            self._log("re-calibration.")
            self._log("")
            self._log("Statistical-floor calibration (max of absolute_floor and per-part")
            self._log("statistic) was investigated but requires further validation; this")
            self._log("is articulated as concrete future work.")
            self._log("-" * 60)
        except Exception as e:
            self._log("=" * 60)
            self._log(f"ERROR: {e}")
            self._log(traceback.format_exc())


class LogRedirector:
    def __init__(self, log_callback):
        self.log_callback = log_callback
        self.buffer = ""

    def write(self, msg):
        self.buffer += msg
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            if line:
                self.log_callback(line)

    def flush(self):
        if self.buffer:
            self.log_callback(self.buffer)
            self.buffer = ""


class RuntimeConfig:
    DENSITY_REMOVAL_THRESHOLD = 0.5
    COMPLEXITY_K_NEIGHBORS = 8
    PATTERN_ISOLATED_NEIGHBOR_RATIO = 0.7
    PATTERN_MESA_HIGH_DENSITY_THRESHOLD = 0.8
    STRESS_INTERPOLATION_K = 4

    LOAD_CASES = []
    TOPOLOGY_DENSITY_FILE = ""
    BUMPER_STL_FILE = ""
    OUTPUT_DIR = "output"
    FUNCTIONAL_ZONES_FILE = "functional_zones.json"

    PP_YIELD_STRESS_MPA = 27.6
    FOS_CRITICAL_THRESHOLD = 1.5

    COMPLEXITY_N_SIGMA = 1.0
    COMPLEXITY_NEIGHBORHOOD_RADIUS_FACTOR = 2.0
    COMPLEXITY_MIN_NEIGHBOR_COUNT_FACTOR = 0.005

    ADJACENCY_RADIUS_MM = None
    STRUCTURAL_ADJACENCY_RADIUS_MM = None
    COMPLEXITY_SPREAD_RADIUS_MM = None
    COMPLEXITY_NEIGHBORHOOD_RADIUS_MM = None
    COMPLEXITY_MIN_NEIGHBOR_COUNT = None
    PATTERN_MIN_REGION_SIZE = None

    CASE_NAMES = []

    @property
    def REPORT_TEXT_FILE(self):
        import os
        return os.path.join(self.OUTPUT_DIR, "post_processor_report.txt")

    @property
    def REPORT_JSON_FILE(self):
        import os
        return os.path.join(self.OUTPUT_DIR, "post_processor_results.json")

    def __init__(self, **overrides):
        for k, v in overrides.items():
            if hasattr(self.__class__, k):
                setattr(self, k, v)


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        style.theme_use('clam')
    except Exception:
        pass
    app = TOPostProcessorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()