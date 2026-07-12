"""
TO Post-Processor configuration
"""

# Material properties
PP_YIELD_STRESS_MPA = 27.6  # Polypropylene copolymer yield strength

# Filter thresholds
FOS_CRITICAL_THRESHOLD = 1.5
DENSITY_REMOVAL_THRESHOLD = 0.5

# Mesh processing
ADJACENCY_RADIUS_MM = 2.0
STRESS_INTERPOLATION_K = 4
STRUCTURAL_ADJACENCY_RADIUS_MM = 15.0

# Pattern classification
PATTERN_ISOLATED_NEIGHBOR_RATIO = 0.7
PATTERN_MESA_HIGH_DENSITY_THRESHOLD = 0.8
PATTERN_MIN_REGION_SIZE = 5

# File paths
DATA_DIR = "data"
FRONTAL_STRESS_FILE = "data/frontal_stress.csv"
SIDE_A_STRESS_FILE = "data/side_a_stress.csv"
SIDE_B_STRESS_FILE = "data/side_b_stress.csv"
TOPOLOGY_DENSITY_FILE = "data/topology_density.csv"
BUMPER_STL_FILE = "data/bumper.STL"
FUNCTIONAL_ZONES_FILE = "functional_zones.json"

# Output paths
REPORT_TEXT_FILE = "output/post_processor_report.txt"
REPORT_JSON_FILE = "output/post_processor_results.json"

# Complexity filter parameters
COMPLEXITY_K_NEIGHBORS = 8
COMPLEXITY_SPREAD_RADIUS_MM = 8.0
COMPLEXITY_N_SIGMA = 1.0
COMPLEXITY_NEIGHBORHOOD_RADIUS_MM = 18.0       # NEW: sphere around centroid for layer-2 check
COMPLEXITY_MIN_NEIGHBOR_COUNT = 20             # NEW: how many high-complex elements trigger rejection