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

# Signal criteria (Evans et al., 2001 - widely used for spontaneous reports):
#   PRR >= 2, at least 3 cases, and chi-square (Yates) >= 4
SIGNAL_PRR_MIN = 2.0
SIGNAL_CASES_MIN = 3
SIGNAL_CHI2_MIN = 4.0

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
