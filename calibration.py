# calibration.py
TEMP_Z = 1.05  # ← CHANGED from 1.45
BALANCE_BIAS = 0.15  # ← CHANGED from 0.20
CLIP_MIN = 0.08
CLIP_MAX = 0.92
MULT_CENTER = 1.00
MULT_MAX_DEV = 0.15
EMP_PRIOR_K = 20
W_EMP_MAX = 0.30
INCLUDE_LAST_SEASON = True
SHRINK_TO_LEAGUE = 0.10

# Sigma scaling by stat type (tuned 11/12/2025)
SIGMA_SCALE = {
    "PTS": 1.00,
    "REB": 0.90,
    "AST": 0.95,
    "PRA": 0.97,
    "REB+AST": 0.92,
    "PTS+REB": 0.93,
    "PTS+AST": 0.93,
    "FG3M": 1.10
}