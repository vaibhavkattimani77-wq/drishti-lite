"""All tunable settings for DRISHTI-lite, in one place.

Every value here is a documented design choice (see DRISHTI-lite_Spec_v2.md).
If you change one, say so in the README and PROJECT_NOTES.md.
"""

APP_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Drugs in the picker (free text is also allowed in the app)
# ---------------------------------------------------------------------------
DRUGS = {
    "Atorvastatin": "ATORVASTATIN",      # statin: rhabdomyolysis, myalgia
    "Ciprofloxacin": "CIPROFLOXACIN",    # fluoroquinolone: tendon rupture
    "Montelukast": "MONTELUKAST",        # neuropsychiatric events (boxed warning)
    "Semaglutide": "SEMAGLUTIDE",        # GLP-1 RA: pancreatitis, GI events
    "Isotretinoin": "ISOTRETINOIN",      # depression, teratogenicity
}

# Pairs expected to show disproportionate reporting (sanity checks, Gate 1).
KNOWN_PAIRS = [
    ("Atorvastatin", "RHABDOMYOLYSIS"),
    ("Ciprofloxacin", "TENDON RUPTURE"),
    ("Montelukast", "NIGHTMARE"),
    ("Semaglutide", "PANCREATITIS"),
]

# ---------------------------------------------------------------------------
# Predefined signal rules (spec §4.4). Defaults; adjustable in the sidebar.
# ---------------------------------------------------------------------------
PRR_MIN = 2.0          # PRR rule (Evans et al. 2001): PRR >= 2 ...
CASES_MIN = 3          # ... and a >= 3 (also used by the ROR rule) ...
CHI2_MIN = 4.0         # ... and Yates chi-square >= 4
ROR_LOWER_MIN = 1.0    # ROR rule: lower 95% CI of ROR > 1 (and a >= CASES_MIN)
IC025_MIN = 0.0        # IC rule (WHO-UMC practice): IC025 > 0

SMALL_NUMBERS_BELOW = 5   # a < 5 -> small-numbers warning (spec §4.3)
Z_95 = 1.96

# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------
TOP_N_REACTIONS = 100      # reactions analysed per drug (default)
TOP_N_MAX = 1000           # openFDA count queries return at most 1,000 values

# ---------------------------------------------------------------------------
# Trend (spec §4.5)
# ---------------------------------------------------------------------------
TREND_QUARTERS = 8               # 4 recent complete quarters vs the 4 before
TREND_RISING_RATIO = 1.5
TREND_FALLING_RATIO = 0.67
TREND_MIN_RECENT = 3             # rising also needs >= 3 reports in the last 4 quarters
TREND_MIN_TOTAL = 6              # fewer than 6 reports in 8 quarters -> insufficient data

# ---------------------------------------------------------------------------
# Exploratory prioritisation score (spec §5, Screen 2). NOT a validated model.
# ---------------------------------------------------------------------------
SCORE_NOT_FOUND_IN_LABEL = 2
SCORE_POSSIBLY_LABELLED = 1
SCORE_DME = 2
SCORE_FATAL = 2
SCORE_MOSTLY_SERIOUS = 1          # > 50% of reports serious
SCORE_RULES_3 = 2
SCORE_RULES_2 = 1
SCORE_INCREASING = 1
SCORE_MAX = 10
BAND_HIGHER_MIN = 7               # Higher >= 7, Medium 4-6, Lower <= 3
BAND_MEDIUM_MIN = 4

# ---------------------------------------------------------------------------
# openFDA
# ---------------------------------------------------------------------------
OPENFDA_EVENT = "https://api.fda.gov/drug/event.json"
OPENFDA_LABEL = "https://api.fda.gov/drug/label.json"
LABEL_CANDIDATES = 25        # recent labels fetched to pick the latest single-ingredient one
CACHE_PATH = "data/cache.sqlite"
CACHE_DAYS = 30                  # raw answers kept 30 days (spec §3)
SECONDS_BETWEEN_CALLS = 0.3      # stay under openFDA's 240 requests/minute

# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
DME_CSV = "data/ema_dme_list.csv"
DME_VERSION_TXT = "data/ema_dme_list_VERSION.txt"
EXTRACTIONS_DIR = "data/extractions"
SIGNAL_LOG_PATH = "data/signal_log.sqlite"
SIGNAL_LOG_SEED = "data/signal_log_seed.json"   # committed; loaded when the log is empty
RATIONALE_MIN = 50                               # characters (spec §5, Screen 4)
