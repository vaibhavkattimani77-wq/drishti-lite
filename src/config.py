"""Project-wide settings: the drugs we study and the signal criteria we use.

Change things here, not inside the code. Every value below is a documented
decision - mention it in the README if you change it.
"""

# Drugs shown in the app's drug picker.
# Each has at least one well-known, label-listed adverse reaction, so you can
# check that the dashboard "finds" something real (the worked example).
DRUGS = {
    "Atorvastatin": "ATORVASTATIN",      # statin -> rhabdomyolysis, myalgia
    "Ciprofloxacin": "CIPROFLOXACIN",    # fluoroquinolone -> tendon rupture
    "Montelukast": "MONTELUKAST",        # neuropsychiatric events (boxed warning)
    "Semaglutide": "SEMAGLUTIDE",        # GLP-1 RA -> pancreatitis, GI events
    "Isotretinoin": "ISOTRETINOIN",      # depression, teratogenicity
}

# Known drug-event pairs used for the worked example in the README.
KNOWN_PAIRS = [
    ("Atorvastatin", "RHABDOMYOLYSIS"),
    ("Ciprofloxacin", "TENDON RUPTURE"),
    ("Montelukast", "NIGHTMARE"),
    ("Semaglutide", "PANCREATITIS"),
]

# Predefined signal rules (spec section 4.4). Adjustable in the sidebar later;
# the values actually used are saved in the extraction record.
#   PRR rule (Evans et al. 2001): PRR >= 2 AND a >= 3 AND chi-square (Yates) >= 4
PRR_MIN = 2.0
PRR_CASES_MIN = 3
CHI2_MIN = 4.0
#   ROR rule: lower 95% CI of ROR > 1 AND a >= 3
ROR_LOWER_MIN = 1.0
ROR_CASES_MIN = 3
#   IC rule (WHO-UMC practice; Noren et al. 2013): IC025 > 0
IC025_MIN = 0.0

# Small-numbers warning shown when a (cases) is below this value.
SMALL_NUMBERS_BELOW = 5

# How many of the drug's most frequently reported reactions to analyse.
TOP_N_REACTIONS = 100

# openFDA settings
OPENFDA_BASE = "https://api.fda.gov/drug/event.json"
CACHE_PATH = "data/cache.sqlite"
CACHE_DAYS = 30            # re-download cached answers older than this
SECONDS_BETWEEN_CALLS = 0.3  # stay under openFDA's 240 requests/minute limit

# EMA Designated Medical Event list (see data/ema_dme_list_VERSION.txt)
DME_LIST_PATH = "data/ema_dme_list.csv"
DME_VERSION_PATH = "data/ema_dme_list_VERSION.txt"

# Version shown in every extraction record (the git commit is added when available).
APP_VERSION = "0.1.0-phase1"

# Where each analysis saves its extraction record and results table.
EXTRACTIONS_DIR = "data/extractions"
